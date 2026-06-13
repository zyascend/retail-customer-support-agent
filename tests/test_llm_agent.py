from __future__ import annotations

from app.agent.context_builder import ContextBuilder
from app.agent.models import (
    SessionState,
    ToolCallResponse,
)
from app.agent.providers import ScriptedToolCallingProvider
from app.config import resolve_config
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry
from app.tools.retail_adapter import RetailAdapter


def _registry() -> ToolRegistry:
    runtime = RetailAdapter(resolve_config()).create_runtime()
    return ToolRegistry(runtime.tools)


def _gateway() -> ToolGateway:
    runtime = RetailAdapter(resolve_config()).create_runtime()
    registry = ToolRegistry(runtime.tools)
    return ToolGateway(registry=registry, runtime=runtime)


def _context_builder() -> ContextBuilder:
    policy_path = resolve_config().retail_policy_path
    policy_text = policy_path.read_text()[:500] if policy_path.exists() else ""
    return ContextBuilder(policy_text=policy_text)


def _session(**kwargs) -> SessionState:
    defaults = dict(
        session_id="test-1",
        authenticated_user_id="U1",
        auth_method="email",
        active_user_identity={"user_id": "U1", "name": "Test User", "email": "test@example.com"},
    )
    defaults.update(kwargs)
    return SessionState(**defaults)


class TestAgentLoopBasic:
    """Tests: single-turn response, no tool calls."""

    def test_direct_text_response_no_tools(self) -> None:
        from app.agent.llm_agent import AgentLoop

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    assistant_content="Hello! How can I help you today?",
                    finish_reason="stop",
                )
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        session = _session()
        result = loop.run_turn(session, "Hi")

        assert result.assistant_message == "Hello! How can I help you today?"
        assert result.turn.loop_iterations == 1
        assert result.turn.termination == "final_response"
        assert result.pending_action_set is False

    def test_turn_context_has_steps(self) -> None:
        from app.agent.llm_agent import AgentLoop

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    assistant_content="Done.",
                    finish_reason="stop",
                )
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(_session(), "Hello")

        assert len(result.turn.steps) > 0
        assert any(s.node == "llm_reason" for s in result.turn.steps)
        assert any(s.node == "finalize" for s in result.turn.steps)
