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


class ToolCallRequest(BaseModel):
    id: str
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    raw_arguments: Optional[str] = None


class ToolCallResponse(BaseModel):
    assistant_content: Optional[str] = None
    tool_calls: List[ToolCallRequest] = Field(default_factory=list)
    finish_reason: Optional[str] = None
    token_usage: Optional[Dict[str, Any]] = None
    reasoning_content: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class ToolExecutionError(BaseModel):
    status: Literal["error"] = "error"
    error_type: Literal[
        "unknown_tool",
        "malformed_arguments",
        "missing_required_args",
        "tool_execution_error",
        "guard_blocked",
        "prompt_injection_write_blocked",
        "premature_transfer_blocked",
    ]
    message_for_llm: str
    retryable: bool
    block_context: Dict[str, Any] = Field(default_factory=dict)
    missing_args: List[str] = Field(default_factory=list)
    allowed_tools: Optional[List[str]] = None


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


class ActionCandidate(BaseModel):
    tool_name: str
    confidence: Literal["low", "medium", "high"] = "medium"
    reason: str
    order_id: Optional[str] = None
    item_ids: List[str] = Field(default_factory=list)
    product_ids: List[str] = Field(default_factory=list)
    required_read_tools: List[str] = Field(default_factory=list)


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
    block_context: Dict[str, Any] = Field(default_factory=dict)
    before_db_hash: Optional[str] = None
    after_db_hash: Optional[str] = None
    idempotency_key: Optional[str] = None
    resource_lock: Optional[str] = None


class AgentStep(BaseModel):
    node: str
    status: Literal["ok", "blocked", "error"] = "ok"
    detail: Dict[str, Any] = Field(default_factory=dict)


class SessionState(BaseModel):
    """Cross-turn persistent state.

    Primary state object for runtime turns and trace artifacts.
    """
    session_id: str
    task_id: Optional[str] = None
    authenticated_user_id: Optional[str] = None
    auth_method: Optional[str] = None
    active_user_identity: Dict[str, Any] = Field(default_factory=dict)
    messages: List[Message] = Field(default_factory=list)
    loaded_context: LoadedContext = Field(default_factory=LoadedContext)
    tool_results: List[ToolCallRecord] = Field(default_factory=list)
    write_locks: List[str] = Field(default_factory=list)
    audit_logs: List[Dict[str, Any]] = Field(default_factory=list)
    pending_action: Optional[PendingAction] = None
    current_action_candidate: Optional[ActionCandidate] = None
    termination_reason: Optional[str] = None

    confirmation_status: str = "not_required"
    step_durations: dict[str, float] = Field(default_factory=dict)

    steps: List[AgentStep] = Field(default_factory=list)

    def add_step(self, node: str, **detail: Any) -> None:
        self.steps.append(AgentStep(node=node, detail=detail))


class TurnContext(BaseModel):
    """Single-turn ephemeral bookkeeping.

    Recorded in trace artifacts but not persisted across turns.
    Phase 3's LLM agent loop will populate this.
    """
    steps: List[AgentStep] = Field(default_factory=list)
    step_durations: dict[str, float] = Field(default_factory=dict)
    llm_call_durations: list[dict] = Field(default_factory=list)
    llm_token_usage: Optional[Dict[str, Any]] = None
    loop_iterations: int = 0
    consecutive_tool_failures: int = 0
    termination: Optional[str] = None
    auto_load_count: int = 0
    premature_refusal_corrected_count: int = 0
    context_truncation_count: int = 0
    context_truncation_summary: Optional[str] = None
    prompt_injection_signal_count: int = 0
    prompt_injection_signals: List[Dict[str, Any]] = Field(default_factory=list)
    action_candidate_invoked: bool = False

    # ── Phase 6: replay harness ──
    llm_responses: list[dict] = Field(default_factory=list)

    def add_step(self, node: str, **detail: Any) -> None:
        self.steps.append(AgentStep(node=node, detail=detail))


class AgentTurnResult(BaseModel):
    """Return value from AgentLoop.run_turn()."""
    assistant_message: str
    turn: TurnContext
    pending_action_set: bool = False

# ── Phase 7: backward-compatible alias ──
ConversationState = SessionState
