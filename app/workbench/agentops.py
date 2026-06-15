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
