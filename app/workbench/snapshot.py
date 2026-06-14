from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.agent.models import SessionState
from app.ops.serialization import to_plain_data

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\w)"
)
SENSITIVE_KEYS = {"email", "phone", "payment", "zip", "address", "street"}


def snapshot_from_state(
    *,
    session_id: str,
    mode: str,
    llm_available: bool,
    state: SessionState,
    initial_db_hash: Optional[str],
    current_db_hash: Optional[str],
    trace_artifact_path: Optional[str],
    selected_case_id: Optional[str],
    script_cursor: int,
    script_message_count: int,
    last_error: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    can_advance = bool(selected_case_id) and script_cursor < script_message_count
    messages = redact_value(to_plain_data(state.messages))
    tool_results = redact_value(to_plain_data(state.tool_results))
    audit_logs = redact_value(to_plain_data(state.audit_logs))

    return {
        "session_id": session_id,
        "mode": mode,
        "llm_available": llm_available,
        "selected_case_id": selected_case_id,
        "script_cursor": script_cursor,
        "script_message_count": script_message_count,
        "run_controls": {
            "can_step": can_advance,
            "can_run_all": can_advance,
            "can_reset": True,
        },
        "messages": messages,
        "business": {
            "authenticated_user_id": state.authenticated_user_id,
            "auth_method": state.auth_method,
            "active_user_identity": redact_value(state.active_user_identity),
            "active_order_id": None,
            "confirmation_status": state.confirmation_status,
            "db_changed": initial_db_hash != current_db_hash,
            "initial_db_hash": initial_db_hash,
            "current_db_hash": current_db_hash,
            "write_locks": redact_value(state.write_locks),
        },
        "compat": {
            "current_intent": "unknown",
            "slots": {},
            "policy_decision": None,
        },
        "pending_action": (
            redact_value(to_plain_data(state.pending_action))
            if state.pending_action is not None
            else None
        ),
        "tool_results": tool_results,
        "timeline": build_timeline(state),
        "audit_logs": audit_logs,
        "guard_blocks": build_guard_blocks(state),
        "trace_artifact_path": trace_artifact_path,
        "last_error": last_error,
    }


_PRIMARY_STEPS = {"intent_and_slot_extractor", "policy_reasoner", "write_action_guard"}


def _step_weight(node: str) -> str:
    return "primary" if node in _PRIMARY_STEPS else "secondary"


def build_timeline(state: SessionState) -> List[Dict[str, Any]]:
    timeline: List[tuple[tuple[int, int, int], Dict[str, Any]]] = []

    for index, message in enumerate(state.messages):
        detail = redact_value(to_plain_data(message))
        timeline.append(
            (
                _message_sort_key(state.messages[: index + 1], message.role, index),
                _timeline_event(
                    event_id=f"message-{index}",
                    kind="message",
                    label=message.name or message.role,
                    status=None,
                    timestamp=message.created_at,
                    summary=_summarize_detail(detail.get("content")),
                    detail=detail,
                    source_index=index,
                ),
            )
        )

    tool_index = 0
    for index, step in enumerate(state.steps):
        detail = redact_value(to_plain_data(step.detail))
        turn_index = _step_turn_index(state.steps[: index + 1])
        timeline.append(
            (
                (turn_index, 20 + index, index),
                _timeline_event(
                    event_id=f"step-{index}",
                    kind="step",
                    label=step.node,
                    status=step.status,
                    timestamp=None,
                    summary=_summarize_detail(detail),
                    detail=detail,
                    source_index=index,
                    weight=_step_weight(step.node),
                ),
            )
        )
        if step.node in {"tool_executor", "write_action_guard"} and tool_index < len(
            state.tool_results
        ):
            record = state.tool_results[tool_index]
            if (step.node == "write_action_guard" and record.status == "blocked") or (
                step.node == "tool_executor"
                and record.status != "blocked"
                and "tool_name" in detail
            ):
                timeline.append(
                    (
                        (turn_index, 21 + index, tool_index),
                        _tool_timeline_event(record, tool_index),
                    )
                )
                tool_index += 1

    fallback_turn_index = max(_step_turn_index(state.steps), 0)
    while tool_index < len(state.tool_results):
        timeline.append(
            (
                (fallback_turn_index, 70, tool_index),
                _tool_timeline_event(state.tool_results[tool_index], tool_index),
            )
        )
        tool_index += 1

    for index, audit in enumerate(state.audit_logs):
        detail = redact_value(audit)
        timeline.append(
            (
                (fallback_turn_index, 80, index),
                _timeline_event(
                    event_id=f"write_audit-{index}",
                    kind="write_audit",
                    label=str(
                        audit.get("tool_name")
                        or audit.get("action_name")
                        or audit.get("event")
                        or "write_audit"
                    ),
                    status=audit.get("status"),
                    timestamp=audit.get("timestamp") or audit.get("created_at"),
                    summary=_summarize_detail(detail),
                    detail=detail,
                    source_index=index,
                    weight="primary",
                ),
            )
        )

    return [event for _, event in sorted(timeline, key=lambda item: item[0])]


def build_guard_blocks(state: SessionState) -> List[Dict[str, Any]]:
    guard_blocks = [
        redact_value(to_plain_data(record))
        for record in state.tool_results
        if record.status == "blocked"
    ]
    guard_blocks.extend(_wrong_user_guard_blocks(state))
    return guard_blocks


def redact_value(value: Any, key: str = "") -> Any:
    plain_value = to_plain_data(value)

    if _is_sensitive_key(key):
        return _redacted_for_key(key)

    if isinstance(plain_value, dict):
        return {
            str(item_key): redact_value(item_value, str(item_key))
            for item_key, item_value in plain_value.items()
        }

    if isinstance(plain_value, list):
        return [redact_value(item, key) for item in plain_value]

    if isinstance(plain_value, tuple):
        return [redact_value(item, key) for item in plain_value]

    if isinstance(plain_value, str):
        text = EMAIL_RE.sub("[redacted-email]", plain_value)
        text = PHONE_RE.sub("[redacted-phone]", text)
        return text

    return plain_value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(sensitive_key in normalized for sensitive_key in SENSITIVE_KEYS)


def _redacted_for_key(key: str) -> str:
    normalized = key.lower()
    if "email" in normalized:
        return "[redacted-email]"
    if "phone" in normalized:
        return "[redacted-phone]"
    if "address" in normalized or "street" in normalized:
        return "[redacted-address]"
    if "zip" in normalized:
        return "[redacted-zip]"
    if "payment" in normalized:
        return "[redacted-payment]"
    return "[redacted]"


def _timeline_event(
    *,
    event_id: str,
    kind: str,
    label: str,
    status: Optional[str],
    timestamp: Optional[str],
    summary: Optional[str],
    detail: Any,
    source_index: int,
    weight: str = "secondary",
) -> Dict[str, Any]:
    return {
        "id": event_id,
        "kind": kind,
        "label": label,
        "status": status,
        "timestamp": timestamp,
        "summary": summary,
        "detail": detail,
        "source_index": source_index,
        "weight": weight,
    }


def _tool_timeline_event(record: Any, index: int) -> Dict[str, Any]:
    detail = redact_value(to_plain_data(record))
    return _timeline_event(
        event_id=f"tool_call-{index}",
        kind="tool_call",
        label=record.tool_name,
        status=record.status,
        timestamp=None,
        summary=_summarize_detail(detail.get("error"))
        or _summarize_detail(detail.get("observation")),
        detail=detail,
        source_index=index,
        weight="primary",
    )


def _message_sort_key(
    messages_so_far: List[Any], role: str, index: int
) -> tuple[int, int, int]:
    turn_index = sum(1 for message in messages_so_far if message.role == "user") - 1
    if turn_index < 0:
        turn_index = 0
    phase = 10 if role == "user" else 90
    return (turn_index, phase, index)


def _step_turn_index(steps: List[Any]) -> int:
    receive_count = sum(1 for step in steps if step.node == "receive_message")
    return max(receive_count - 1, 0)


def _wrong_user_guard_blocks(state: SessionState) -> List[Dict[str, Any]]:
    if not state.authenticated_user_id:
        return []

    guard_blocks = []
    for order_id, order in state.loaded_context.orders.items():
        if order.get("user_id") == state.authenticated_user_id:
            continue
        guard_blocks.append(
            redact_value(
                {
                    "tool_name": "context_loader",
                    "arguments": {"order_id": order_id},
                    "tool_kind": "read",
                    "status": "blocked",
                    "error": "wrong_user_order_access",
                    "observation": {
                        "order_id": order_id,
                        "order_user_id": order.get("user_id"),
                        "authenticated_user_id": state.authenticated_user_id,
                    },
                }
            )
        )
    return guard_blocks


def _summarize_detail(detail: Any) -> Optional[str]:
    if detail is None:
        return None
    if isinstance(detail, str):
        return _truncate(detail)
    if isinstance(detail, dict):
        for key in ("summary", "user_facing_summary", "error", "status", "content"):
            value = detail.get(key)
            if value:
                return _truncate(str(value))
    return _truncate(json.dumps(detail, sort_keys=True, default=str))


def _truncate(value: str, limit: int = 160) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."
