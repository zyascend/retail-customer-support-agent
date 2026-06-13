from __future__ import annotations

import time
from typing import Any

from app.agent.context_builder import ContextBuilder
from app.agent.models import (
    AgentTurnResult,
    SessionState,
    ToolCallResponse,
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

            response = self._step_llm_reason(messages, tool_schemas)
            turn.step_durations["llm_reason"] = round(
                (time.perf_counter() - t0) * 1000, 1
            )
            turn.add_step("llm_reason", finish_reason=response.finish_reason)

            if response.token_usage:
                turn.llm_token_usage = response.token_usage

            if not response.tool_calls:
                return self._step_finalize(response, turn)

            # Tool execution placeholder (to be implemented in next tasks)
            turn.termination = "max_iterations"
            return AgentTurnResult(
                assistant_message="I'm sorry, I couldn't process your request.",
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

    # ── Internal helpers ──

    def _load_system_prompt_template(self) -> str:
        from pathlib import Path
        prompt_path = Path("prompts/llm_agent_system_v001.md")
        template = prompt_path.read_text(encoding="utf-8")
        tool_catalog = self._registry.tool_catalog_for_llm()
        policy_text = ""
        if hasattr(self._context_builder, "_policy_text"):
            policy_text = self._context_builder._policy_text
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
