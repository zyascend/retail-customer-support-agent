from __future__ import annotations

import time
from typing import Any

from app.agent.context_builder import ContextBuilder
from app.agent.models import (
    AgentTurnResult,
    PendingAction,
    SessionState,
    ToolCallRecord,
    ToolCallRequest,
    ToolCallResponse,
    ToolExecutionError,
    TurnContext,
)
from app.agent.providers import LLMProvider
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry


class AgentLoop:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        gateway: ToolGateway,
        registry: ToolRegistry,
        context_builder: ContextBuilder,
        max_iterations: int = 5,
        max_consecutive_failures: int = 3,
    ) -> None:
        self._provider = provider
        self._gateway = gateway
        self._registry = registry
        self._context_builder = context_builder
        self._max_iterations = max_iterations
        self._max_consecutive_failures = max_consecutive_failures
        self._system_prompt_template = self._load_system_prompt_template()

    def run_turn(
        self, session: SessionState, user_content: str
    ) -> AgentTurnResult:
        turn = TurnContext()
        messages = self._build_messages(session, user_content)
        tool_schemas = self._registry.tool_schemas_for_llm()

        while turn.loop_iterations < self._max_iterations:
            turn.loop_iterations += 1
            t0 = time.perf_counter()

            try:
                response = self._step_llm_reason(messages, tool_schemas)
            except TimeoutError:
                turn.termination = "provider_timeout"
                turn.add_step("provider_timeout")
                return AgentTurnResult(
                    assistant_message=(
                        "I'm having trouble processing your request right now. "
                        "Please try again in a moment."
                    ),
                    turn=turn,
                )

            # Phase 6: record LLM response for trace replay
            turn.llm_responses.append(response.model_dump())

            turn.step_durations["llm_reason"] = round(
                (time.perf_counter() - t0) * 1000, 1
            )
            turn.add_step("llm_reason", finish_reason=response.finish_reason)

            if response.token_usage:
                turn.llm_token_usage = response.token_usage

            if not response.tool_calls:
                return self._step_finalize(response, turn)

            # Execute each tool call
            assistant_msg = self._assistant_message_dict(response)
            messages.append(assistant_msg)

            all_failed = True
            for tc in response.tool_calls:
                record, obs_msg = self._step_tool_execute(session, tc, turn)

                if record is not None and record.status == "blocked" and record.error == "explicit_confirmation_required":
                    return self._step_pending(session, tc, turn)

                if obs_msg is not None:
                    messages.append(obs_msg)

                if record is not None and record.status == "success":
                    all_failed = False

            if all_failed:
                turn.consecutive_tool_failures += 1
            else:
                turn.consecutive_tool_failures = 0

            if turn.consecutive_tool_failures >= self._max_consecutive_failures:
                turn.termination = "consecutive_failures"
                turn.add_step("consecutive_failures_limit")
                return AgentTurnResult(
                    assistant_message=(
                        "I'm unable to complete this request. "
                        "Let me transfer you to a human agent."
                    ),
                    turn=turn,
                )

        turn.termination = "max_iterations"
        return AgentTurnResult(
            assistant_message=(
                "I'm having trouble processing your request. "
                "Let me transfer you to a human agent."
            ),
            turn=turn,
        )

    # ── Step methods ──

    def _step_llm_reason(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ToolCallResponse:
        return self._provider.chat_with_tools(messages=messages, tools=tools)

    def _step_finalize(
        self, response: ToolCallResponse, turn: TurnContext
    ) -> AgentTurnResult:
        turn.termination = "final_response"
        turn.add_step("finalize")
        return AgentTurnResult(
            assistant_message=response.assistant_content or "",
            turn=turn,
        )

    def _step_tool_execute(
        self,
        session: SessionState,
        tool_call: ToolCallRequest,
        turn: TurnContext,
    ) -> tuple[ToolCallRecord | None, dict[str, Any] | None]:
        """Execute a single tool call. Returns (record, error_message_dict_or_None)."""
        # Pre-gateway validation
        validation_error = self._validate_tool_call(tool_call)
        if validation_error:
            return None, {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": validation_error.model_dump_json(),
            }

        t0 = time.perf_counter()
        record = self._gateway.execute(
            state=session,
            tool_name=tool_call.tool_name,
            arguments=tool_call.arguments,
        )
        turn.step_durations[f"tool_{tool_call.tool_name}"] = round(
            (time.perf_counter() - t0) * 1000, 1
        )
        turn.add_step("tool_execute", tool_name=tool_call.tool_name, status=record.status)

        # Build tool observation message
        if record.status == "success":
            obs = record.observation
            obs_str = str(obs)[:500] if obs is not None else "(none)"
            return record, {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": obs_str,
            }
        elif record.status == "blocked":
            if record.error == "explicit_confirmation_required":
                return record, None  # caller handles pending
            else:
                error_msg = ToolExecutionError(
                    error_type="guard_blocked",
                    message_for_llm=(
                        f"Tool {tool_call.tool_name} was blocked: {record.error}. "
                        "Explain this to the user and suggest alternatives."
                    ),
                    retryable=False,
                )
                return record, {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": error_msg.model_dump_json(),
                }
        else:
            error_msg = ToolExecutionError(
                error_type="tool_execution_error",
                message_for_llm=(
                    f"Tool {tool_call.tool_name} failed: {record.error or 'unknown error'}"
                ),
                retryable=True,
            )
            return record, {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": error_msg.model_dump_json(),
            }

    def _step_pending(
        self, session: SessionState, tool_call: ToolCallRequest, turn: TurnContext
    ) -> AgentTurnResult:
        """Set pending action and return a confirmation-request turn result."""
        session.pending_action = PendingAction(
            action_name=tool_call.tool_name,
            arguments=dict(tool_call.arguments),
            user_facing_summary=(
                f"{tool_call.tool_name}: "
                f"{', '.join(f'{k}={v}' for k, v in tool_call.arguments.items())}"
            ),
        )
        turn.termination = "pending_confirmation"
        turn.add_step("pending_set", tool_name=tool_call.tool_name)
        return AgentTurnResult(
            assistant_message=(
                f"I'd like to {tool_call.tool_name.replace('_', ' ')}. "
                "Can you confirm?"
            ),
            turn=turn,
            pending_action_set=True,
        )

    # ── Internal helpers ──

    def _load_system_prompt_template(self) -> str:
        from pathlib import Path
        prompt_path = Path("prompts/llm_agent_system_v001.md")
        template = prompt_path.read_text(encoding="utf-8")
        tool_catalog = self._registry.tool_catalog_for_llm()
        policy_text = self._context_builder.policy_text
        return (
            template.replace("{tool_catalog}", tool_catalog)
            .replace("{policy}", policy_text)
        )
    # Note: {state_summary} is replaced dynamically in _build_messages

    def _build_messages(
        self, session: SessionState, user_content: str
    ) -> list[dict[str, Any]]:
        state_summary = self._context_builder.build(session)
        system_prompt = self._system_prompt_template.replace(
            "{state_summary}", state_summary
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        for msg in session.messages[-6:]:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_content})
        return messages

    def _validate_tool_call(
        self, tool_call: ToolCallRequest
    ) -> ToolExecutionError | None:
        if tool_call.tool_name not in self._registry.tools:
            return ToolExecutionError(
                error_type="unknown_tool",
                message_for_llm=(
                    f"Unknown tool: '{tool_call.tool_name}'. "
                    f"Available tools: {sorted(self._registry.tools)}"
                ),
                retryable=True,
                allowed_tools=sorted(self._registry.tools),
            )
        required = self._registry.required_args_for_tool(tool_call.tool_name)
        missing = [a for a in required if not tool_call.arguments.get(a)]
        if missing:
            return ToolExecutionError(
                error_type="missing_required_args",
                message_for_llm=(
                    f"Missing required arguments for {tool_call.tool_name}: {missing}"
                ),
                retryable=True,
                missing_args=missing,
            )
        if tool_call.raw_arguments is not None and not tool_call.arguments:
            return ToolExecutionError(
                error_type="malformed_arguments",
                message_for_llm=(
                    f"Could not parse arguments for {tool_call.tool_name}. "
                    "Please provide valid JSON arguments."
                ),
                retryable=True,
            )
        return None

    @staticmethod
    def _assistant_message_dict(response: ToolCallResponse) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": response.assistant_content}
        if response.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": tc.raw_arguments or "{}",
                    },
                }
                for tc in response.tool_calls
            ]
        return msg
