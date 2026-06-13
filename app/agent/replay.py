from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

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
        if expected.tool_name != tool_name:
            raise RuntimeError(
                f"Tool mismatch: expected {expected.tool_name}, got {tool_name}"
            )
        return expected


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

    def replay(
        self,
        session: SessionState,
        user_message: str,
        *,
        context_builder,
    ) -> AgentTurnResult:
        """回放单轮：用记录的 LLM 响应和工具结果驱动 AgentLoop。"""
        from app.agent.llm_agent import AgentLoop

        provider = ScriptedToolCallingProvider(
            responses=list(self._responses)
        )
        gateway = ScriptedToolGateway(
            results=list(self._tool_results)
        )

        loop = AgentLoop(
            provider=provider,
            gateway=gateway,
            registry=self._registry,
            context_builder=context_builder,
        )
        return loop.run_turn(session, user_message)
