# Phase 11 Workbench AgentOps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only AgentOps workspace to Workbench so we can browse eval reports, jump into failed cases, and inspect trace timeline, guard context, and DB diffs without changing the existing Demo session flow.

**Architecture:** Keep Demo and AgentOps as separate surfaces. Demo continues to use `WorkbenchSession` and `WorkbenchSnapshot`; AgentOps adds a new read-only artifact service plus `/api/agentops/*` endpoints and separate frontend types/components. Timeline rendering stays reusable by mapping trace artifacts into the existing `TimelineEvent` shape.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, pytest, existing eval report / trace artifacts, React 19, TypeScript, Vite, existing Workbench CSS and timeline components.

---

## File Structure

### Backend files

- Create: `app/workbench/agentops_models.py`
  - Pydantic response models for report summaries, report detail, case detail, and trace detail.
- Create: `app/workbench/agentops.py`
  - Read-only artifact discovery, report loading, case detail assembly, and trace mapping.
- Modify: `app/workbench/api.py`
  - Register `/api/agentops/*` endpoints and inject the AgentOps service.
- Modify: `app/workbench/snapshot.py`
  - Reuse redaction helpers if needed from a shared import path, but keep Demo snapshot contract unchanged.
- Modify: `app/workbench/errors.py`
  - Reuse structured error payloads for AgentOps artifact errors.
- Create: `tests/test_workbench_agentops.py`
  - Unit tests for report discovery, case assembly, trace loading, and direct trace path opening.
- Modify: `tests/test_workbench_api.py`
  - API tests for all new AgentOps routes.

### Frontend files

- Create: `workbench/src/agentopsTypes.ts`
  - AgentOps-only TypeScript contracts.
- Create: `workbench/src/agentopsApi.ts`
  - Fetch helpers for `/api/agentops/*`.
- Create: `workbench/src/components/AgentOpsWorkspace.tsx`
  - Top-level AgentOps page state and layout.
- Create: `workbench/src/components/AgentOpsBrowser.tsx`
  - Report picker, filters, case list, and trace-path input.
- Create: `workbench/src/components/AgentOpsInspector.tsx`
  - LLM response, tool observation, guard context, DB diff, and trace metadata panels.
- Modify: `workbench/src/App.tsx`
  - Add `Demo` / `AgentOps` surface switch while preserving Demo behavior.
- Modify: `workbench/src/api.ts`
  - Keep Demo API isolated; no AgentOps types leak in.
- Modify: `workbench/src/types.ts`
  - Keep Demo contracts only, or reduce it to Demo-only exports.
- Modify: `workbench/src/labels.ts`
  - Add labels for AgentOps statuses and artifact errors.
- Modify: `workbench/src/styles.css`
  - Add top-level workspace tabs and AgentOps three-column layout.

---

### Task 1: Build Read-Only AgentOps Report Discovery

**Files:**
- Create: `app/workbench/agentops_models.py`
- Create: `app/workbench/agentops.py`
- Create: `tests/test_workbench_agentops.py`

- [x] **Step 1: Write the failing report discovery tests**

Create `tests/test_workbench_agentops.py` with these helpers and tests:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.workbench.agentops import AgentOpsService
from app.workbench.errors import WorkbenchAPIError


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class AgentOpsServiceTests(unittest.TestCase):
    def test_list_reports_returns_latest_report_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_json(
                artifact_dir / "reports" / "eval-run-a.json",
                {
                    "eval_run_id": "eval-run-a",
                    "created_at": "2026-06-15T01:00:00+00:00",
                    "eval_backend": "live",
                    "model": "deepseek-v4-flash",
                    "baseline_metadata": {"provider": "deepseek", "subset": "live_smoke_core"},
                    "results": [{"passed": True}, {"passed": False}],
                },
            )
            _write_json(
                artifact_dir / "reports" / "eval-run-b.json",
                {
                    "eval_run_id": "eval-run-b",
                    "created_at": "2026-06-15T02:00:00+00:00",
                    "eval_backend": "scripted_offline_demo",
                    "model": "deepseek-v4-flash",
                    "baseline_metadata": {"provider": "deepseek", "subset": "curated_mvp"},
                    "results": [{"passed": False}],
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)
            reports = service.list_reports()

        self.assertEqual([report.run_id for report in reports], ["eval-run-b", "eval-run-a"])
        self.assertEqual(reports[0].failure_case_count, 1)
        self.assertEqual(reports[0].fail_count, 1)
        self.assertEqual(reports[0].subset, "curated_mvp")

    def test_get_report_detail_raises_structured_error_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = AgentOpsService(artifact_dir=Path(tmp))

            with self.assertRaises(WorkbenchAPIError) as context:
                service.get_report("missing-run")

        self.assertEqual(context.exception.code, "report_not_found")
        self.assertEqual(context.exception.status_code, 404)
```

- [x] **Step 2: Run the report discovery tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_workbench_agentops.py::AgentOpsServiceTests::test_list_reports_returns_latest_report_summaries tests/test_workbench_agentops.py::AgentOpsServiceTests::test_get_report_detail_raises_structured_error_when_missing -q
```

Expected: FAIL because `AgentOpsService` and the response models do not exist yet.

- [x] **Step 3: Implement report summary models and service**

Create `app/workbench/agentops_models.py` with:

```python
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
```

Create the initial `AgentOpsService` in `app/workbench/agentops.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from app.workbench.agentops_models import (
    AgentOpsReportCaseSummary,
    AgentOpsReportDetail,
    AgentOpsReportSummary,
)
from app.workbench.errors import WorkbenchAPIError


class AgentOpsService:
    def __init__(self, *, artifact_dir: Path) -> None:
        self.artifact_dir = artifact_dir

    def list_reports(self) -> list[AgentOpsReportSummary]:
        reports = [self._read_report(path) for path in self._report_paths()]
        reports.sort(key=lambda item: item.created_at, reverse=True)
        return [
            AgentOpsReportSummary(
                run_id=report.run_id,
                report_path=report.report_path,
                created_at=report.created_at,
                eval_backend=report.eval_backend,
                model=report.model,
                provider=report.provider,
                subset=report.subset,
                pass_count=sum(1 for case in report.cases if case.passed),
                fail_count=sum(1 for case in report.cases if not case.passed),
                failure_case_count=sum(1 for case in report.cases if not case.passed),
            )
            for report in reports
        ]

    def get_report(self, run_id: str) -> AgentOpsReportDetail:
        path = self.artifact_dir / "reports" / f"{run_id}.json"
        if not path.exists():
            raise WorkbenchAPIError(
                code="report_not_found",
                message=f"Report '{run_id}' was not found.",
                status_code=404,
                details={"run_id": run_id},
            )
        return self._read_report(path)

    def _report_paths(self) -> list[Path]:
        report_dir = self.artifact_dir / "reports"
        if not report_dir.exists():
            return []
        return sorted(report_dir.glob("*.json"))

    def _read_report(self, path: Path) -> AgentOpsReportDetail:
        payload = json.loads(path.read_text(encoding="utf-8"))
        baseline = payload.get("baseline_metadata", {})
        results = payload.get("results", [])
        return AgentOpsReportDetail(
            run_id=payload["eval_run_id"],
            report_path=str(path),
            created_at=payload.get("created_at", ""),
            eval_backend=payload.get("eval_backend", ""),
            model=payload.get("model", ""),
            provider=baseline.get("provider", ""),
            subset=baseline.get("subset", ""),
            baseline_metadata=baseline,
            metrics=payload.get("metrics", {}),
            cases=[
                AgentOpsReportCaseSummary(
                    case_id=result["case_id"],
                    subset=result.get("subset"),
                    passed=bool(result.get("passed")),
                    failure_label=result.get("failure_label"),
                    root_cause=result.get("failure_category"),
                    trace_artifact_path=result.get("trace_artifact_path"),
                )
                for result in results
            ],
        )
```

- [x] **Step 4: Re-run the report discovery tests**

Run:

```bash
uv run python -m pytest tests/test_workbench_agentops.py::AgentOpsServiceTests::test_list_reports_returns_latest_report_summaries tests/test_workbench_agentops.py::AgentOpsServiceTests::test_get_report_detail_raises_structured_error_when_missing -q
```

Expected: PASS.

- [x] **Step 5: Commit the report discovery slice**

Run:

```bash
git add app/workbench/agentops.py app/workbench/agentops_models.py tests/test_workbench_agentops.py
git commit -m "feat: 添加 agentops report 发现服务"
```

Expected: commit succeeds with the new backend discovery layer only.

---

### Task 2: Assemble Case Detail And Trace Detail From Artifacts

**Files:**
- Modify: `app/workbench/agentops_models.py`
- Modify: `app/workbench/agentops.py`
- Modify: `tests/test_workbench_agentops.py`

- [x] **Step 1: Write the failing case and trace detail tests**

Extend `tests/test_workbench_agentops.py` with:

```python
    def test_get_case_detail_merges_report_and_trace_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            trace_path = artifact_dir / "traces" / "eval-run-a" / "runs" / "case-a.json"
            _write_json(
                artifact_dir / "reports" / "eval-run-a.json",
                {
                    "eval_run_id": "eval-run-a",
                    "created_at": "2026-06-15T01:00:00+00:00",
                    "eval_backend": "live",
                    "model": "deepseek-v4-flash",
                    "baseline_metadata": {"provider": "deepseek", "subset": "live_smoke_core"},
                    "results": [
                        {
                            "case_id": "case-a",
                            "passed": False,
                            "failure_label": "wrong_tool",
                            "failure_category": "prompt_gap",
                            "trace_artifact_path": str(trace_path),
                            "expected_actual_diff": {"order_status": {"expected": "cancelled", "actual": "pending"}},
                        }
                    ],
                },
            )
            _write_json(
                trace_path,
                {
                    "run_id": "case-a",
                    "messages": [
                        {"role": "user", "content": "cancel order #W1"},
                        {"role": "assistant", "content": "I need confirmation."},
                    ],
                    "metadata": {
                        "llm_responses": [
                            {
                                "assistant_content": "",
                                "finish_reason": "tool_calls",
                                "token_usage": {"total_tokens": 42},
                                "tool_calls": [
                                    {
                                        "tool_name": "cancel_pending_order",
                                        "arguments": {"order_id": "#W1"},
                                        "id": "call_1",
                                        "raw_arguments": "{\"order_id\":\"#W1\"}",
                                    }
                                ],
                            }
                        ]
                    },
                    "tool_calls": [
                        {
                            "tool_name": "cancel_pending_order",
                            "arguments": {"order_id": "#W1"},
                            "tool_kind": "write",
                            "status": "blocked",
                            "error": "explicit_confirmation_required",
                            "block_context": {"confirmation_required": True, "summary": "Cancel order #W1."},
                            "observation": {"block_reason": "explicit_confirmation_required"},
                        }
                    ],
                    "steps": [
                        {
                            "node": "write_action_guard",
                            "status": "ok",
                            "detail": {
                                "tool_name": "cancel_pending_order",
                                "status": "blocked",
                                "block_reason": "explicit_confirmation_required",
                                "block_context": {"confirmation_required": True, "summary": "Cancel order #W1."},
                            },
                        }
                    ],
                    "final_state": {
                        "auth_method": "email",
                        "authenticated_user_id": "user-1",
                        "compat": {"current_intent": "unknown", "slots": {}, "policy_decision": None},
                        "confirmation_status": "required",
                        "pending_action": {"action_name": "cancel_pending_order"},
                        "session_id": "case-a",
                        "task_id": "case-a",
                        "termination_reason": "awaiting_confirmation",
                        "write_locks": [],
                    },
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)
            detail = service.get_case("eval-run-a", "case-a")

        self.assertEqual(detail.failure_label, "wrong_tool")
        self.assertEqual(detail.root_cause, "prompt_gap")
        self.assertEqual(detail.guard_context, [{"confirmation_required": True, "summary": "Cancel order #W1."}])
        self.assertEqual(detail.db_assertion_diff["order_status"]["actual"], "pending")

    def test_get_trace_by_path_returns_timeline_and_redacted_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            trace_path = artifact_dir / "traces" / "trace-a.json"
            _write_json(
                trace_path,
                {
                    "run_id": "trace-a",
                    "messages": [{"role": "user", "content": "email me at alex@example.com"}],
                    "metadata": {"llm_responses": []},
                    "tool_calls": [],
                    "steps": [],
                    "final_state": {},
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)
            detail = service.get_trace_by_path(str(trace_path))

        self.assertEqual(detail.trace_id, "trace-a")
        self.assertEqual(detail.timeline[0]["kind"], "message")
        self.assertEqual(detail.turns[0]["messages"][0]["content"], "email me at [redacted-email]")
```

- [x] **Step 2: Run the new tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_workbench_agentops.py::AgentOpsServiceTests::test_get_case_detail_merges_report_and_trace_signals tests/test_workbench_agentops.py::AgentOpsServiceTests::test_get_trace_by_path_returns_timeline_and_redacted_messages -q
```

Expected: FAIL because `get_case()` / `get_trace_by_path()` and the case/trace models do not exist yet.

- [x] **Step 3: Implement case detail and trace detail models**

Extend `app/workbench/agentops_models.py` with:

```python
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
```

- [x] **Step 4: Implement case and trace assembly**

Add to `app/workbench/agentops.py`:

```python
import json
from pathlib import Path
from typing import Any

from app.agent.models import Message, SessionState, ToolCallRecord
from app.workbench.snapshot import build_timeline, redact_value


    def get_case(self, run_id: str, case_id: str) -> AgentOpsCaseDetail:
        report = self.get_report(run_id)
        case = next((item for item in report.cases if item.case_id == case_id), None)
        if case is None:
            raise WorkbenchAPIError(
                code="case_not_found",
                message=f"Case '{case_id}' was not found in report '{run_id}'.",
                status_code=404,
                details={"run_id": run_id, "case_id": case_id},
            )
        result_payload = self._report_result(run_id, case_id)
        trace = self.get_trace_by_path(case.trace_artifact_path or "")
        return AgentOpsCaseDetail(
            case_id=case.case_id,
            run_id=run_id,
            subset=case.subset,
            passed=case.passed,
            failure_label=case.failure_label,
            root_cause=case.root_cause,
            trace_artifact_path=case.trace_artifact_path,
            user_messages=[
                item["content"]
                for turn in trace.turns
                for item in turn["messages"]
                if item["role"] == "user"
            ],
            assistant_messages=[
                item["content"]
                for turn in trace.turns
                for item in turn["messages"]
                if item["role"] == "assistant"
            ],
            guard_context=[
                call.get("block_context", {})
                for call in trace.tool_calls
                if call.get("block_context")
            ],
            db_assertion_diff=result_payload.get("expected_actual_diff", {}),
            tool_calls=trace.tool_calls,
            trace_summary={
                "message_count": sum(len(turn["messages"]) for turn in trace.turns),
                "llm_response_count": len(trace.llm_responses),
                "tool_call_count": len(trace.tool_calls),
                "guard_block_count": sum(1 for call in trace.tool_calls if call.get("status") == "blocked"),
            },
        )

    def get_trace_by_path(self, raw_path: str) -> AgentOpsTraceDetail:
        if not raw_path:
            raise WorkbenchAPIError(
                code="invalid_trace_path",
                message="Trace path is required.",
                status_code=400,
            )
        path = Path(raw_path)
        if not path.exists():
            raise WorkbenchAPIError(
                code="trace_not_found",
                message=f"Trace '{raw_path}' was not found.",
                status_code=404,
                details={"trace_path": raw_path},
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        messages = redact_value(payload.get("messages", []))
        tool_calls = redact_value(payload.get("tool_calls", []))
        trace_state = SessionState(session_id=str(payload.get("run_id", path.stem)))
        for message in payload.get("messages", []):
            trace_state.messages.append(Message(**message))
        for step in payload.get("steps", []):
            trace_state.add_step(step["node"], status=step.get("status"), detail=step.get("detail", {}))
        for call in payload.get("tool_calls", []):
            trace_state.tool_results.append(ToolCallRecord(**call))
        timeline = build_timeline(trace_state)
        return AgentOpsTraceDetail(
            trace_id=str(payload.get("run_id") or path.stem),
            trace_artifact_path=str(path),
            metadata=redact_value(payload.get("metadata", {})),
            timeline=timeline,
            turns=[{"index": 0, "messages": messages, "llm_responses": redact_value(payload.get("metadata", {}).get("llm_responses", []))}],
            final_state=redact_value(payload.get("final_state", {})),
            db_hashes={
                "initial_db_hash": payload.get("metadata", {}).get("initial_db_hash"),
                "final_db_hash": payload.get("metadata", {}).get("final_db_hash"),
            },
            llm_responses=redact_value(payload.get("metadata", {}).get("llm_responses", [])),
            tool_calls=tool_calls,
        )
```

Also add a private helper to reread the raw report result:

```python
    def _report_result(self, run_id: str, case_id: str) -> dict[str, Any]:
        path = self.artifact_dir / "reports" / f"{run_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        for result in payload.get("results", []):
            if result.get("case_id") == case_id:
                return result
        raise WorkbenchAPIError(
            code="case_not_found",
            message=f"Case '{case_id}' was not found in report '{run_id}'.",
            status_code=404,
            details={"run_id": run_id, "case_id": case_id},
        )
```

- [x] **Step 5: Re-run the case and trace tests**

Run:

```bash
uv run python -m pytest tests/test_workbench_agentops.py::AgentOpsServiceTests::test_get_case_detail_merges_report_and_trace_signals tests/test_workbench_agentops.py::AgentOpsServiceTests::test_get_trace_by_path_returns_timeline_and_redacted_messages -q
```

Expected: PASS.

- [x] **Step 6: Commit the trace assembly slice**

Run:

```bash
git add app/workbench/agentops.py app/workbench/agentops_models.py tests/test_workbench_agentops.py
git commit -m "feat: 添加 agentops case 和 trace 视图"
```

Expected: commit succeeds with read-only case and trace assembly.

---

### Task 3: Expose AgentOps FastAPI Endpoints

**Files:**
- Modify: `app/workbench/api.py`
- Modify: `tests/test_workbench_api.py`

- [x] **Step 1: Write failing AgentOps API tests**

Add these tests to `tests/test_workbench_api.py`:

```python
    def test_agentops_report_routes_return_report_and_case_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "reports"
            trace_path = Path(tmp) / "traces" / "eval-run-a" / "runs" / "case-a.json"
            report_dir.mkdir(parents=True, exist_ok=True)
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            report_dir.joinpath("eval-run-a.json").write_text(
                json.dumps(
                    {
                        "eval_run_id": "eval-run-a",
                        "created_at": "2026-06-15T01:00:00+00:00",
                        "eval_backend": "live",
                        "model": "deepseek-v4-flash",
                        "baseline_metadata": {"provider": "deepseek", "subset": "live_smoke_core"},
                        "results": [
                            {
                                "case_id": "case-a",
                                "passed": False,
                                "failure_label": "wrong_tool",
                                "failure_category": "prompt_gap",
                                "trace_artifact_path": str(trace_path),
                                "expected_actual_diff": {"order_status": {"expected": "cancelled", "actual": "pending"}},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            trace_path.write_text(
                json.dumps(
                    {
                        "run_id": "case-a",
                        "messages": [{"role": "user", "content": "cancel order #W1"}],
                        "metadata": {"llm_responses": []},
                        "tool_calls": [],
                        "steps": [],
                        "final_state": {},
                    }
                ),
                encoding="utf-8",
            )
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            reports = client.get("/api/agentops/reports")
            report = client.get("/api/agentops/reports/eval-run-a")
            case = client.get("/api/agentops/cases/eval-run-a/case-a")
            trace = client.get("/api/agentops/traces", params={"path": str(trace_path)})

        self.assertEqual(reports.status_code, 200)
        self.assertEqual(report.status_code, 200)
        self.assertEqual(case.status_code, 200)
        self.assertEqual(trace.status_code, 200)
        self.assertEqual(report.json()["run_id"], "eval-run-a")
        self.assertEqual(case.json()["root_cause"], "prompt_gap")
        self.assertEqual(trace.json()["trace_id"], "case-a")

    def test_agentops_missing_trace_returns_structured_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.get("/api/agentops/traces", params={"path": "/tmp/missing-trace.json"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "trace_not_found")
```

- [x] **Step 2: Run the AgentOps API tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_workbench_api.py::WorkbenchAPITests::test_agentops_report_routes_return_report_and_case_details tests/test_workbench_api.py::WorkbenchAPITests::test_agentops_missing_trace_returns_structured_error -q
```

Expected: FAIL because `/api/agentops/*` routes are not registered.

- [x] **Step 3: Implement the FastAPI endpoints**

Update `app/workbench/api.py`:

```python
from fastapi import FastAPI, Query

from app.workbench.agentops import AgentOpsService


def create_app(config: Optional[AppConfig] = None) -> FastAPI:
    resolved_config = config or resolve_config(artifact_dir="artifacts/phase4")
    manager = WorkbenchSessionManager(resolved_config)
    agentops = AgentOpsService(artifact_dir=resolved_config.run_artifact_dir.parent)
    app = FastAPI(title="Retail Agent Workbench API")
    app.state.config = resolved_config
    app.state.manager = manager
    app.state.agentops = agentops

    @app.get("/api/agentops/reports")
    def list_agentops_reports() -> list[dict[str, Any]]:
        return [report.model_dump() for report in agentops.list_reports()]

    @app.get("/api/agentops/reports/{run_id}")
    def get_agentops_report(run_id: str) -> dict[str, Any]:
        return agentops.get_report(run_id).model_dump()

    @app.get("/api/agentops/cases/{run_id}/{case_id}")
    def get_agentops_case(run_id: str, case_id: str) -> dict[str, Any]:
        return agentops.get_case(run_id, case_id).model_dump()

    @app.get("/api/agentops/traces/{trace_id}")
    def get_agentops_trace(trace_id: str) -> dict[str, Any]:
        return agentops.get_trace(trace_id).model_dump()

    @app.get("/api/agentops/traces")
    def get_agentops_trace_by_path(path: str = Query(...)) -> dict[str, Any]:
        return agentops.get_trace_by_path(path).model_dump()
```

Add `get_trace()` to `AgentOpsService` in `app/workbench/agentops.py`:

```python
    def get_trace(self, trace_id: str) -> AgentOpsTraceDetail:
        matches = sorted(self.artifact_dir.glob(f"traces/**/{trace_id}.json"))
        if not matches:
            raise WorkbenchAPIError(
                code="trace_not_found",
                message=f"Trace '{trace_id}' was not found.",
                status_code=404,
                details={"trace_id": trace_id},
            )
        return self.get_trace_by_path(str(matches[0]))
```

- [x] **Step 4: Re-run the AgentOps API tests**

Run:

```bash
uv run python -m pytest tests/test_workbench_api.py::WorkbenchAPITests::test_agentops_report_routes_return_report_and_case_details tests/test_workbench_api.py::WorkbenchAPITests::test_agentops_missing_trace_returns_structured_error -q
```

Expected: PASS.

- [x] **Step 5: Commit the API layer**

Run:

```bash
git add app/workbench/api.py app/workbench/agentops.py tests/test_workbench_api.py
git commit -m "feat: 暴露 agentops workbench 接口"
```

Expected: commit succeeds with AgentOps API routes in place.

---

### Task 4: Split The Workbench Shell Into Demo And AgentOps Surfaces

**Files:**
- Create: `workbench/src/agentopsTypes.ts`
- Create: `workbench/src/agentopsApi.ts`
- Modify: `workbench/src/App.tsx`
- Modify: `workbench/src/types.ts`
- Modify: `workbench/src/labels.ts`

- [x] **Step 1: Write the failing TypeScript surface split by importing new AgentOps types**

Create `workbench/src/agentopsTypes.ts`:

```ts
export interface AgentOpsReportSummary {
  run_id: string;
  report_path: string;
  created_at: string;
  eval_backend: string;
  model: string;
  provider: string;
  subset: string;
  pass_count: number;
  fail_count: number;
  failure_case_count: number;
}

export interface AgentOpsCaseSummary {
  case_id: string;
  subset: string | null;
  passed: boolean;
  failure_label: string | null;
  root_cause: string | null;
  trace_artifact_path: string | null;
}

export interface AgentOpsReportDetail extends AgentOpsReportSummary {
  baseline_metadata: Record<string, unknown>;
  metrics: Record<string, unknown>;
  cases: AgentOpsCaseSummary[];
}

export interface AgentOpsCaseDetail {
  case_id: string;
  run_id: string;
  subset: string | null;
  passed: boolean;
  failure_label: string | null;
  root_cause: string | null;
  trace_artifact_path: string | null;
  user_messages: string[];
  assistant_messages: string[];
  guard_context: Array<Record<string, unknown>>;
  db_assertion_diff: Record<string, unknown>;
  tool_calls: Array<Record<string, unknown>>;
  trace_summary: Record<string, unknown>;
}

export interface AgentOpsTraceDetail {
  trace_id: string;
  trace_artifact_path: string;
  metadata: Record<string, unknown>;
  timeline: import("./types").TimelineEvent[];
  turns: Array<Record<string, unknown>>;
  final_state: Record<string, unknown>;
  db_hashes: Record<string, unknown>;
  llm_responses: Array<Record<string, unknown>>;
  tool_calls: Array<Record<string, unknown>>;
}
```

Create `workbench/src/agentopsApi.ts`:

```ts
import type {
  AgentOpsCaseDetail,
  AgentOpsReportDetail,
  AgentOpsReportSummary,
  AgentOpsTraceDetail,
} from "./agentopsTypes";

import { requestJson } from "./api";

export function listAgentOpsReports(): Promise<AgentOpsReportSummary[]> {
  return requestJson<AgentOpsReportSummary[]>("/api/agentops/reports");
}

export function getAgentOpsReport(runId: string): Promise<AgentOpsReportDetail> {
  return requestJson<AgentOpsReportDetail>(`/api/agentops/reports/${runId}`);
}

export function getAgentOpsCase(runId: string, caseId: string): Promise<AgentOpsCaseDetail> {
  return requestJson<AgentOpsCaseDetail>(`/api/agentops/cases/${runId}/${caseId}`);
}

export function getAgentOpsTraceByPath(path: string): Promise<AgentOpsTraceDetail> {
  return requestJson<AgentOpsTraceDetail>(`/api/agentops/traces?path=${encodeURIComponent(path)}`);
}
```

Then export the generic request helper from `workbench/src/api.ts`:

```ts
export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  // existing request() body moved here unchanged
}
```

- [x] **Step 2: Verify the new imports fail until `App.tsx` is updated**

Run:

```bash
npm --prefix workbench run build
```

Expected: FAIL because the new files are not wired into the React app yet.

- [x] **Step 3: Add top-level surface switching to `App.tsx`**

Update `workbench/src/App.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";

import { AgentOpsWorkspace } from "./components/AgentOpsWorkspace";
import { modeLabel } from "./labels";
import type { WorkbenchConfig, WorkbenchMode, WorkbenchSnapshot } from "./types";

type WorkbenchSurface = "demo" | "agentops";

export function App() {
  const [surface, setSurface] = useState<WorkbenchSurface>("demo");
  // existing Demo state remains unchanged

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>零售客服工作台</h1>
          <p>{surface === "demo" ? "零售客服 Agent 演示面板" : "零售客服 AgentOps 调试台"}</p>
        </div>
        <div className="topbar-status">
          <div className="workspace-tabs" aria-label="工作面切换">
            <button
              className={surface === "demo" ? "active" : ""}
              onClick={() => setSurface("demo")}
              type="button"
            >
              Demo
            </button>
            <button
              className={surface === "agentops" ? "active" : ""}
              onClick={() => setSurface("agentops")}
              type="button"
            >
              AgentOps
            </button>
          </div>
          {surface === "demo" ? (
            <>
              <span className="case-label">{selectedCase?.title || "正在加载案例"}</span>
              <span className="mode-pill">{modeLabel(snapshot?.mode || config?.default_mode)}</span>
            </>
          ) : null}
        </div>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}

      {surface === "demo" ? (
        // existing dashboard-grid unchanged
      ) : (
        <AgentOpsWorkspace />
      )}
    </main>
  );
}
```

Add AgentOps labels in `workbench/src/labels.ts`:

```ts
const ERROR_LABELS: Record<string, string> = {
  // existing labels...
  report_not_found: "评估报告不存在",
  trace_not_found: "Trace 不存在",
  invalid_trace_path: "Trace 路径无效",
  artifact_parse_error: "Artifact 解析失败",
};
```

- [x] **Step 4: Re-run the frontend build**

Run:

```bash
npm --prefix workbench run build
```

Expected: FAIL because `AgentOpsWorkspace` still does not exist, but the shell/type split compiles far enough to isolate the missing UI component.

- [x] **Step 5: Commit the shell split**

Run:

```bash
git add workbench/src/App.tsx workbench/src/api.ts workbench/src/agentopsApi.ts workbench/src/agentopsTypes.ts workbench/src/labels.ts
git commit -m "feat: 拆分 workbench demo 与 agentops 工作面"
```

Expected: commit succeeds once the surface split and typed clients compile together with the next task.

---

### Task 5: Build The AgentOps Browser And Inspector UI

**Files:**
- Create: `workbench/src/components/AgentOpsWorkspace.tsx`
- Create: `workbench/src/components/AgentOpsBrowser.tsx`
- Create: `workbench/src/components/AgentOpsInspector.tsx`
- Modify: `workbench/src/styles.css`

- [x] **Step 1: Create the AgentOps workspace component with failing fetch flow**

Create `workbench/src/components/AgentOpsWorkspace.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react";

import { getAgentOpsCase, getAgentOpsReport, getAgentOpsTraceByPath, listAgentOpsReports } from "../agentopsApi";
import type { AgentOpsCaseDetail, AgentOpsReportDetail, AgentOpsReportSummary, AgentOpsTraceDetail } from "../agentopsTypes";
import { AgentOpsBrowser } from "./AgentOpsBrowser";
import { AgentOpsInspector } from "./AgentOpsInspector";
import { Timeline } from "./Timeline";

export function AgentOpsWorkspace() {
  const [reports, setReports] = useState<AgentOpsReportSummary[]>([]);
  const [selectedReport, setSelectedReport] = useState<AgentOpsReportDetail | null>(null);
  const [selectedCase, setSelectedCase] = useState<AgentOpsCaseDetail | null>(null);
  const [selectedTrace, setSelectedTrace] = useState<AgentOpsTraceDetail | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [failureOnly, setFailureOnly] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listAgentOpsReports()
      .then(setReports)
      .catch((exc: Error) => setError(exc.message));
  }, []);

  async function handleSelectReport(runId: string) {
    const report = await getAgentOpsReport(runId);
    setSelectedReport(report);
    setSelectedCase(null);
    setSelectedTrace(null);
    setSelectedEventId(null);
  }

  async function handleSelectCase(caseId: string) {
    if (!selectedReport) {
      return;
    }
    const detail = await getAgentOpsCase(selectedReport.run_id, caseId);
    setSelectedCase(detail);
    if (detail.trace_artifact_path) {
      const trace = await getAgentOpsTraceByPath(detail.trace_artifact_path);
      setSelectedTrace(trace);
      setSelectedEventId(trace.timeline.at(-1)?.id || null);
    }
  }

  async function handleOpenTracePath(path: string) {
    const trace = await getAgentOpsTraceByPath(path);
    setSelectedTrace(trace);
    setSelectedEventId(trace.timeline.at(-1)?.id || null);
  }

  const visibleCases = useMemo(() => {
    if (!selectedReport) {
      return [];
    }
    return selectedReport.cases.filter((item) => (failureOnly ? !item.passed : true));
  }, [failureOnly, selectedReport]);

  const activeEvent =
    selectedTrace?.timeline.find((event) => event.id === selectedEventId) ||
    selectedTrace?.timeline.at(-1) ||
    null;

  return (
    <section className="agentops-grid" aria-label="AgentOps 调试台">
      <AgentOpsBrowser
        error={error}
        reports={reports}
        selectedReport={selectedReport}
        visibleCases={visibleCases}
        onFailureOnlyChange={setFailureOnly}
        onOpenTracePath={handleOpenTracePath}
        onSelectCase={handleSelectCase}
        onSelectReport={handleSelectReport}
      />
      <section className="panel timeline-panel" aria-label="Trace 时间线">
        <div className="panel-header">
          <div>
            <div className="panel-kicker">Trace</div>
            <h2>{selectedTrace?.trace_id || "尚未打开 Trace"}</h2>
          </div>
        </div>
        <Timeline
          events={selectedTrace?.timeline || []}
          selectedEventId={selectedEventId}
          onSelectEvent={setSelectedEventId}
        />
      </section>
      <AgentOpsInspector
        event={activeEvent}
        selectedCase={selectedCase}
        trace={selectedTrace}
      />
    </section>
  );
}
```

- [x] **Step 2: Create the browser and inspector components**

Create `workbench/src/components/AgentOpsBrowser.tsx`:

```tsx
import { useState } from "react";

import type { AgentOpsReportDetail, AgentOpsReportSummary } from "../agentopsTypes";

interface AgentOpsBrowserProps {
  error: string | null;
  reports: AgentOpsReportSummary[];
  selectedReport: AgentOpsReportDetail | null;
  visibleCases: AgentOpsReportDetail["cases"];
  onFailureOnlyChange: (next: boolean) => void;
  onOpenTracePath: (path: string) => Promise<void>;
  onSelectCase: (caseId: string) => Promise<void>;
  onSelectReport: (runId: string) => Promise<void>;
}

export function AgentOpsBrowser({
  error,
  reports,
  selectedReport,
  visibleCases,
  onFailureOnlyChange,
  onOpenTracePath,
  onSelectCase,
  onSelectReport,
}: AgentOpsBrowserProps) {
  const [tracePath, setTracePath] = useState("");

  return (
    <section className="panel agentops-browser" aria-label="报告与案例浏览">
      <div className="panel-header">
        <div>
          <div className="panel-kicker">AgentOps</div>
          <h2>报告与案例</h2>
        </div>
      </div>

      {error ? <div className="error-banner inline-error">{error}</div> : null}

      <label className="field">
        <span>评估报告</span>
        <select
          onChange={(event) => onSelectReport(event.target.value)}
          value={selectedReport?.run_id || ""}
        >
          <option value="" disabled>
            选择报告
          </option>
          {reports.map((report) => (
            <option key={report.run_id} value={report.run_id}>
              {report.run_id} · {report.subset} · fail {report.fail_count}
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>直接打开 Trace</span>
        <textarea
          rows={3}
          value={tracePath}
          onChange={(event) => setTracePath(event.target.value)}
          placeholder="粘贴 trace artifact 绝对路径..."
        />
      </label>
      <button className="button" onClick={() => onOpenTracePath(tracePath)} type="button">
        打开 Trace
      </button>

      <label className="checkbox-row">
        <input defaultChecked type="checkbox" onChange={(event) => onFailureOnlyChange(event.target.checked)} />
        <span>仅显示失败案例</span>
      </label>

      <div className="case-list">
        {visibleCases.map((item) => (
          <button
            key={item.case_id}
            className={"case-list-item" + (item.passed ? "" : " is-failing")}
            onClick={() => onSelectCase(item.case_id)}
            type="button"
          >
            <strong>{item.case_id}</strong>
            <span>{item.root_cause || item.failure_label || "passed"}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
```

Create `workbench/src/components/AgentOpsInspector.tsx`:

```tsx
import type { AgentOpsCaseDetail, AgentOpsTraceDetail } from "../agentopsTypes";
import type { TimelineEvent } from "../types";

interface AgentOpsInspectorProps {
  event: TimelineEvent | null;
  selectedCase: AgentOpsCaseDetail | null;
  trace: AgentOpsTraceDetail | null;
}

export function AgentOpsInspector({ event, selectedCase, trace }: AgentOpsInspectorProps) {
  const activeToolCall =
    typeof event?.source_index === "number" && event.kind === "tool_call"
      ? trace?.tool_calls[event.source_index] || null
      : null;

  return (
    <section className="panel inspector-panel" aria-label="AgentOps 检查器">
      <div className="panel-header">
        <div>
          <div className="panel-kicker">Inspector</div>
          <h2>{trace?.trace_id || "调试详情"}</h2>
        </div>
      </div>

      <div className="json-section">
        <div className="section-label">LLM Response</div>
        <pre>{JSON.stringify(trace?.llm_responses ?? [], null, 2)}</pre>
      </div>
      <div className="json-section">
        <div className="section-label">Tool Observation</div>
        <pre>{JSON.stringify(activeToolCall ?? null, null, 2)}</pre>
      </div>
      <div className="json-section">
        <div className="section-label">Guard Context</div>
        <pre>{JSON.stringify(selectedCase?.guard_context ?? [], null, 2)}</pre>
      </div>
      <div className="json-section">
        <div className="section-label">DB Diff</div>
        <pre>{JSON.stringify(selectedCase?.db_assertion_diff ?? {}, null, 2)}</pre>
      </div>
      <div className="json-section">
        <div className="section-label">Trace Metadata</div>
        <pre>{JSON.stringify(trace?.metadata ?? {}, null, 2)}</pre>
      </div>
    </section>
  );
}
```

- [x] **Step 3: Add AgentOps layout styles**

Append to `workbench/src/styles.css`:

```css
.workspace-tabs {
  display: inline-grid;
  grid-template-columns: 1fr 1fr;
  overflow: hidden;
  border: 1px solid #c9d2de;
  border-radius: 999px;
  background: #eef3f8;
}

.workspace-tabs button {
  border: 0;
  background: transparent;
  color: #475467;
  padding: 7px 14px;
  font-size: 13px;
  font-weight: 800;
}

.workspace-tabs button.active {
  background: #172033;
  color: #ffffff;
}

.agentops-grid {
  display: grid;
  grid-template-columns: minmax(280px, 320px) minmax(360px, 1fr) minmax(320px, 420px);
  gap: 12px;
  padding: 12px;
}

.agentops-browser {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.checkbox-row {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #344154;
  font-size: 13px;
  font-weight: 700;
}

.case-list {
  display: grid;
  gap: 8px;
  overflow: auto;
}

.case-list-item {
  display: grid;
  gap: 4px;
  border: 1px solid #d9e1ec;
  border-radius: 8px;
  background: #ffffff;
  padding: 10px;
  text-align: left;
}

.case-list-item.is-failing {
  border-color: #e3b0b0;
  background: #fff7f7;
}

.inline-error {
  margin: 0;
}

@media (max-width: 1100px) {
  .agentops-grid,
  .dashboard-grid {
    grid-template-columns: 1fr;
    grid-template-areas: none;
  }

  .run-control,
  .business-state,
  .conversation-panel,
  .timeline-panel,
  .inspector-panel {
    grid-area: auto;
  }
}
```

- [x] **Step 4: Build the frontend and verify it passes**

Run:

```bash
npm --prefix workbench run build
npm --prefix workbench run check:i18n
```

Expected:

- `build`: PASS with successful TypeScript + Vite output.
- `check:i18n`: PASS with no English UI regressions.

- [x] **Step 5: Run backend verification for the full Workbench slice**

Run:

```bash
uv run python -m pytest tests/test_workbench_agentops.py tests/test_workbench_api.py tests/test_workbench_snapshot.py tests/test_workbench_session.py -q
uv run ruff check .
```

Expected:

- All listed Workbench backend tests PASS.
- `ruff check .` returns `All checks passed!`

- [x] **Step 6: Commit the AgentOps UI**

Run:

```bash
git add workbench/src/App.tsx workbench/src/agentopsApi.ts workbench/src/agentopsTypes.ts workbench/src/components/AgentOpsBrowser.tsx workbench/src/components/AgentOpsInspector.tsx workbench/src/components/AgentOpsWorkspace.tsx workbench/src/labels.ts workbench/src/styles.css
git commit -m "feat: 添加 workbench agentops 调试界面"
```

Expected: commit succeeds with the new AgentOps browser and inspector.

---

### Task 6: End-To-End Manual Verification

**Files:**
- No code changes expected unless verification reveals a bug.

- [x] **Step 1: Start the Workbench API**

Run:

```bash
uv run python -m uvicorn app.workbench.api:create_app --factory --reload --port 8000
```

Expected: local API starts without import errors.

- [x] **Step 2: Start the frontend**

Run in a second terminal:

```bash
npm --prefix workbench run dev
```

Expected: Vite serves the app on `http://127.0.0.1:5173`.

- [x] **Step 3: Verify the Demo surface did not regress**

Manual checks:

1. Open the default `Demo` tab.
2. Select `cancel_pending_order`.
3. Click `单步执行`, then `运行全部`.
4. Confirm pending action / timeline / inspector still behave as before.

- [x] **Step 4: Verify the AgentOps failure workflow**

Manual checks:

1. Switch to `AgentOps`.
2. Select a report with at least one failed case.
3. Leave `仅显示失败案例` enabled.
4. Click a failed case.
5. Confirm the timeline loads.
6. Click the blocked or failing tool event.
7. Confirm `Guard Context` and `DB Diff` are visible in the right-hand inspector.

- [x] **Step 5: Verify direct trace-path opening**

Manual checks:

1. Copy a known `trace_artifact_path` from the selected case.
2. Paste it into `直接打开 Trace`.
3. Click `打开 Trace`.
4. Confirm the timeline and inspector refresh to that trace.

- [x] **Step 6: Commit only if fixes were needed**

If manual verification required no extra code changes, do not create an additional commit. If a fix was required, stage only the fix and commit it with a focused message such as:

```bash
git add <changed-files>
git commit -m "fix: 修正 agentops trace 检查器显示"
```

---

## Self-Review

### Spec coverage

- `Demo` / `AgentOps` 双工作面：Task 4, Task 5.
- 只读 `agentops` API：Task 1, Task 2, Task 3.
- report -> failed case -> trace workflow：Task 3, Task 5, Task 6.
- Inspector 分区展示 `LLM Response`、`Tool Observation`、`Guard Context`、`DB Diff`：Task 5.
- 直接按 trace 路径打开：Task 2, Task 3, Task 5, Task 6.
- 保持 Demo contract 不变：Task 5 backend regression run + Task 6 Demo manual verification.

### Placeholder scan

- No `TBD`, `TODO`, “similar to Task N”, or unspecified commands remain.
- Every code-changing step includes exact file paths and concrete code snippets.

### Type consistency

- Backend route names and frontend client names use the same nouns: `reports`, `cases`, `traces`.
- AgentOps types stay separate from `WorkbenchSnapshot`.
- Timeline rendering reuses the existing `TimelineEvent` shape rather than inventing a second timeline format.
