from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.agent.models import ConversationState
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
    state: ConversationState,
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
            "active_order_id": state.slots.get("order_id"),
            "current_intent": state.current_intent,
            "slots": redact_value(state.slots),
            "confirmation_status": state.confirmation_status,
            "db_changed": initial_db_hash != current_db_hash,
            "initial_db_hash": initial_db_hash,
            "current_db_hash": current_db_hash,
            "write_locks": redact_value(state.write_locks),
        },
        "pending_action": (
            redact_value(to_plain_data(state.pending_action))
            if state.pending_action is not None
            else None
        ),
        "policy_decision": (
            redact_value(to_plain_data(state.policy_decision))
            if state.policy_decision is not None
            else None
        ),
        "tool_results": tool_results,
        "timeline": build_timeline(state),
        "audit_logs": audit_logs,
        "guard_blocks": [
            redact_value(to_plain_data(record))
            for record in state.tool_results
            if record.status == "blocked"
        ],
        "trace_artifact_path": trace_artifact_path,
        "last_error": last_error,
    }


def build_timeline(state: ConversationState) -> List[Dict[str, Any]]:
    timeline: List[Dict[str, Any]] = []

    for index, message in enumerate(state.messages):
        detail = redact_value(to_plain_data(message))
        timeline.append(
            _timeline_event(
                event_id=f"message-{index}",
                kind="message",
                label=message.name or message.role,
                status=None,
                timestamp=message.created_at,
                summary=_summarize_detail(detail.get("content")),
                detail=detail,
                source_index=index,
            )
        )

    for index, step in enumerate(state.steps):
        detail = redact_value(to_plain_data(step.detail))
        timeline.append(
            _timeline_event(
                event_id=f"step-{index}",
                kind="step",
                label=step.node,
                status=step.status,
                timestamp=None,
                summary=_summarize_detail(detail),
                detail=detail,
                source_index=index,
            )
        )

    for index, record in enumerate(state.tool_results):
        detail = redact_value(to_plain_data(record))
        timeline.append(
            _timeline_event(
                event_id=f"tool_call-{index}",
                kind="tool_call",
                label=record.tool_name,
                status=record.status,
                timestamp=None,
                summary=_summarize_detail(detail.get("error"))
                or _summarize_detail(detail.get("observation")),
                detail=detail,
                source_index=index,
            )
        )

    for index, audit in enumerate(state.audit_logs):
        detail = redact_value(audit)
        timeline.append(
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
            )
        )

    return timeline


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
    }


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

