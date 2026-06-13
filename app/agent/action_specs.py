from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class WriteActionSpec:
    """Single source of truth for a write operation.

    Every other location that needs write action metadata derives from the
    WRITE_ACTION_REGISTRY below — no more hardcoded lists in guard, runtime,
    registry, or prompt files.
    """
    name: str
    display: str
    tool_name: str
    intent: str
    required_args: tuple[str, ...]
    required_slots: tuple[str, ...]
    order_status_check: Optional[str]
    resource_type: str  # "order" | "user"
    risk: str  # "high" | "medium" | "low"


WRITE_ACTION_REGISTRY: tuple[WriteActionSpec, ...] = (
    WriteActionSpec(
        name="cancel_pending_order",
        display="Cancel Order",
        tool_name="cancel_pending_order",
        intent="cancel_order",
        required_args=("order_id", "reason"),
        required_slots=("order_id", "reason"),
        order_status_check="pending",
        resource_type="order",
        risk="high",
    ),
    WriteActionSpec(
        name="modify_pending_order_address",
        display="Modify Address",
        tool_name="modify_pending_order_address",
        intent="modify_order_address",
        required_args=("order_id", "address1", "city", "state", "country", "zip"),
        required_slots=("order_id", "address"),
        order_status_check="pending",
        resource_type="order",
        risk="high",
    ),
    WriteActionSpec(
        name="modify_pending_order_items",
        display="Modify Items",
        tool_name="modify_pending_order_items",
        intent="modify_order_items",
        required_args=("order_id", "item_ids", "new_item_ids"),
        required_slots=("order_id", "item_ids", "new_item_ids"),
        order_status_check="pending",
        resource_type="order",
        risk="high",
    ),
    WriteActionSpec(
        name="modify_pending_order_payment",
        display="Modify Payment",
        tool_name="modify_pending_order_payment",
        intent="modify_order_payment",
        required_args=("order_id", "payment_method_id"),
        required_slots=("order_id", "payment_method_id"),
        order_status_check="pending",
        resource_type="order",
        risk="high",
    ),
    WriteActionSpec(
        name="return_delivered_order_items",
        display="Return Items",
        tool_name="return_delivered_order_items",
        intent="return_items",
        required_args=("order_id", "item_ids", "payment_method_id"),
        required_slots=("order_id", "item_ids", "payment_method_id"),
        order_status_check="delivered",
        resource_type="order",
        risk="high",
    ),
    WriteActionSpec(
        name="exchange_delivered_order_items",
        display="Exchange Items",
        tool_name="exchange_delivered_order_items",
        intent="exchange_items",
        required_args=("order_id", "item_ids", "new_item_ids", "payment_method_id"),
        required_slots=("order_id", "item_ids", "new_item_ids", "payment_method_id"),
        order_status_check="delivered",
        resource_type="order",
        risk="high",
    ),
    WriteActionSpec(
        name="modify_user_address",
        display="Modify User Address",
        tool_name="modify_user_address",
        intent="modify_user_address",
        required_args=("user_id", "address1", "city", "state", "country", "zip"),
        required_slots=("address",),
        order_status_check=None,
        resource_type="user",
        risk="medium",
    ),
)

# ── Convenience lookups computed once at module load ──

WRITE_ACTION_BY_NAME: Dict[str, WriteActionSpec] = {
    s.name: s for s in WRITE_ACTION_REGISTRY
}
WRITE_ACTION_BY_INTENT: Dict[str, WriteActionSpec] = {
    s.intent: s for s in WRITE_ACTION_REGISTRY
}
WRITE_ACTION_NAMES: set[str] = {s.name for s in WRITE_ACTION_REGISTRY}
WRITE_TOOL_NAMES: set[str] = {s.tool_name for s in WRITE_ACTION_REGISTRY}
WRITE_INTENTS: set[str] = {s.intent for s in WRITE_ACTION_REGISTRY}


def build_action_catalog_for_prompt() -> str:
    """Generate the allowed pending_write action list for action_planner prompt."""
    lines = ["## Allowed pending_write action_name values"]
    for spec in WRITE_ACTION_REGISTRY:
        args_fmt = ", ".join(spec.required_args)
        lines.append(
            f"- {spec.name}: {args_fmt}"
            + (f" (requires {spec.order_status_check} order)"
               if spec.order_status_check else "")
        )
    return "\n".join(lines)


def tool_params_for_llm(name: str) -> str:
    """LLM-facing parameter descriptions derived from registry."""
    if name not in WRITE_TOOL_NAMES:
        return "(see function signature)"
    spec = WRITE_ACTION_BY_NAME[name]
    return ", ".join(f"{a} (string)" for a in spec.required_args)


def tool_constraints_for_llm(name: str) -> str:
    """LLM-facing constraint descriptions derived from registry."""
    constraints: Dict[str, str] = {
        "cancel_pending_order": (
            "order must be pending; requires user confirmation; "
            "reason must be 'no longer needed' or 'ordered by mistake'"
        ),
        "modify_pending_order_address": (
            "order must be pending; requires user confirmation"
        ),
        "modify_pending_order_items": (
            "order must be pending; new items must be same product as old; "
            "new items must be available; count must match; requires user confirmation"
        ),
        "modify_pending_order_payment": (
            "order must be pending; payment method must belong to user; "
            "must differ from current; gift card must have sufficient balance; "
            "requires user confirmation"
        ),
        "modify_user_address": (
            "target user must be authenticated user; "
            "address passed to user_id argument; requires user confirmation"
        ),
        "return_delivered_order_items": (
            "order must be delivered; items must be in the order; "
            "payment method must belong to user; requires user confirmation"
        ),
        "exchange_delivered_order_items": (
            "order must be delivered; old and new item counts must match; "
            "new items must be same product as old; new items must be available; "
            "payment method must belong to user; requires user confirmation"
        ),
    }
    return constraints.get(name, "requires user confirmation")
