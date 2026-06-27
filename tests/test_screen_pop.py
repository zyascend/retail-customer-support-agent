from __future__ import annotations

from unittest.mock import MagicMock

from app.agent.models import SessionState, ToolCallRecord
from app.agent.screen_pop import ScreenPop


def _mock_gateway(user_obs: dict, orders_obs: list) -> MagicMock:
    gw = MagicMock()

    def execute(*, state, tool_name, arguments, confirmed=False):
        if tool_name == "get_user_details":
            return ToolCallRecord(
                tool_name=tool_name,
                arguments=arguments,
                tool_kind="read",
                status="success",
                observation=user_obs,
            )
        if tool_name == "list_user_orders":
            return ToolCallRecord(
                tool_name=tool_name,
                arguments=arguments,
                tool_kind="read",
                status="success",
                observation=orders_obs,
            )
        return ToolCallRecord(
            tool_name=tool_name,
            arguments=arguments,
            tool_kind="read",
            status="error",
            error="x",
        )

    gw.execute.side_effect = execute
    return gw


def test_screen_pop_sets_identity_and_loads_orders() -> None:
    user_obs = {"name": {"first_name": "Sofia"}, "email": "s@example.com"}
    orders_obs = [{"order_id": "#W1", "status": "pending", "items": []}]
    gw = _mock_gateway(user_obs, orders_obs)
    state = SessionState(session_id="t")
    ScreenPop(gw).apply(state, "sofia_rossi_8776")
    assert state.authenticated_user_id == "sofia_rossi_8776"
    assert state.auth_method == "screen_pop"
    assert "sofia_rossi_8776" in state.loaded_context.users
    assert "#W1" in state.loaded_context.orders
    assert any(s.node == "screen_pop" for s in state.steps)


def test_screen_pop_orders_loaded_into_context() -> None:
    user_obs = {"name": {}}
    orders_obs = [
        {
            "order_id": "#W1",
            "status": "pending",
            "items": [{"item_id": "1", "name": "Bottle", "price": 10}],
        },
    ]
    gw = _mock_gateway(user_obs, orders_obs)
    state = SessionState(session_id="t")
    ScreenPop(gw).apply(state, "u1")
    assert state.loaded_context.orders["#W1"]["status"] == "pending"


def test_screen_pop_records_order_count() -> None:
    user_obs = {"name": {}}
    orders_obs = [
        {"order_id": "#W1", "status": "pending", "items": []},
        {"order_id": "#W2", "status": "delivered", "items": []},
    ]
    gw = _mock_gateway(user_obs, orders_obs)
    state = SessionState(session_id="t")
    ScreenPop(gw).apply(state, "u1")
    step = next(s for s in state.steps if s.node == "screen_pop")
    assert step.detail.get("order_count") == 2


def test_run_script_accepts_screen_pop_user_id() -> None:
    """run_script 签名接受 screen_pop_user_id 参数。"""
    import inspect
    from app.agent.runtime import AgentRuntime

    sig = inspect.signature(AgentRuntime.run_script)
    assert "screen_pop_user_id" in sig.parameters
