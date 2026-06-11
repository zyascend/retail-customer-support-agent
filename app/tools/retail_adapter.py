from __future__ import annotations

import copy
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict

from app.config import AppConfig
from app.ops.serialization import stable_hash, to_plain_data


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
}
GENERIC_TOOLS = {"calculate", "transfer_to_human_agents"}


@dataclass
class RetailRuntime:
    db: Any
    tools: Any
    policy: str
    source: str

    def db_hash(self) -> str:
        if hasattr(self.db, "get_hash"):
            return str(self.db.get_hash())
        return stable_hash(self.db)

    def db_snapshot(self) -> Any:
        return copy.deepcopy(to_plain_data(self.db))


class RetailAdapterError(RuntimeError):
    pass


class RetailAdapter:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def create_runtime(self) -> RetailRuntime:
        self._validate_paths()
        policy = self.config.retail_policy_path.read_text(encoding="utf-8")
        try:
            return self._create_tau2_runtime(policy)
        except Exception:
            return self._create_local_runtime(policy)

    def _validate_paths(self) -> None:
        required = (
            self.config.retail_db_path,
            self.config.retail_policy_path,
            self.config.retail_tasks_path,
        )
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise RetailAdapterError(
                "missing retail source files: " + ", ".join(missing)
            )

    def _create_tau2_runtime(self, policy: str) -> RetailRuntime:
        if not self.config.tau2_src_dir.exists():
            raise RetailAdapterError(
                f"tau2 source not found: {self.config.tau2_src_dir}"
            )
        src = str(self.config.tau2_src_dir)
        if src not in sys.path:
            sys.path.insert(0, src)
        os.environ.setdefault(
            "TAU2_DATA_DIR", str(self.config.tau2_bench_root / "data")
        )

        from tau2.domains.retail.data_model import RetailDB
        from tau2.domains.retail.tools import RetailTools

        db = RetailDB.load(str(self.config.retail_db_path))
        return RetailRuntime(
            db=db,
            tools=RetailTools(db),
            policy=policy,
            source="tau2-runtime",
        )

    def _create_local_runtime(self, policy: str) -> RetailRuntime:
        with self.config.retail_db_path.open("r", encoding="utf-8") as file:
            db = json.load(file)
        tools = LocalRetailTools(copy.deepcopy(db))
        return RetailRuntime(
            db=tools.db,
            tools=tools,
            policy=policy,
            source="local-fallback",
        )


class LocalRetailTools:
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
        return stable_hash(self.db)

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

    def _get_payment_method(
        self, user_id: str, payment_method_id: str
    ) -> Dict[str, Any]:
        user = self._get_user(user_id)
        try:
            return user["payment_methods"][payment_method_id]
        except KeyError as exc:
            raise ValueError("Payment method not found") from exc

    def _get_variant(self, product_id: str, item_id: str) -> Dict[str, Any]:
        product = self._get_product(product_id)
        try:
            return product["variants"][item_id]
        except KeyError as exc:
            raise ValueError("Variant not found") from exc

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

    def cancel_pending_order(self, order_id: str, reason: str) -> Dict[str, Any]:
        order = self._get_order(order_id)
        if order["status"] != "pending":
            raise ValueError("Non-pending order cannot be cancelled")
        if reason not in {"no longer needed", "ordered by mistake"}:
            raise ValueError("Invalid reason")
        order["status"] = "cancelled"
        order["cancel_reason"] = reason
        return copy.deepcopy(order)

    def modify_pending_order_address(
        self,
        order_id: str,
        address1: str,
        address2: str,
        city: str,
        state: str,
        country: str,
        zip: str,
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        if "pending" not in order["status"]:
            raise ValueError("Non-pending order cannot be modified")
        order["address"] = {
            "address1": address1,
            "address2": address2,
            "city": city,
            "state": state,
            "country": country,
            "zip": zip,
        }
        return copy.deepcopy(order)

    def return_delivered_order_items(
        self, order_id: str, item_ids: list[str], payment_method_id: str
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        if order["status"] != "delivered":
            raise ValueError("Non-delivered order cannot be returned")
        self._get_payment_method(order["user_id"], payment_method_id)
        all_item_ids = [item["item_id"] for item in order["items"]]
        for item_id in item_ids:
            if item_ids.count(item_id) > all_item_ids.count(item_id):
                raise ValueError("Some item not found")
        order["status"] = "return requested"
        order["return_items"] = sorted(item_ids)
        order["return_payment_method_id"] = payment_method_id
        return copy.deepcopy(order)

    def exchange_delivered_order_items(
        self,
        order_id: str,
        item_ids: list[str],
        new_item_ids: list[str],
        payment_method_id: str,
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        if order["status"] != "delivered":
            raise ValueError("Non-delivered order cannot be exchanged")
        if len(item_ids) != len(new_item_ids):
            raise ValueError("The number of items to be exchanged should match.")
        self._get_payment_method(order["user_id"], payment_method_id)
        all_item_ids = [item["item_id"] for item in order["items"]]
        for item_id in item_ids:
            if item_ids.count(item_id) > all_item_ids.count(item_id):
                raise ValueError(f"Number of {item_id} not found.")
        for item_id, new_item_id in zip(item_ids, new_item_ids):
            item = next(item for item in order["items"] if item["item_id"] == item_id)
            variant = self._get_variant(item["product_id"], new_item_id)
            if not variant["available"]:
                raise ValueError(f"New item {new_item_id} not found or available")
        order["status"] = "exchange requested"
        order["exchange_items"] = sorted(item_ids)
        order["exchange_new_items"] = sorted(new_item_ids)
        order["exchange_payment_method_id"] = payment_method_id
        return copy.deepcopy(order)

    def modify_user_address(
        self,
        user_id: str,
        address1: str,
        address2: str,
        city: str,
        state: str,
        country: str,
        zip: str,
    ) -> Dict[str, Any]:
        user = self._get_user(user_id)
        user["address"] = {
            "address1": address1,
            "address2": address2,
            "city": city,
            "state": state,
            "country": country,
            "zip": zip,
        }
        return copy.deepcopy(user)

    def transfer_to_human_agents(self, summary: str) -> str:
        return "Transfer successful"


def get_order_from_db(db: Any, order_id: str) -> Optional[Dict[str, Any]]:
    data = to_plain_data(db)
    return copy.deepcopy(data.get("orders", {}).get(order_id))


def get_user_from_db(db: Any, user_id: str) -> Optional[Dict[str, Any]]:
    data = to_plain_data(db)
    return copy.deepcopy(data.get("users", {}).get(user_id))


def get_product_from_db(db: Any, product_id: str) -> Optional[Dict[str, Any]]:
    data = to_plain_data(db)
    return copy.deepcopy(data.get("products", {}).get(product_id))


def find_product_for_item(db: Any, item_id: str) -> Optional[Dict[str, Any]]:
    data = to_plain_data(db)
    for product in data.get("products", {}).values():
        if item_id in product.get("variants", {}):
            return copy.deepcopy(product)
    return None
