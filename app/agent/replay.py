from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from app.agent.models import (
    AgentTurnResult,
    SessionState,
    ToolCallRecord,
    ToolCallResponse,
)
from app.agent.providers import ScriptedToolCallingProvider


class ScriptedToolGateway:
    """按脚本返回预先记录的工具结果，不执行真实工具。

    用于 trace replay：从 trace artifact 的 tool_calls 段重建
    ToolCallRecord 列表，注入到 AgentLoop 替代真实 ToolGateway。
    """

    def __init__(self, results: List[ToolCallRecord]) -> None:
        self._results = list(results)
        self.calls: List[dict] = []
        self.consumed: List[ToolCallRecord] = []

    def execute(
        self,
        state: Any,
        tool_name: str,
        arguments: dict,
        confirmed: bool = False,
    ) -> ToolCallRecord:
        self.calls.append({
            "tool_name": tool_name,
            "arguments": arguments,
            "confirmed": confirmed,
        })
        if not self._results:
            raise RuntimeError(
                f"No scripted tool results remain for {tool_name}"
            )
        expected = self._results.pop(0)
        if (
            expected.tool_name != tool_name
            or expected.arguments != arguments
        ):
            raise RuntimeError(
                "Tool mismatch: expected "
                f"{expected.tool_name}({expected.arguments}), "
                f"got {tool_name}({arguments})"
            )
        if hasattr(state, "tool_results"):
            state.tool_results.append(expected)
        if (
            expected.status == "success"
            and expected.tool_kind == "write"
            and expected.resource_lock
            and hasattr(state, "write_locks")
        ):
            state.write_locks.append(expected.resource_lock)
        if expected.status == "success" and hasattr(state, "loaded_context"):
            self._update_loaded_context(state, expected)
        if (
            expected.status == "success"
            and expected.tool_name.startswith("find_user_id_by_")
            and isinstance(expected.observation, str)
            and hasattr(state, "authenticated_user_id")
            and not state.authenticated_user_id
        ):
            state.authenticated_user_id = expected.observation
        self.consumed.append(expected)
        return expected

    @staticmethod
    def _update_loaded_context(state: Any, record: ToolCallRecord) -> None:
        if record.tool_name == "get_order_details" and isinstance(
            record.observation, dict
        ):
            order_id = str(record.arguments.get("order_id", ""))
            clean_id = order_id.lstrip("#")
            state.loaded_context.orders[clean_id] = record.observation
            state.loaded_context.orders[f"#{clean_id}"] = record.observation
            if order_id not in (clean_id, f"#{clean_id}"):
                state.loaded_context.orders[order_id] = record.observation
        elif record.tool_name == "get_user_details" and isinstance(
            record.observation, dict
        ):
            user_id = str(record.arguments.get("user_id", ""))
            state.loaded_context.users.setdefault(user_id, record.observation)


class TraceReplayHarness:
    """从 trace artifact 回放单轮对话。

    加载 trace JSON，提取 LLM 响应序列和工具结果序列，
    用 ScriptedToolCallingProvider + ScriptedToolGateway 驱动 AgentLoop。
    """

    def __init__(self, trace_path: Path, registry) -> None:
        with open(trace_path) as f:
            self._trace = json.load(f)

        raw_responses = self._trace.get("llm_responses", [])
        self._responses = [
            ToolCallResponse(**r) for r in raw_responses
        ]

        raw_tool_calls = self._trace.get("tool_calls", [])
        self._tool_results = [
            ToolCallRecord(**tc) for tc in raw_tool_calls
        ]

        self._registry = registry
        self._user_messages = [
            str(message.get("content", ""))
            for message in self._trace.get("messages", [])
            if message.get("role") == "user"
        ]
        self._turn_scripts = self._build_turn_scripts()
        self._turn_index = 0
        self._tool_index = 0
        self._tool_gateway = ScriptedToolGateway(results=list(self._tool_results))

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._trace.get("metadata", {}))

    @property
    def run_id(self) -> str | None:
        raw_run_id = self._trace.get("run_id")
        return str(raw_run_id) if raw_run_id is not None else None

    @property
    def final_state(self) -> dict[str, Any]:
        return dict(self._trace.get("final_state", {}))

    @property
    def messages(self) -> List[dict[str, Any]]:
        return list(self._trace.get("messages", []))

    @property
    def has_llm_responses(self) -> bool:
        return bool(self._responses)

    @property
    def task_id(self) -> str | None:
        metadata = self.metadata
        return metadata.get("task_id") or self._trace.get("task_id")

    @property
    def user_messages(self) -> List[str]:
        return list(self._user_messages)

    @property
    def tool_results(self) -> List[ToolCallRecord]:
        return list(self._tool_results)

    @property
    def consumed_tool_results(self) -> List[ToolCallRecord]:
        return list(self._tool_gateway.consumed)

    @property
    def remaining_tool_results(self) -> List[ToolCallRecord]:
        return list(self._tool_gateway._results)

    def replay(
        self,
        session: SessionState,
        user_message: str,
        *,
        context_builder,
    ) -> AgentTurnResult:
        """回放单轮：用记录的 LLM 响应和工具结果驱动 AgentLoop。"""
        from app.agent.llm_agent import AgentLoop

        if self._turn_index >= len(self._turn_scripts):
            raise RuntimeError("No replay turn script remains")
        responses, tool_results = self._turn_scripts[self._turn_index]
        self._turn_index += 1

        provider = ScriptedToolCallingProvider(
            responses=list(responses)
        )

        loop = AgentLoop(
            provider=provider,
            gateway=self._tool_gateway,
            registry=self._registry,
            context_builder=context_builder,
        )
        return loop.run_turn(session, user_message)

    def consume_tool_result(
        self,
        *,
        session: SessionState,
        tool_name: str,
        arguments: dict,
        confirmed: bool = False,
    ) -> ToolCallRecord:
        return self._tool_gateway.execute(
            state=session,
            tool_name=tool_name,
            arguments=arguments,
            confirmed=confirmed,
        )

    def _build_turn_scripts(
        self,
    ) -> List[tuple[List[ToolCallResponse], List[ToolCallRecord]]]:
        turns: List[tuple[List[ToolCallResponse], List[ToolCallRecord]]] = []
        tool_index = 0
        responses = list(self._responses)
        total_tools = len(self._tool_results)

        idx = 0
        while idx < len(responses):
            turn_responses: List[ToolCallResponse] = []
            turn_tools: List[ToolCallRecord] = []
            while idx < len(responses):
                response = responses[idx]
                idx += 1
                turn_responses.append(response)

                matched_tools: List[ToolCallRecord] = []
                for tool_call in response.tool_calls:
                    if tool_index >= total_tools:
                        raise RuntimeError(
                            "Replay trace is missing a recorded tool result for "
                            f"{tool_call.tool_name}"
                        )
                    expected = self._tool_results[tool_index]
                    if (
                        expected.tool_name != tool_call.tool_name
                        or expected.arguments != tool_call.arguments
                    ):
                        raise RuntimeError(
                            "Replay trace tool mismatch: expected "
                            f"{expected.tool_name}({expected.arguments}), got "
                            f"{tool_call.tool_name}({tool_call.arguments})"
                        )
                    matched_tools.append(expected)
                    tool_index += 1
                turn_tools.extend(matched_tools)

                if not response.tool_calls:
                    break
                if any(
                    record.status == "blocked"
                    and record.error == "explicit_confirmation_required"
                    for record in matched_tools
                ):
                    break

            turns.append((turn_responses, turn_tools))

        return turns
