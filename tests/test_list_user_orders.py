from __future__ import annotations

from app.agent.models import SessionState
from app.tools.gateway import ToolGateway
from app.tools.retail_adapter import LocalRetailTools
from app.tools.registry import ToolRegistry


def _tools_with_one_order() -> LocalRetailTools:
    db = {
        "users": {
            "sofia_rossi_8776": {
                "name": {},
                "email": "s@example.com",
                "address": {},
                "payment_methods": {},
            }
        },
        "orders": {
            "#W5918442": {
                "user_id": "sofia_rossi_8776",
                "status": "pending",
                "items": [{"item_id": "111", "name": "Water Bottle", "price": 10.0}],
            },
            "#W4817420": {
                "user_id": "sofia_rossi_8776",
                "status": "delivered",
                "items": [{"item_id": "222", "name": "Mug", "price": 5.0}],
            },
            "#W0000001": {"user_id": "other_user", "status": "pending", "items": []},
        },
        "products": {},
    }
    return LocalRetailTools(db)


def test_list_user_orders_filters_by_user() -> None:
    tools = _tools_with_one_order()
    result = tools.list_user_orders("sofia_rossi_8776")
    order_ids = [o["order_id"] for o in result]
    assert order_ids == ["#W5918442", "#W4817420"]


def test_list_user_orders_summary_shape() -> None:
    tools = _tools_with_one_order()
    result = tools.list_user_orders("sofia_rossi_8776")
    first = result[0]
    assert first["order_id"] == "#W5918442"
    assert first["status"] == "pending"
    assert first["items"] == [
        {"item_id": "111", "name": "Water Bottle", "price": 10.0}
    ]


def test_list_user_orders_empty() -> None:
    tools = _tools_with_one_order()
    assert tools.list_user_orders("nobody") == []


def _gateway_and_state():
    from app.tools.retail_adapter import RetailRuntime

    tools = _tools_with_one_order()
    runtime = RetailRuntime(db=tools.db, tools=tools, policy="", source="test")
    registry = ToolRegistry(tools)
    gateway = ToolGateway(registry=registry, runtime=runtime)
    state = SessionState(session_id="t")
    state.authenticated_user_id = "sofia_rossi_8776"
    return gateway, state


def test_list_user_orders_blocked_for_other_user() -> None:
    gateway, state = _gateway_and_state()
    record = gateway.execute(
        state=state,
        tool_name="list_user_orders",
        arguments={"user_id": "other_user"},
    )
    assert record.status == "blocked"
    assert record.error == "ownership_violation"


def test_list_user_orders_allowed_for_authenticated_user() -> None:
    gateway, state = _gateway_and_state()
    record = gateway.execute(
        state=state,
        tool_name="list_user_orders",
        arguments={"user_id": "sofia_rossi_8776"},
    )
    assert record.status == "success"
    assert isinstance(record.observation, list)
    assert len(record.observation) == 2

