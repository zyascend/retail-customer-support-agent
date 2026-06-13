# app/synthetic/adapter.py
from __future__ import annotations

import copy
import json
from typing import Any, Callable, Dict

from app.synthetic.generator import SyntheticDBGenerator
from app.tools.retail_adapter import RetailRuntime

READ_TOOLS = {
    "find_user_id_by_email",
    "find_user_id_by_name_zip",
    "get_user_details",
    "get_order_details",
    "get_product_details",
    "get_item_details",
    "list_all_product_types",
}
WRITE_TOOLS = {
    "cancel_pending_order",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
    "exchange_delivered_order_items",
    "modify_pending_order_shipping_method",
}
GENERIC_TOOLS = {"calculate", "transfer_to_human_agents"}


class SyntheticRetailTools:
    def __init__(self, db: Dict[str, Any]) -> None:
        self.db = db
        self.tools: Dict[str, Callable[..., Any]] = {
            name: getattr(self, name)
            for name in sorted(READ_TOOLS | WRITE_TOOLS | GENERIC_TOOLS)
            if hasattr(self, name)
        }

    def tool_type(self, tool_name: str) -> str:
        if tool_name in READ_TOOLS:
            return "read"
        if tool_name in WRITE_TOOLS:
            return "write"
        return "generic"

    def get_hash(self) -> str:
        from app.ops.serialization import stable_hash
        return stable_hash(self.db)

    # ── Private helpers ──

    def _get_order(self, order_id: str) -> Dict[str, Any]:
        try:
            return self.db["orders"][order_id]
        except KeyError as exc:
            raise ValueError("Order not found") from exc

    def _get_user(self, user_id: str) -> Dict[str, Any]:
        try:
            return self.db["users"][user_id]
        except KeyError as exc:
            raise ValueError("User not found") from exc

    def _get_product(self, product_id: str) -> Dict[str, Any]:
        try:
            return self.db["products"][product_id]
        except KeyError as exc:
            raise ValueError("Product not found") from exc

    def _get_variant(self, product_id: str, item_id: str) -> Dict[str, Any]:
        product = self._get_product(product_id)
        try:
            return product["variants"][item_id]
        except KeyError as exc:
            raise ValueError("Variant not found") from exc

    def _get_payment_method(
        self, user_id: str, payment_method_id: str
    ) -> Dict[str, Any]:
        user = self._get_user(user_id)
        try:
            return user["payment_methods"][payment_method_id]
        except KeyError as exc:
            raise ValueError("Payment method not found") from exc

    def _get_current_payment_method_id(self, order: Dict[str, Any]) -> str | None:
        for entry in reversed(order.get("payment_history", [])):
            if entry.get("transaction_type") == "payment":
                return entry.get("payment_method_id")
        return None

    # ── Read tools ──

    def calculate(self, expression: str) -> str:
        if not all(char in "0123456789+-*/(). " for char in expression):
            raise ValueError("Invalid characters in expression")
        return str(round(float(eval(expression, {"__builtins__": None}, {})), 2))

    def find_user_id_by_email(self, email: str) -> str:
        for user_id, user in self.db["users"].items():
            if user["email"].lower() == email.lower():
                return user_id
        raise ValueError("User not found")

    def find_user_id_by_name_zip(
        self, first_name: str, last_name: str, zip: str
    ) -> str:
        for user_id, user in self.db["users"].items():
            name = user["name"]
            if (
                name["first_name"].lower() == first_name.lower()
                and name["last_name"].lower() == last_name.lower()
                and user["address"]["zip"] == zip
            ):
                return user_id
        raise ValueError("User not found")

    def get_user_details(self, user_id: str) -> Dict[str, Any]:
        return copy.deepcopy(self._get_user(user_id))

    def get_order_details(self, order_id: str) -> Dict[str, Any]:
        return copy.deepcopy(self._get_order(order_id))

    def get_product_details(self, product_id: str) -> Dict[str, Any]:
        return copy.deepcopy(self._get_product(product_id))

    def get_item_details(self, item_id: str) -> Dict[str, Any]:
        for product in self.db["products"].values():
            if item_id in product["variants"]:
                return copy.deepcopy(product["variants"][item_id])
        raise ValueError("Item not found")

    def list_all_product_types(self) -> str:
        product_dict = {
            product["name"]: product_id
            for product_id, product in self.db["products"].items()
        }
        return json.dumps(product_dict, sort_keys=True)

    # ── Write tools (existing) ──

    def cancel_pending_order(self, order_id: str, reason: str) -> Dict[str, Any]:
        order = self._get_order(order_id)
        assert order["status"] == "pending"
        assert reason in {"no longer needed", "ordered by mistake"}
        order["status"] = "cancelled"
        order["cancel_reason"] = reason
        return copy.deepcopy(order)

    def modify_pending_order_address(
        self, order_id: str, address1: str, address2: str,
        city: str, state: str, country: str, zip: str,
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        assert "pending" in order["status"]
        order["address"] = {
            "address1": address1, "address2": address2,
            "city": city, "state": state, "country": country, "zip": zip,
        }
        return copy.deepcopy(order)

    def modify_pending_order_items(
        self, order_id: str, item_ids: list[str], new_item_ids: list[str],
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        assert order["status"] == "pending"
        assert len(item_ids) == len(new_item_ids)
        for old_item_id, new_item_id in zip(item_ids, new_item_ids):
            matching_index = next(
                (idx for idx, item in enumerate(order["items"])
                 if item["item_id"] == old_item_id),
                None,
            )
            assert matching_index is not None
            old_item = order["items"][matching_index]
            new_variant = self._get_variant(old_item["product_id"], new_item_id)
            assert new_variant["available"]
            replacement = copy.deepcopy(old_item)
            replacement["item_id"] = new_item_id
            replacement["price"] = new_variant["price"]
            replacement["options"] = copy.deepcopy(new_variant["options"])
            order["items"][matching_index] = replacement
        order["status"] = "pending (item modified)"
        return copy.deepcopy(order)

    def modify_pending_order_payment(
        self, order_id: str, payment_method_id: str,
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        assert "pending" in order["status"]
        payment_method = self._get_payment_method(order["user_id"], payment_method_id)
        current_id = self._get_current_payment_method_id(order)
        assert payment_method_id != current_id
        amount = sum(float(item.get("price", 0.0)) for item in order["items"])
        if payment_method.get("source") == "gift_card":
            assert float(payment_method.get("balance", 0.0)) >= amount
        order["payment_history"].append({
            "transaction_type": "payment",
            "amount": round(amount, 2),
            "payment_method_id": payment_method_id,
        })
        return copy.deepcopy(order)

    def return_delivered_order_items(
        self, order_id: str, item_ids: list[str], payment_method_id: str,
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        assert order["status"] == "delivered"
        self._get_payment_method(order["user_id"], payment_method_id)
        all_item_ids = [item["item_id"] for item in order["items"]]
        for item_id in item_ids:
            assert item_ids.count(item_id) <= all_item_ids.count(item_id)
        order["status"] = "return requested"
        order["return_items"] = sorted(item_ids)
        order["return_payment_method_id"] = payment_method_id
        return copy.deepcopy(order)

    def exchange_delivered_order_items(
        self, order_id: str, item_ids: list[str],
        new_item_ids: list[str], payment_method_id: str,
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        assert order["status"] == "delivered"
        assert len(item_ids) == len(new_item_ids)
        self._get_payment_method(order["user_id"], payment_method_id)
        all_item_ids = [item["item_id"] for item in order["items"]]
        for item_id in item_ids:
            assert item_ids.count(item_id) <= all_item_ids.count(item_id)
        for item_id, new_item_id in zip(item_ids, new_item_ids):
            item = next(i for i in order["items"] if i["item_id"] == item_id)
            variant = self._get_variant(item["product_id"], new_item_id)
            assert variant["available"]
        order["status"] = "exchange requested"
        order["exchange_items"] = sorted(item_ids)
        order["exchange_new_items"] = sorted(new_item_ids)
        order["exchange_payment_method_id"] = payment_method_id
        return copy.deepcopy(order)

    def modify_user_address(
        self, user_id: str, address1: str, address2: str,
        city: str, state: str, country: str, zip: str,
    ) -> Dict[str, Any]:
        user = self._get_user(user_id)
        user["address"] = {
            "address1": address1, "address2": address2,
            "city": city, "state": state, "country": country, "zip": zip,
        }
        return copy.deepcopy(user)

    # ── New write tool: modify shipping method ──

    def modify_pending_order_shipping_method(
        self, order_id: str, shipping_method: str,
        payment_method_id: str | None = None,
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        assert order["status"] == "pending"
        old_method = order["shipping_method"]
        shipping_methods = self.db["shipping_methods"]
        old_fee = shipping_methods[old_method]["fee"]
        new_fee = shipping_methods[shipping_method]["fee"]
        fee_delta = new_fee - old_fee
        order["shipping_method"] = shipping_method
        order["shipping_fee"] = new_fee
        if fee_delta > 0 and payment_method_id:
            order["payment_history"].append({
                "transaction_type": "shipping_upgrade",
                "amount": round(fee_delta, 2),
                "payment_method_id": payment_method_id,
            })
        return copy.deepcopy(order)

    # ── Generic ──

    def transfer_to_human_agents(self, summary: str) -> str:
        return "Transfer successful"


class SyntheticRetailAdapter:
    def __init__(self, seed: int = 42) -> None:
        self.seed = seed

    def create_runtime(self) -> RetailRuntime:
        db = SyntheticDBGenerator.from_seed(self.seed)
        tools = SyntheticRetailTools(db)
        return RetailRuntime(
            db=tools.db,
            tools=tools,
            policy="synthetic-policy",
            source="synthetic",
        )
