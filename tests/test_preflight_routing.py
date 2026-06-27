from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.agent.confirmation import ConfirmationResolver
from app.agent.models import PendingAction, SessionState
from app.agent.runtime import AgentRuntime
from app.config import resolve_config


def _runtime_with_pending() -> tuple[AgentRuntime, SessionState]:
    """Construct a minimal AgentRuntime (no LLM) with a pending action."""
    config = resolve_config(artifact_dir=str(Path("/tmp")))
    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime.config = config
    runtime.gateway = MagicMock()
    runtime._resolver = ConfirmationResolver()
    runtime.provider = None
    runtime._context_builder = MagicMock()
    runtime._turn_contexts = []
    state = SessionState(session_id="t")
    state.authenticated_user_id = "u1"
    state.pending_action = PendingAction(
        action_name="cancel_pending_order",
        arguments={"order_id": "#W1", "reason": "no longer needed"},
        user_facing_summary="cancel",
    )
    return runtime, state


def test_clean_confirm_short_circuits() -> None:
    runtime, state = _runtime_with_pending()
    runtime.gateway.execute.return_value = MagicMock(status="success", observation={})
    runtime._preflight_confirmation(state, "yes")
    # 干净确认 → gateway 用 confirmed=True 执行
    assert runtime.gateway.execute.call_args.kwargs.get("confirmed") is True
    assert state.pending_action is None


def test_clean_deny_discards() -> None:
    runtime, state = _runtime_with_pending()
    msg = runtime._preflight_confirmation(state, "no")
    assert state.pending_action is None
    assert "No changes" in msg


def test_changed_discards_pending() -> None:
    runtime, state = _runtime_with_pending()
    msg = runtime._preflight_confirmation(
        state, "No, use item 1234567890 instead."
    )
    assert state.pending_action is None
    assert "discarded" in msg.lower()


def test_mixed_confirm_falls_through_to_llm() -> None:
    runtime, state = _runtime_with_pending()
    msg = runtime._preflight_confirmation(state, "嗯行吧不过换成 express")
    # mixed → 放行 LLM, return None, pending 保持
    assert msg is None
    assert state.pending_action is not None


def test_denied_with_question_falls_through() -> None:
    runtime, state = _runtime_with_pending()
    msg = runtime._preflight_confirmation(state, "算了别取消了，退款多少？")
    # denied + 提问 → 丢弃 pending 后放行 LLM
    assert msg is None
    assert state.pending_action is None
