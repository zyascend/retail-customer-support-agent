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
    assert "user_id=U1" in summary
    assert "(email)" in summary


def test_build_includes_order_summaries() -> None:
    summary = ContextBuilder(policy_text="dummy").build(_session())
    assert "O1" in summary
    assert "pending" in summary
    assert "O2" in summary
    assert "delivered" in summary


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
    assert "User:" not in summary


def test_build_handles_empty_state() -> None:
    session = SessionState(session_id="ctx-3")
    summary = ContextBuilder(policy_text="dummy").build(session)
    assert summary == ""


def test_estimate_tokens_is_reasonable() -> None:
    builder = ContextBuilder(policy_text="dummy")
    summary = builder.build(_session())
    tokens = builder.estimate_tokens(summary)
    assert isinstance(tokens, int)
    assert 0 < tokens < 2000


def test_recent_messages_not_included() -> None:
    session = _session()
    for i in range(10):
        session.messages.append(Message(role="user", content=f"msg {i}"))
    summary = ContextBuilder(policy_text="dummy").build(session)
    assert "msg" not in summary


def test_build_includes_recent_tool_error_and_guard_block() -> None:
    session = SessionState(session_id="ctx-4", authenticated_user_id="U1")
    session.tool_results.append(
        ToolCallRecord(
            tool_name="cancel_pending_order",
            arguments={"order_id": "#W1", "reason": "no longer needed"},
            tool_kind="write",
            status="blocked",
            error="ownership_violation",
            block_context={"order_id": "#W1"},
        )
    )
    session.tool_results.append(
        ToolCallRecord(
            tool_name="get_order_details",
            arguments={"order_id": "#W404"},
            tool_kind="read",
            status="error",
            error="order_not_found",
        )
    )

    summary = ContextBuilder(policy_text="dummy").build(session)

    assert "Recent guard block: cancel_pending_order ownership_violation" in summary
    assert "Recent tool error: get_order_details order_not_found" in summary


def test_build_includes_recent_successful_write_amount_context() -> None:
    session = SessionState(session_id="ctx-5", authenticated_user_id="U1")
    session.tool_results.append(
        ToolCallRecord(
            tool_name="return_delivered_order_items",
            arguments={
                "order_id": "#W1",
                "item_ids": ["I1"],
                "payment_method_id": "paypal_1",
            },
            tool_kind="write",
            status="success",
            resource_lock="item:I1:return",
            observation={
                "order_id": "#W1",
                "status": "return requested",
                "payment_history": [
                    {
                        "amount": 25.5,
                        "payment_method_id": "paypal_1",
                        "transaction_type": "refund",
                    }
                ],
                "items": [
                    {"item_id": "I1", "name": "Widget", "price": 25.5},
                ],
            },
        )
    )

    summary = ContextBuilder(policy_text="dummy").build(session)

    assert "Recent successful writes:" in summary
    assert "return_delivered_order_items" in summary
    assert "item:I1:return" in summary
    assert "refund 25.5 via paypal_1" in summary
    assert "I1 Widget 25.5" in summary


def test_successful_return_write_includes_target_item_total() -> None:
    session = SessionState(session_id="ctx-6", authenticated_user_id="U1")
    session.tool_results.append(
        ToolCallRecord(
            tool_name="return_delivered_order_items",
            arguments={
                "order_id": "#W2",
                "item_ids": ["I1", "I3"],
                "payment_method_id": "paypal_1",
            },
            tool_kind="write",
            status="success",
            resource_lock="item:I1,I3:return",
            observation={
                "order_id": "#W2",
                "status": "return requested",
                "payment_history": [
                    {
                        "amount": 999.0,
                        "payment_method_id": "paypal_1",
                        "transaction_type": "payment",
                    }
                ],
                "items": [
                    {"item_id": "I1", "name": "Skateboard", "price": 200.8},
                    {"item_id": "I2", "name": "Tent", "price": 500.0},
                    {"item_id": "I3", "name": "Backpack", "price": 193.38},
                ],
            },
        )
    )

    summary = ContextBuilder(policy_text="dummy").build(session)

    assert "target_items=[I1, I3]" in summary
    assert "target_item_total=394.18" in summary


def test_successful_modify_write_includes_replacement_ids() -> None:
    session = SessionState(session_id="ctx-7", authenticated_user_id="U1")
    session.tool_results.append(
        ToolCallRecord(
            tool_name="modify_pending_order_items",
            arguments={
                "order_id": "#W3",
                "item_ids": ["old1"],
                "new_item_ids": ["new1"],
                "payment_method_id": "gift_card_1",
            },
            tool_kind="write",
            status="success",
            resource_lock="order:#W3:modify_items",
            observation={
                "order_id": "#W3",
                "status": "pending (item modified)",
                "items": [
                    {"item_id": "new1", "name": "Desk Lamp", "price": 135.24},
                ],
            },
        )
    )

    summary = ContextBuilder(policy_text="dummy").build(session)

    assert "replacements=[old1->new1]" in summary
