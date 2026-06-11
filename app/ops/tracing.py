from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.agent.models import ConversationState


class TraceWriter:
    def __init__(self, artifact_dir: Path) -> None:
        self.artifact_dir = artifact_dir

    def write(
        self,
        *,
        run_id: str,
        state: ConversationState,
        metadata: Dict[str, Any],
    ) -> Path:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        path = self.artifact_dir / f"{run_id}.json"
        payload = {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata,
            "messages": [message.model_dump() for message in state.messages],
            "steps": [step.model_dump() for step in state.steps],
            "tool_calls": [record.model_dump() for record in state.tool_results],
            "policy_checks": (
                [state.policy_decision.model_dump()] if state.policy_decision else []
            ),
            "write_audit_logs": state.audit_logs,
            "final_state": final_state_summary(state),
        }
        with path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, sort_keys=True, default=str)
            file.write("\n")
        return path


def final_state_summary(state: ConversationState) -> Dict[str, Any]:
    return {
        "session_id": state.session_id,
        "task_id": state.task_id,
        "authenticated_user_id": state.authenticated_user_id,
        "auth_method": state.auth_method,
        "current_intent": state.current_intent,
        "slots": state.slots,
        "confirmation_status": state.confirmation_status,
        "pending_action": (
            state.pending_action.model_dump() if state.pending_action else None
        ),
        "write_locks": state.write_locks,
        "termination_reason": state.termination_reason,
    }

