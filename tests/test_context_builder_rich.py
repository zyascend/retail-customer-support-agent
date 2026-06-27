from __future__ import annotations

from app.agent.context_builder import ContextBuilder
from app.agent.models import PendingAction, SessionState


def test_orders_show_item_names() -> None:
    cb = ContextBuilder(policy_text="")
    state = SessionState(session_id="t")
    state.authenticated_user_id = "u1"
    state.loaded_context.orders["#W1"] = {
        "status": "pending",
        "items": [
            {"item_id": "1", "name": "Water Bottle", "price": 10},
            {"item_id": "2", "name": "T-Shirt", "price": 20},
            {"item_id": "3", "name": "Mug", "price": 5},
        ],
    }
    out = cb.build(state)
    assert "[Water Bottle, T-Shirt, Mug]" in out


def test_orders_truncate_to_three_names() -> None:
    cb = ContextBuilder(policy_text="")
    state = SessionState(session_id="t")
    state.authenticated_user_id = "u1"
    state.loaded_context.orders["#W1"] = {
        "status": "pending",
        "items": [
            {"item_id": str(i), "name": f"Item{i}", "price": 1} for i in range(5)
        ],
    }
    out = cb.build(state)
    assert "..." in out  # 超过 3 个截断


def test_orders_no_names_falls_back_to_count() -> None:
    cb = ContextBuilder(policy_text="")
    state = SessionState(session_id="t")
    state.authenticated_user_id = "u1"
    state.loaded_context.orders["#W1"] = {
        "status": "pending",
        "items": [{"item_id": "1", "price": 10}],  # 无 name
    }
    out = cb.build(state)
    assert "(1 items)" in out


def test_pending_shows_arguments() -> None:
    cb = ContextBuilder(policy_text="")
    state = SessionState(session_id="t")
    state.authenticated_user_id = "u1"
    state.pending_action = PendingAction(
        action_name="cancel_pending_order",
        arguments={"order_id": "#W5918442", "reason": "no longer needed"},
        user_facing_summary="cancel",
    )
    out = cb.build(state)
    assert "order_id=#W5918442" in out
    assert "reason=no longer needed" in out
