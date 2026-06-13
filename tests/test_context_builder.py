from __future__ import annotations

from app.agent.context_builder import ContextBuilder
from app.agent.models import Message, PendingAction, SessionState, ToolCallRecord


def _session() -> SessionState:
    session = SessionState(
        session_id="ctx-1",
        authenticated_user_id="U1",
        auth_method="email",
        active_user_identity={
            "user_id": "U1",
            "name": "Alice Smith",
            "email": "alice@example.com",
        },
    )
    session.messages = [
        Message(role="user", content="I need help with my order"),
        Message(role="assistant", content="Let me look up your order."),
    ]
    session.loaded_context.orders["O1"] = {
        "order_id": "O1", "user_id": "U1", "status": "pending",
        "items": [{"item_id": "I1", "name": "Widget"}, {"item_id": "I2", "name": "Gadget"}],
    }
    session.loaded_context.orders["O2"] = {
        "order_id": "O2", "user_id": "U1", "status": "delivered",
        "items": [{"item_id": "I3", "name": "Thing"}],
    }
    session.tool_results = [
        ToolCallRecord(
            tool_name="get_order_details", arguments={"order_id": "O1"},
            tool_kind="read", status="success",
            observation={"order_id": "O1", "status": "pending", "item_count": 2},
        ),
    ]
    return session


def test_build_includes_auth_summary() -> None:
    summary = ContextBuilder(policy_text="dummy").build(_session())
    assert "Alice Smith" in summary
    assert "U1" in summary
    assert "example.com" in summary


def test_build_includes_order_summaries() -> None:
    summary = ContextBuilder(policy_text="dummy").build(_session())
    assert "O1" in summary
    assert "pending" in summary
    assert "O2" in summary
    assert "delivered" in summary


def test_build_marks_writable_orders() -> None:
    summary = ContextBuilder(policy_text="dummy").build(_session())
    assert "[writable]" in summary


def test_build_includes_pending_action() -> None:
    session = _session()
    session.pending_action = PendingAction(
        action_name="cancel_pending_order",
        arguments={"order_id": "O1", "reason": "no longer needed"},
        user_facing_summary="Cancel order O1",
    )
    summary = ContextBuilder(policy_text="dummy").build(session)
    assert "cancel_pending_order" in summary


def test_build_includes_write_locks() -> None:
    session = _session()
    session.write_locks = ["order_O1_write_lock"]
    summary = ContextBuilder(policy_text="dummy").build(session)
    assert "order_O1_write_lock" in summary


def test_build_handles_unauthenticated_user() -> None:
    session = SessionState(session_id="ctx-2")
    summary = ContextBuilder(policy_text="dummy").build(session)
    assert "not authenticated" in summary.lower()


def test_build_handles_empty_state() -> None:
    session = SessionState(session_id="ctx-3")
    summary = ContextBuilder(policy_text="dummy").build(session)
    assert len(summary) > 0


def test_estimate_tokens_is_reasonable() -> None:
    builder = ContextBuilder(policy_text="dummy")
    summary = builder.build(_session())
    tokens = builder.estimate_tokens(summary)
    assert isinstance(tokens, int)
    assert 0 < tokens < 2000


def test_recent_messages_limited_to_last_six() -> None:
    session = _session()
    for i in range(10):
        session.messages.append(Message(role="user", content=f"msg {i}"))
    summary = ContextBuilder(policy_text="dummy").build(session)
    assert "msg 0" not in summary
    assert "msg 3" not in summary
    assert "msg 8" in summary
