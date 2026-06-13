from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.agent.models import SessionState


class TraceWriter:
    def __init__(self, artifact_dir: Path) -> None:
        self.artifact_dir = artifact_dir

    def write(
        self,
        *,
        run_id: str,
        state: SessionState,
        metadata: Dict[str, Any],
    ) -> Path:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        path = self.artifact_dir / f"{run_id}.json"
        self.write_path(path=path, run_id=run_id, state=state, metadata=metadata)
        return path

    def write_path(
        self,
        *,
        path: Path,
        run_id: str,
        state: SessionState,
        metadata: Dict[str, Any],
    ) -> Path:
        payload = build_trace_payload(
            run_id=run_id,
            state=state,
            metadata=metadata,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, sort_keys=True, default=str)
            file.write("\n")
        return path


def build_trace_payload(
    *,
    run_id: str,
    state: SessionState,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata,
        "messages": [message.model_dump() for message in state.messages],
        "steps": [step.model_dump() for step in state.steps],
        "tool_calls": [record.model_dump() for record in state.tool_results],
        "write_audit_logs": state.audit_logs,
        "final_state": final_state_summary(state),
        "timing": _build_timing_section(state),
    }


def _build_timing_section(state: SessionState) -> dict:
    step_durations = getattr(state, "step_durations", {}) or {}
    llm_call_durations = getattr(state, "llm_call_durations", []) or []
    total_ms = sum(step_durations.values())
    llm_total_ms = sum(call.get("duration_ms", 0) for call in llm_call_durations)
    return {
        "step_durations_ms": step_durations,
        "total_ms": round(total_ms, 1),
        "llm_total_ms": round(llm_total_ms, 1),
        "llm_calls": llm_call_durations,
    }


def final_state_summary(state: SessionState) -> Dict[str, Any]:
    return {
        "session_id": state.session_id,
        "task_id": state.task_id,
        "authenticated_user_id": state.authenticated_user_id,
        "auth_method": state.auth_method,
        "confirmation_status": state.confirmation_status,
        "current_intent": "unknown",
        "slots": {},
        "pending_action": (
            state.pending_action.model_dump() if state.pending_action else None
        ),
        "write_locks": state.write_locks,
        "termination_reason": state.termination_reason,
    }
