from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.agent.models import ConversationState, ToolCall
from app.ops.serialization import stable_hash
from app.tools.retail_adapter import (
    find_variant_in_db,
    get_current_payment_method_id,
    get_order_from_db,
    get_user_from_db,
)

from app.agent.action_specs import WRITE_ACTION_NAMES

WRITE_ACTIONS = WRITE_ACTION_NAMES
DEFERRED_WRITE_ACTIONS: set[str] = set()


@dataclass
class WriteActionGuardResult:
    allowed: bool
    block_reason: Optional[str] = None
    missing_requirements: List[str] = field(default_factory=list)
    required_user_confirmation: bool = True
    risk_level: str = "medium"
    normalized_action: Optional[ToolCall] = None
    user_facing_summary: Optional[str] = None
    idempotency_key: Optional[str] = None
    resource_lock: Optional[str] = None


class WriteActionGuard:
    def check(
        self,
        *,
        state: ConversationState,
        db: Any,
        action: ToolCall,
        confirmed: bool,
    ) -> WriteActionGuardResult:
        if action.tool_name in DEFERRED_WRITE_ACTIONS:
            return self._blocked("unsupported_in_mvp")
        if action.tool_name not in WRITE_ACTIONS:
            return self._blocked("unknown_write_action")
        if not state.authenticated_user_id:
            return self._blocked("authentication_required")
        if not confirmed:
            return self._blocked(
                "explicit_confirmation_required",
                missing=["explicit_user_confirmation"],
            )

        normalized = ToolCall(
            tool_name=action.tool_name,
            arguments=self._normalize_args(action.arguments),
        )
        ownership_reason = self._validate_ownership(state, db, normalized)
        if ownership_reason:
            return self._blocked(ownership_reason)
        read_reason = self._validate_read_before_write(state, normalized)
        if read_reason:
            return self._blocked(read_reason, missing=["read_before_write"])
        policy_reason = self._validate_policy(db, normalized)
        if policy_reason:
            return self._blocked(policy_reason)

        lock = self._resource_lock(normalized)
        conflict = self._lock_conflict(state.write_locks, lock, normalized.tool_name)
        if conflict:
            return self._blocked(conflict)

        idempotency_key = stable_hash(
            {
                "session_id": state.session_id,
                "tool_name": normalized.tool_name,
                "arguments": normalized.arguments,
                "resource_lock": lock,
            }
        )
        return WriteActionGuardResult(
            allowed=True,
            normalized_action=normalized,
            user_facing_summary=self._summary(normalized),
            idempotency_key=idempotency_key,
            resource_lock=lock,
        )

    def _blocked(
        self, reason: str, missing: Optional[List[str]] = None
    ) -> WriteActionGuardResult:
        return WriteActionGuardResult(
            allowed=False,
            block_reason=reason,
            missing_requirements=missing or [],
        )

    def _normalize_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {}
        for key, value in args.items():
            if isinstance(value, list):
                normalized[key] = [str(item) for item in value]
            elif value is None:
                normalized[key] = value
            else:
                normalized[key] = str(value)
        return normalized

    def _validate_ownership(
        self, state: ConversationState, db: Any, action: ToolCall
    ) -> Optional[str]:
        user_id = state.authenticated_user_id
        if action.tool_name == "modify_user_address":
            if action.arguments.get("user_id") == user_id:
                return None
            return "ownership_violation"
        order_id = action.arguments.get("order_id")
        if order_id:
            order = get_order_from_db(db, order_id)
            if not order:
                return "order_not_found"
            if order.get("user_id") != user_id:
                return "ownership_violation"
        return None

    def _validate_read_before_write(
        self, state: ConversationState, action: ToolCall
    ) -> Optional[str]:
        order_id = action.arguments.get("order_id")
        if order_id and order_id not in state.loaded_context.orders:
            return "read_before_write_required"
        user_id = action.arguments.get("user_id")
        if action.tool_name == "modify_user_address" and user_id:
            if user_id not in state.loaded_context.users:
                return "read_before_write_required"
        return None

    def _validate_policy(self, db: Any, action: ToolCall) -> Optional[str]:
        args = action.arguments
        order_id = args.get("order_id")
        order = get_order_from_db(db, order_id) if order_id else None
        if action.tool_name == "cancel_pending_order":
            if not order or order.get("status") != "pending":
                return "non_pending_order_cannot_be_cancelled"
            if args.get("reason") not in {"no longer needed", "ordered by mistake"}:
                return "invalid_cancel_reason"
        if action.tool_name == "modify_pending_order_address":
            if not order or order.get("status") != "pending":
                return "non_pending_order_cannot_be_modified"
        if action.tool_name == "return_delivered_order_items":
            if not order or order.get("status") != "delivered":
                return "non_delivered_order_cannot_be_returned"
        if action.tool_name == "exchange_delivered_order_items":
            if not order or order.get("status") != "delivered":
                return "non_delivered_order_cannot_be_exchanged"
            if len(args.get("item_ids", [])) != len(args.get("new_item_ids", [])):
                return "exchange_item_count_mismatch"
            replacement_reason = self._validate_item_replacements(db, order, args)
            if replacement_reason:
                return replacement_reason
        if action.tool_name == "modify_pending_order_items":
            if not order or order.get("status") != "pending":
                return "non_pending_order_cannot_be_modified"
            replacement_reason = self._validate_item_replacements(db, order, args)
            if replacement_reason:
                return replacement_reason
        if action.tool_name == "modify_pending_order_payment":
            if not order or order.get("status") != "pending":
                return "non_pending_order_cannot_be_modified"
            payment_reason = self._validate_payment_change(db, order, args)
            if payment_reason:
                return payment_reason
        if action.tool_name == "modify_user_address":
            if not get_user_from_db(db, args.get("user_id", "")):
                return "user_not_found"
        return None

    def _validate_item_replacements(
        self, db: Any, order: Dict[str, Any], args: Dict[str, Any]
    ) -> Optional[str]:
        item_ids = args.get("item_ids", [])
        new_item_ids = args.get("new_item_ids", [])
        if len(item_ids) != len(new_item_ids):
            return "replacement_item_count_mismatch"
        order_items = order.get("items", [])
        for old_item_id, new_item_id in zip(item_ids, new_item_ids):
            old_item = next(
                (item for item in order_items if item.get("item_id") == old_item_id),
                None,
            )
            if old_item is None:
                return "order_item_not_found"
            new_variant = find_variant_in_db(db, new_item_id)
            if new_variant is None:
                return "replacement_item_not_found"
            if new_variant.get("product_id") != old_item.get("product_id"):
                return "replacement_item_product_mismatch"
            if not new_variant.get("available"):
                return "replacement_item_unavailable"
        return None

    def _validate_payment_change(
        self, db: Any, order: Dict[str, Any], args: Dict[str, Any]
    ) -> Optional[str]:
        user = get_user_from_db(db, order.get("user_id", ""))
        if not user:
            return "user_not_found"
        payment_method_id = args.get("payment_method_id")
        payment_method = user.get("payment_methods", {}).get(payment_method_id)
        if payment_method is None:
            return "payment_method_not_owned"
        current_payment_method_id = get_current_payment_method_id(order)
        if payment_method_id == current_payment_method_id:
            return "same_payment_method"
        if payment_method.get("source") == "gift_card":
            amount = sum(float(item.get("price", 0.0)) for item in order.get("items", []))
            if float(payment_method.get("balance", 0.0)) < amount:
                return "gift_card_balance_insufficient"
        return None

    def _resource_lock(self, action: ToolCall) -> str:
        args = action.arguments
        if action.tool_name == "modify_user_address":
            return f"user:{args.get('user_id')}:modify_address"
        item_level_actions = {
            "return_delivered_order_items",
            "exchange_delivered_order_items",
        }
        if action.tool_name in item_level_actions:
            item_ids = ",".join(sorted(args.get("item_ids", [])))
            category = "return" if action.tool_name.startswith("return") else "exchange"
            return f"item:{item_ids}:{category}"
        category = {
            "cancel_pending_order": "cancel",
            "modify_pending_order_address": "modify_address",
            "modify_pending_order_items": "modify_items",
            "modify_pending_order_payment": "modify_payment",
        }.get(action.tool_name, action.tool_name)
        return f"order:{args.get('order_id')}:{category}"

    def _lock_conflict(
        self, existing_locks: List[str], new_lock: str, action_name: str
    ) -> Optional[str]:
        if new_lock in existing_locks:
            return "duplicate_write_lock"
        if new_lock.startswith("order:"):
            order_id = new_lock.split(":")[1]
            if f"order:{order_id}:cancel" in existing_locks:
                return "order_already_cancelled_or_locked"
            if action_name in {"cancel_pending_order", "modify_pending_order_items"}:
                if f"order:{order_id}:modify_items" in existing_locks:
                    return "order_items_already_modified"
        if new_lock.startswith("item:"):
            item_ids = set(new_lock.split(":")[1].split(","))
            for lock in existing_locks:
                if lock.startswith("item:"):
                    locked_items = set(lock.split(":")[1].split(","))
                    if item_ids & locked_items:
                        return "item_already_returned_or_exchanged"
        return None

    def _summary(self, action: ToolCall) -> str:
        if action.tool_name == "cancel_pending_order":
            return (
                f"Cancel order {action.arguments.get('order_id')} because "
                f"{action.arguments.get('reason')}."
            )
        if action.tool_name == "modify_pending_order_address":
            return (
                "Modify shipping address for order "
                f"{action.arguments.get('order_id')}."
            )
        if action.tool_name == "return_delivered_order_items":
            return f"Request return for order {action.arguments.get('order_id')}."
        if action.tool_name == "exchange_delivered_order_items":
            return f"Request exchange for order {action.arguments.get('order_id')}."
        if action.tool_name == "modify_pending_order_items":
            return (
                f"Modify items for order {action.arguments.get('order_id')}."
            )
        if action.tool_name == "modify_pending_order_payment":
            return (
                f"Modify payment for order {action.arguments.get('order_id')}."
            )
        if action.tool_name == "modify_user_address":
            return f"Modify default address for user {action.arguments.get('user_id')}."
        return action.tool_name
