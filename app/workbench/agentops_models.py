from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentOpsReportSummary(BaseModel):
    run_id: str
    report_path: str
    created_at: str
    eval_backend: str
    model: str
    provider: str
    subset: str
    pass_count: int
    fail_count: int
    failure_case_count: int


class AgentOpsReportCaseSummary(BaseModel):
    case_id: str
    subset: Optional[str] = None
    passed: bool
    failure_label: Optional[str] = None
    root_cause: Optional[str] = None
    trace_artifact_path: Optional[str] = None


class AgentOpsReportDetail(BaseModel):
    run_id: str
    report_path: str
    created_at: str
    eval_backend: str
    model: str
    provider: str
    subset: str
    baseline_metadata: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    cases: list[AgentOpsReportCaseSummary] = Field(default_factory=list)


class AgentOpsTraceDetail(BaseModel):
    trace_id: str
    trace_artifact_path: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    turns: list[dict[str, Any]] = Field(default_factory=list)
    final_state: dict[str, Any] = Field(default_factory=dict)
    db_hashes: dict[str, Any] = Field(default_factory=dict)
    llm_responses: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class AgentOpsCaseDetail(BaseModel):
    case_id: str
    run_id: str
    subset: str | None = None
    passed: bool
    failure_label: str | None = None
    root_cause: str | None = None
    trace_artifact_path: str | None = None
    user_messages: list[str] = Field(default_factory=list)
    assistant_messages: list[str] = Field(default_factory=list)
    guard_context: list[dict[str, Any]] = Field(default_factory=list)
    db_assertion_diff: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    trace_summary: dict[str, Any] = Field(default_factory=dict)
    trace_detail: AgentOpsTraceDetail
