from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from app.pydantic_compat import BaseModel, Field

Role = Literal["user", "assistant", "tool", "system"]
ConfirmationStatus = Literal[
    "not_required", "required", "confirmed", "denied", "changed", "unknown"
]
ToolKind = Literal["read", "write", "generic", "think"]


class Message(BaseModel):
    role: Role
    content: str
    name: Optional[str] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ToolCall(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class PendingAction(BaseModel):
    action_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    user_facing_summary: str
    risk_level: Literal["low", "medium", "high"] = "medium"
    idempotency_key: Optional[str] = None
    resource_lock: Optional[str] = None


class PolicyDecision(BaseModel):
    decision: Literal["allow", "ask_clarification", "deny", "transfer"]
    intent: str = "unknown"
    missing_slots: List[str] = Field(default_factory=list)
    user_confirmation_required: bool = False
    explanation_for_user: str = ""
    internal_reasoning_summary: str = ""


class LoadedContext(BaseModel):
    users: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    orders: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    products: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    items: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class ToolCallRecord(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]
    tool_kind: ToolKind
    status: Literal["success", "blocked", "error"]
    observation: Optional[Any] = None
    error: Optional[str] = None
    before_db_hash: Optional[str] = None
    after_db_hash: Optional[str] = None
    idempotency_key: Optional[str] = None
    resource_lock: Optional[str] = None


class AgentStep(BaseModel):
    node: str
    status: Literal["ok", "blocked", "error"] = "ok"
    detail: Dict[str, Any] = Field(default_factory=dict)


class ConversationState(BaseModel):
    session_id: str
    task_id: Optional[str] = None
    authenticated_user_id: Optional[str] = None
    auth_method: Optional[str] = None
    active_user_identity: Dict[str, Any] = Field(default_factory=dict)
    messages: List[Message] = Field(default_factory=list)
    current_intent: str = "unknown"
    slots: Dict[str, Any] = Field(default_factory=dict)
    loaded_context: LoadedContext = Field(default_factory=LoadedContext)
    pending_action: Optional[PendingAction] = None
    confirmation_status: ConfirmationStatus = "not_required"
    policy_decision: Optional[PolicyDecision] = None
    risk_level: Literal["low", "medium", "high"] = "low"
    tool_results: List[ToolCallRecord] = Field(default_factory=list)
    write_locks: List[str] = Field(default_factory=list)
    run_metrics: Dict[str, Any] = Field(default_factory=dict)
    steps: List[AgentStep] = Field(default_factory=list)
    audit_logs: List[Dict[str, Any]] = Field(default_factory=list)
    termination_reason: Optional[str] = None

    # ── Timing (Module 3) ──
    step_durations: dict[str, float] = Field(default_factory=dict)
    # {"identity_resolver": 45.2, "intent_and_slot_extractor": 210.8, ...}

    llm_call_durations: list[dict] = Field(default_factory=list)
    # [{"node": "policy_reasoner", "call_type": "json", "duration_ms": 185.2, "status": "ok"}, ...]

    def add_step(self, node: str, **detail: Any) -> None:
        self.steps.append(AgentStep(node=node, detail=detail))
