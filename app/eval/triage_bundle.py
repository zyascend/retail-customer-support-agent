from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def build_triage_bundle(result: Mapping[str, Any]) -> dict[str, Any]:
    trace_path = result.get("trace_artifact_path")
    trace = _read_trace(trace_path) if trace_path else {}
    return {
        "case_id": result.get("case_id"),
        "failure_label": result.get("failure_label"),
        "trace_artifact_path": trace_path,
        "user_messages": [
            message.get("content", "")
            for message in trace.get("messages", [])
            if message.get("role") == "user"
        ],
        "assistant_messages": [
            message.get("content", "")
            for message in trace.get("messages", [])
            if message.get("role") == "assistant"
        ],
        "llm_responses": trace.get("metadata", {}).get("llm_responses", []),
        "tool_calls": [
            {
                "tool_name": call.get("tool_name"),
                "status": call.get("status"),
                "error": call.get("error"),
                "block_context": call.get("block_context", {}),
                "observation": call.get("observation"),
            }
            for call in trace.get("tool_calls", [])
        ],
        "guard_context": [
            call.get("block_context", {})
            for call in trace.get("tool_calls", [])
            if call.get("block_context")
        ],
        "db_assertion_diff": result.get("expected_actual_diff", {}),
    }


def _read_trace(trace_path: object) -> dict[str, Any]:
    path = Path(str(trace_path))
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    return payload if isinstance(payload, dict) else {}
