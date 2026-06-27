from __future__ import annotations

from typing import Any, Dict

from app.agent.guard import WriteActionGuard, _canonical_order_id
from app.agent.models import SessionState, ToolCall, ToolCallRecord
from app.ops.serialization import to_plain_data
from app.tools.registry import ToolRegistry


class ToolGateway:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        runtime: Any,
        guard: Any = None,
    ) -> None:
        self.registry = registry
        self.runtime = runtime
        self.guard = guard or WriteActionGuard()

    def execute(
        self,
        *,
        state: SessionState,
        tool_name: str,
        arguments: Dict[str, Any],
        confirmed: bool = False,
    ) -> ToolCallRecord:
        spec = self.registry.get(tool_name)
        before_hash = self.runtime.db_hash()
        normalized_args = arguments
        idempotency_key = None
        resource_lock = None

        # list_user_orders 越权校验：user_id 必须是认证用户（防越权枚举订单）
        if tool_name == "list_user_orders":
            req_user = str(arguments.get("user_id", ""))
            if (
                not state.authenticated_user_id
                or req_user != state.authenticated_user_id
            ):
                observation = {
                    "status": "blocked",
                    "message_for_llm": (
                        "I can only list orders for the authenticated user."
                    ),
                }
                record = ToolCallRecord(
                    tool_name=tool_name,
                    arguments=arguments,
                    tool_kind=spec.kind,
                    status="blocked",
                    observation=observation,
                    error="ownership_violation",
                    before_db_hash=before_hash,
                    after_db_hash=before_hash,
                )
                state.tool_results.append(record)
                state.add_step(
                    "list_user_orders_guard",
                    status="blocked",
                    tool_name=tool_name,
                    block_reason="ownership_violation",
                )
                return record

        if spec.kind == "write":
            guard_result = self.guard.check(
                state=state,
                db=self.runtime.db,
                action=ToolCall(tool_name=tool_name, arguments=arguments),
                confirmed=confirmed,
            )
            idempotency_key = guard_result.idempotency_key
            resource_lock = guard_result.resource_lock
            if not guard_result.allowed:
                observation = _guard_block_observation(
                    tool_name=tool_name,
                    block_reason=guard_result.block_reason,
                    block_context=guard_result.block_context,
                )
                record = ToolCallRecord(
                    tool_name=tool_name,
                    arguments=arguments,
                    tool_kind=spec.kind,
                    status="blocked",
                    observation=observation,
                    error=guard_result.block_reason,
                    block_context=guard_result.block_context,
                    before_db_hash=before_hash,
                    after_db_hash=before_hash,
                    idempotency_key=idempotency_key,
                    resource_lock=resource_lock,
                )
                state.tool_results.append(record)
                state.add_step(
                    "write_action_guard",
                    status="blocked",
                    tool_name=tool_name,
                    block_reason=guard_result.block_reason,
                    block_context=guard_result.block_context,
                )
                return record
            normalized_args = guard_result.normalized_action.arguments

        try:
            result = spec.func(**normalized_args)
            after_hash = self.runtime.db_hash()
            record = ToolCallRecord(
                tool_name=tool_name,
                arguments=normalized_args,
                tool_kind=spec.kind,
                status="success",
                observation=to_plain_data(result),
                before_db_hash=before_hash,
                after_db_hash=after_hash,
                idempotency_key=idempotency_key,
                resource_lock=resource_lock,
            )
            if spec.kind == "write" and resource_lock:
                state.write_locks.append(resource_lock)
                state.audit_logs.append(
                    {
                        "tool_name": tool_name,
                        "arguments": normalized_args,
                        "before_db_hash": before_hash,
                        "after_db_hash": after_hash,
                        "idempotency_key": idempotency_key,
                        "resource_lock": resource_lock,
                    }
                )
            # Update loaded_context for read tools that load context
            self._update_loaded_context(state, tool_name, normalized_args, result)
            state.tool_results.append(record)
            state.add_step(
                "tool_executor",
                tool_name=tool_name,
                status="success",
                tool_kind=spec.kind,
            )
            return record
        except Exception as exc:
            after_hash = self.runtime.db_hash()
            record = ToolCallRecord(
                tool_name=tool_name,
                arguments=normalized_args,
                tool_kind=spec.kind,
                status="error",
                error=type(exc).__name__,
                before_db_hash=before_hash,
                after_db_hash=after_hash,
                idempotency_key=idempotency_key,
                resource_lock=resource_lock,
            )
            state.tool_results.append(record)
            state.add_step(
                "tool_executor",
                tool_name=tool_name,
                status="error",
                error_type=type(exc).__name__,
            )
            return record

    @staticmethod
    def _update_loaded_context(
        state: SessionState,
        tool_name: str,
        args: Dict[str, Any],
        result: Any,
    ) -> None:
        """Update loaded_context when a read tool populates orders/users.

        This ensures the guard's read_before_write check passes
        without requiring the LLM to explicitly load context.
        """
        if tool_name == "get_order_details" and isinstance(result, dict):
            order_id = str(args.get("order_id", ""))
            canonical = _canonical_order_id(order_id)
            state.loaded_context.orders[canonical or order_id] = result
        elif tool_name == "get_user_details" and isinstance(result, dict):
            user_id = str(args.get("user_id", ""))
            state.loaded_context.users.setdefault(user_id, result)
        elif tool_name == "get_product_details" and isinstance(result, dict):
            product_id = str(args.get("product_id", ""))
            state.loaded_context.products[product_id] = result
        elif tool_name == "get_item_details" and isinstance(result, dict):
            item_id = str(args.get("item_id", ""))
            state.loaded_context.items[item_id] = result


def _describe_block_reason(reason: str | None) -> str:
    """Map a guard block-reason code to a concise human-readable phrase."""
    if not reason:
        return "unknown reason"
    return {
        "ownership_violation": "the order belongs to a different account",
        "order_not_found": "the order was not found",
        "non_pending_order_cannot_be_cancelled": "the order is not in pending status",
        "non_pending_order_cannot_be_modified": "the order is not in pending status",
        "non_delivered_order_cannot_be_returned": "the order has not been delivered",
        "non_delivered_order_cannot_be_exchanged": "the order has not been delivered",
        "invalid_cancel_reason": "the cancel reason is not valid",
        "duplicate_write_lock": "a conflicting operation is already in progress",
        "order_already_cancelled_or_locked": "the order is already cancelled or locked",
        "payment_method_not_owned": "the payment method does not belong to you",
        "same_payment_method": "the new payment method is the same as the current one",
        "gift_card_balance_insufficient": "the gift card balance is insufficient",
        "exchange_item_count_mismatch": "the number of old and new items must match",
        "unknown_shipping_method": "the shipping method is not recognized",
        "read_before_write_required": "the order must be looked up first",
        "authentication_required": "you must be logged in",
        "explicit_confirmation_required": "the operation requires your confirmation",
        "unsupported_in_mvp": "this action is not yet supported",
        "unknown_write_action": "this action is not recognized",
    }.get(reason, reason)


def _guard_block_observation(
    *,
    tool_name: str,
    block_reason: str | None,
    block_context: Dict[str, Any],
) -> Dict[str, Any]:
    resource_id = block_context.get("resource_id") or block_context.get("order_id") or ""
    resource_ref = f" for {resource_id}" if resource_id else ""
    description = _describe_block_reason(block_reason)
    return {
        "status": "blocked",
        "error_type": "guard_blocked",
        "tool_name": tool_name,
        "block_reason": block_reason,
        "block_context": block_context,
        "message_for_llm": (
            f"Tool {tool_name}{resource_ref} was blocked: {description}. "
            "Inform the user of the reason and suggest next steps."
        ),
        "retryable": False,
    }
