# app/synthetic/oracle.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class DeterministicOracle:
    """从 variant 类型自动派生的标准答案（用于 eval 断言）"""
    expected_user_id: str
    expected_intent: str
    order_id: str | None = None
    expected_write_lock: str | None = None
    expected_order_status: str | None = None
    expected_confirmation_status: str = "confirmed"
    expected_guard_block_reason: str | None = None
    expected_no_write: bool = False
    expected_tool_names: List[str] = field(default_factory=list)
    expected_db_assertions: Dict[str, Any] = field(default_factory=dict)
    expected_tool_sequence: List[str] = field(default_factory=list)


# ── Oracle derivation functions ──


def _derive_cancel_success(world: dict, entities: dict) -> DeterministicOracle:
    order = entities["order"]
    user = entities["user"]
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="cancel_order",
        order_id=order["order_id"],
        expected_write_lock=f"order:{order['order_id']}:cancel",
        expected_order_status="cancelled",
        expected_confirmation_status="confirmed",
        expected_no_write=False,
        expected_tool_names=["cancel_pending_order"],
    )


def _derive_cancel_block_nonpending(world: dict, entities: dict) -> DeterministicOracle:
    order = entities["order"]
    user = entities["user"]
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="cancel_order",
        order_id=order["order_id"],
        expected_guard_block_reason="non_pending_order_cannot_be_cancelled",
        expected_no_write=True,
        expected_confirmation_status="confirmed",
        expected_tool_names=["cancel_pending_order"],
    )


def _derive_cancel_block_wrong_user(world: dict, entities: dict) -> DeterministicOracle:
    order = entities["order"]
    user = entities["user"]
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="cancel_order",
        order_id=order["order_id"],
        expected_confirmation_status="",
        expected_no_write=True,
        expected_tool_names=[],
    )


def _derive_shipping_success(world: dict, entities: dict) -> DeterministicOracle:
    order = entities["order"]
    user = entities["user"]
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="modify_shipping_method",
        order_id=order["order_id"],
        expected_write_lock=f"order:{order['order_id']}:modify_shipping_method",
        expected_confirmation_status="confirmed",
        expected_no_write=False,
        expected_tool_names=["modify_pending_order_shipping_method"],
    )


def _derive_shipping_block_same(world: dict, entities: dict) -> DeterministicOracle:
    order = entities["order"]
    user = entities["user"]
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="modify_shipping_method",
        order_id=order["order_id"],
        expected_guard_block_reason="same_shipping_method",
        expected_no_write=True,
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_pending_order_shipping_method"],
    )


def _derive_shipping_block_nonpending(world: dict, entities: dict) -> DeterministicOracle:
    order = entities["order"]
    user = entities["user"]
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="modify_shipping_method",
        order_id=order["order_id"],
        expected_guard_block_reason="non_pending_order_cannot_be_modified",
        expected_no_write=True,
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_pending_order_shipping_method"],
    )


def _derive_shipping_block_unknown(world: dict, entities: dict) -> DeterministicOracle:
    order = entities["order"]
    user = entities["user"]
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="modify_shipping_method",
        order_id=order["order_id"],
        expected_guard_block_reason="unknown_shipping_method",
        expected_no_write=True,
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_pending_order_shipping_method"],
    )


def _derive_coupon_transfer(world: dict, entities: dict) -> DeterministicOracle:
    user = entities["user"]
    order = entities.get("order")
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="transfer",
        order_id=order["order_id"] if order else None,
        expected_confirmation_status="",
        expected_no_write=True,
        expected_tool_names=["transfer_to_human_agents"],
    )


VARIANT_ORACLE_DERIVERS = {
    "cancel_success": _derive_cancel_success,
    "cancel_block_nonpending": _derive_cancel_block_nonpending,
    "cancel_block_wrong_user": _derive_cancel_block_wrong_user,
    "shipping_success_express": _derive_shipping_success,
    "shipping_success_overnight": _derive_shipping_success,
    "shipping_block_same_method": _derive_shipping_block_same,
    "shipping_block_nonpending": _derive_shipping_block_nonpending,
    "shipping_block_unknown_method": _derive_shipping_block_unknown,
    "coupon_transfer_no_write": _derive_coupon_transfer,
}


def derive_oracle(world: dict, entities: dict, variant_type: str) -> DeterministicOracle:
    """根据 variant_type 自动派生标准答案 oracle。"""
    deriver = VARIANT_ORACLE_DERIVERS.get(variant_type)
    if deriver is None:
        raise ValueError(f"Unknown variant_type: {variant_type}")
    return deriver(world, entities)


def select_entity_for_variant(world: dict, variant_type: str) -> dict:
    """从合成世界中选取适配 variant_type 的实体 (user + order)。"""
    users = list(world["users"].values())
    orders = list(world["orders"].values())

    if variant_type == "cancel_success":
        for order in orders:
            if order["status"] == "pending":
                user = world["users"][order["user_id"]]
                return {"user": user, "order": order}
        raise ValueError("No pending order found for cancel_success")

    if variant_type == "cancel_block_nonpending":
        for order in orders:
            if order["status"] != "pending":
                user = world["users"][order["user_id"]]
                return {"user": user, "order": order}
        raise ValueError("No non-pending order found for cancel_block_nonpending")

    if variant_type == "cancel_block_wrong_user":
        if len(users) < 2 or len(orders) < 2:
            raise ValueError("Need at least 2 users and 2 orders for wrong_user variant")
        user = users[0]
        for order in orders:
            if order["user_id"] != user["user_id"]:
                return {"user": user, "order": order}
        raise ValueError("No order from different user found for cancel_block_wrong_user")

    if variant_type.startswith("shipping_success_"):
        target_method = variant_type.replace("shipping_success_", "")
        for order in orders:
            if order["status"] == "pending" and order.get("shipping_method") != target_method:
                user = world["users"][order["user_id"]]
                return {"user": user, "order": order, "target_method": target_method}
        raise ValueError(f"No pending order found for shipping_success {target_method}")

    if variant_type == "shipping_block_same_method":
        for order in orders:
            if order["status"] == "pending":
                user = world["users"][order["user_id"]]
                return {"user": user, "order": order}
        raise ValueError("No pending order for shipping_block_same_method")

    if variant_type == "shipping_block_nonpending":
        for order in orders:
            if order["status"] != "pending":
                user = world["users"][order["user_id"]]
                return {"user": user, "order": order}
        raise ValueError("No non-pending order for shipping_block_nonpending")

    if variant_type == "shipping_block_unknown_method":
        for order in orders:
            if order["status"] == "pending":
                user = world["users"][order["user_id"]]
                return {"user": user, "order": order}
        raise ValueError("No pending order for shipping_block_unknown_method")

    if variant_type == "coupon_transfer_no_write":
        if not users:
            raise ValueError("No users found for coupon_transfer_no_write")
        user = users[0]
        user_orders = [o for o in orders if o["user_id"] == user["user_id"]]
        order = user_orders[0] if user_orders else None
        return {"user": user, "order": order}

    raise ValueError(f"Unknown variant_type: {variant_type}")
