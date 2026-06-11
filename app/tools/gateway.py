from __future__ import annotations

from typing import Any, Dict

from app.agent.guard import WriteActionGuard
from app.agent.models import ConversationState, ToolCall, ToolCallRecord
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
        state: ConversationState,
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
                record = ToolCallRecord(
                    tool_name=tool_name,
                    arguments=arguments,
                    tool_kind=spec.kind,
                    status="blocked",
                    error=guard_result.block_reason,
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
                error=str(exc),
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
                error=str(exc),
            )
            return record
