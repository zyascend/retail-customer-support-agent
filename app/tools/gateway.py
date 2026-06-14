from __future__ import annotations

from typing import Any, Dict

from app.agent.guard import WriteActionGuard
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
            clean_id = order_id.lstrip("#")
            state.loaded_context.orders[clean_id] = result
            state.loaded_context.orders[f"#{clean_id}"] = result
            if order_id not in (clean_id, f"#{clean_id}"):
                state.loaded_context.orders[order_id] = result
        elif tool_name == "get_user_details" and isinstance(result, dict):
            user_id = str(args.get("user_id", ""))
            state.loaded_context.users.setdefault(user_id, result)
        elif tool_name == "get_product_details" and isinstance(result, dict):
            product_id = str(args.get("product_id", ""))
            state.loaded_context.products[product_id] = result
        elif tool_name == "get_item_details" and isinstance(result, dict):
            item_id = str(args.get("item_id", ""))
            state.loaded_context.items[item_id] = result


def _guard_block_observation(
    *,
    tool_name: str,
    block_reason: str | None,
    block_context: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "status": "blocked",
        "error_type": "guard_blocked",
        "tool_name": tool_name,
        "block_reason": block_reason,
        "block_context": block_context,
        "message_for_llm": (
            f"Tool {tool_name} was blocked by the write guard. "
            f"Reason: {block_reason}. "
            f"Context: {to_plain_data(block_context)}. "
            "Explain the safe next step to the user without exposing sensitive data."
        ),
        "retryable": False,
    }
