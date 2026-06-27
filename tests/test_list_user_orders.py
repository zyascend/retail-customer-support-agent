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
