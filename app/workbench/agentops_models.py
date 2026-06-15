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
