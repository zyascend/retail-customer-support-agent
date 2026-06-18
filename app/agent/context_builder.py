from __future__ import annotations

import re

from app.agent.models import SessionState, ToolCallRecord

# ── Semantic lock labels: map lock strings (e.g. "order:#W123:cancel") → human-readable ──
_LOCK_LABEL_PATTERNS: list[tuple[str, str]] = [
    (r"^order:#W\d+:cancel$", "cancellation in progress"),
    (r"^order:#W\d+:modify_address$", "address change in progress"),
    (r"^order:#W\d+:modify_items$", "item change in progress"),
    (r"^order:#W\d+:modify_payment$", "payment change in progress"),
    (r"^order:#W\d+:modify_shipping_method$", "shipping change in progress"),
    (r"^item:[^:]+:return$", "return in progress"),
    (r"^item:[^:]+:exchange$", "exchange in progress"),
    (r"^user:[^:]+:modify_address$", "address change in progress"),
]

# ── Semantic block-reason labels ──
_BLOCK_REASON_LABELS: dict[str, str] = {
    "ownership_violation": "order belongs to another account",
    "order_not_found": "order not found",
    "non_pending_order_cannot_be_cancelled": "order is not pending",
    "non_pending_order_cannot_be_modified": "order is not pending",
    "non_delivered_order_cannot_be_returned": "order is not delivered",
    "non_delivered_order_cannot_be_exchanged": "order is not delivered",
    "invalid_cancel_reason": "invalid cancel reason",
    "duplicate_write_lock": "conflicting operation in progress",
    "order_already_cancelled_or_locked": "order already locked",
    "payment_method_not_owned": "payment method not yours",
    "same_payment_method": "same payment method",
    "gift_card_balance_insufficient": "insufficient gift card balance",
    "exchange_item_count_mismatch": "item count mismatch",
    "unknown_shipping_method": "unknown shipping method",
    "read_before_write_required": "needs order lookup first",
    "authentication_required": "login required",
}

_ORDER_ID_FROM_LOCK_RE = re.compile(r"^(?:order|item|user):(#W\d+)(?::|$)")


def _describe_lock(lock_str: str) -> str:
    """Convert a technical lock string to a human-readable label.

    ``order:#W123:cancel`` → ``cancellation in progress for #W123``
    """
    match = _ORDER_ID_FROM_LOCK_RE.match(lock_str)
    resource = match.group(1) if match else ""
    for pattern, label in _LOCK_LABEL_PATTERNS:
        if re.fullmatch(pattern, lock_str):
            return f"{label} for {resource}" if resource else label
    return lock_str  # fallback: raw string


def _describe_block_reason(reason: str | None) -> str:
    """Map an internal block-reason code to a user-facing description."""
    if not reason:
        return "unknown reason"
    return _BLOCK_REASON_LABELS.get(reason, reason)


class ContextBuilder:
    """Builds a compressed LLM-visible state summary from SessionState.

    Target budget: ~1200 tokens. Provides the LLM with context needed for
    tool-calling decisions without overwhelming the prompt with raw DB objects.
    """

    def __init__(self, *, policy_text: str, max_recent_messages: int = 6) -> None:
        self._policy_text = policy_text
        self._max_recent_messages = max_recent_messages

    @property
    def policy_text(self) -> str:
        return self._policy_text

    def build(self, session: SessionState) -> str:  # noqa: C901
        parts: list[str] = []

        if session.authenticated_user_id:
            user_line = f"User: user_id={session.authenticated_user_id}"
            if session.auth_method:
                user_line += f" ({session.auth_method})"
            parts.append(user_line)

        if session.loaded_context.orders:
            order_parts = []
            for oid, order in session.loaded_context.orders.items():
                status = order.get("status", "?")
                items = order.get("items", [])
                item_count = len(items) if isinstance(items, list) else 0
                order_parts.append(f"{oid}={status} ({item_count} items)")
            parts.append("Orders: " + ", ".join(order_parts))

        payment_parts = []
        for user in session.loaded_context.users.values():
            methods = user.get("payment_methods", {}) if isinstance(user, dict) else {}
            if not isinstance(methods, dict):
                continue
            for method_id, method in methods.items():
                if not isinstance(method, dict):
                    payment_parts.append(str(method_id))
                    continue
                source = method.get("source")
                balance = method.get("balance")
                if balance is not None:
                    payment_parts.append(f"{method_id}({source}, balance={balance})")
                elif source:
                    payment_parts.append(f"{method_id}({source})")
                else:
                    payment_parts.append(str(method_id))
        if payment_parts:
            parts.append("Payment methods: " + ", ".join(payment_parts))

        if session.pending_action:
            parts.append(
                f"Pending: {session.pending_action.action_name} "
                f"— waiting for user confirmation"
            )
        else:
            if session.write_locks:
                lock_descriptions = [_describe_lock(lock) for lock in session.write_locks]
                parts.append("Active safeguards: " + ", ".join(lock_descriptions))

            recent_successful_writes = [
                record
                for record in reversed(session.tool_results)
                if record.tool_kind == "write" and record.status == "success"
            ][:3]
            if recent_successful_writes:
                summaries = [
                    self._format_successful_write(record)
                    for record in reversed(recent_successful_writes)
                ]
                parts.append("Recent successful writes: " + "; ".join(summaries))

        recent_guard_block = next(
            (
                record
                for record in reversed(session.tool_results)
                if record.status == "blocked"
                and record.error != "explicit_confirmation_required"
            ),
            None,
        )
        if recent_guard_block and recent_guard_block.error:
            order_id = recent_guard_block.arguments.get("order_id")
            resource_ref = f" on {order_id}" if order_id else ""
            description = _describe_block_reason(recent_guard_block.error)
            parts.append(
                "Recent guard block: "
                f"{recent_guard_block.tool_name}{resource_ref} — {description}"
            )

        recent_tool_error = next(
            (
                record
                for record in reversed(session.tool_results)
                if record.status == "error"
            ),
            None,
        )
        if recent_tool_error and recent_tool_error.error:
            parts.append(
                "Recent tool error: "
                f"{recent_tool_error.tool_name} {recent_tool_error.error}"
            )

        return "\n".join(parts)

    @staticmethod
    def _format_successful_write(record: ToolCallRecord) -> str:
        fields = [record.tool_name]
        if record.resource_lock:
            fields.append(f"lock={record.resource_lock}")

        order_id = record.arguments.get("order_id")
        if order_id:
            fields.append(f"order={order_id}")

        item_ids = _string_list(record.arguments.get("item_ids"))
        if item_ids:
            fields.append("target_items=[" + ", ".join(item_ids) + "]")

        new_item_ids = _string_list(record.arguments.get("new_item_ids"))
        if item_ids and new_item_ids:
            replacements = [
                f"{old}->{new}" for old, new in zip(item_ids, new_item_ids, strict=False)
            ]
            fields.append("replacements=[" + ", ".join(replacements) + "]")

        observation = record.observation if isinstance(record.observation, dict) else {}
        status = observation.get("status")
        if status:
            fields.append(f"status={status}")

        payment_parts = []
        for payment in observation.get("payment_history", []) or []:
            if not isinstance(payment, dict):
                continue
            amount = payment.get("amount")
            method = payment.get("payment_method_id")
            tx_type = payment.get("transaction_type")
            if amount is None:
                continue
            if tx_type and method:
                payment_parts.append(f"{tx_type} {amount} via {method}")
            elif tx_type:
                payment_parts.append(f"{tx_type} {amount}")
            else:
                payment_parts.append(str(amount))
        if payment_parts:
            fields.append("payments=[" + ", ".join(payment_parts) + "]")

        item_parts = []
        for item in observation.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            item_id = item.get("item_id")
            name = item.get("name")
            price = item.get("price")
            if item_id and name and price is not None:
                item_parts.append(f"{item_id} {name} {price}")
        if item_parts:
            fields.append("items=[" + ", ".join(item_parts[:5]) + "]")

        target_total = _target_item_total(observation, item_ids)
        if target_total is not None:
            fields.append(f"target_item_total={target_total:.2f}")

        return " ".join(fields)

    def estimate_tokens(self, text: str) -> int:
        return max(1, int(len(text.split()) / 0.75))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _target_item_total(observation: dict, item_ids: list[str]) -> float | None:
    if not item_ids:
        return None
    wanted = set(item_ids)
    total = 0.0
    matched = False
    for item in observation.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("item_id")) not in wanted:
            continue
        price = item.get("price")
        if price is None:
            continue
        total += float(price)
        matched = True
    return total if matched else None
