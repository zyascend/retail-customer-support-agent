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
