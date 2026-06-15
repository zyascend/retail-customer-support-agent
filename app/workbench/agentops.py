from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

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
        reports: list[AgentOpsReportSummary] = []
        for path in self._report_paths():
            try:
                reports.append(self._read_report_summary(path))
            except WorkbenchAPIError as error:
                if error.code != "artifact_parse_error":
                    raise
        reports.sort(key=lambda item: item.created_at, reverse=True)
        return reports

    def get_report(self, run_id: str) -> AgentOpsReportDetail:
        path = self._report_path_for_run_id(run_id)
        if not path.exists():
            raise WorkbenchAPIError(
                code="report_not_found",
                message=f"Report '{run_id}' was not found.",
                status_code=404,
                details={"run_id": run_id},
            )
        return self._read_report_detail(path)

    def _report_paths(self) -> list[Path]:
        report_dir = self.artifact_dir / "reports"
        if not report_dir.exists():
            return []
        return sorted(report_dir.glob("*.json"))

    def _report_path_for_run_id(self, run_id: str) -> Path:
        if not run_id or Path(run_id).name != run_id or "/" in run_id or "\\" in run_id:
            raise WorkbenchAPIError(
                code="invalid_report_id",
                message="Unsupported report id.",
                status_code=400,
                details={"run_id": run_id},
            )
        report_dir = (self.artifact_dir / "reports").resolve()
        path = (report_dir / f"{run_id}.json").resolve()
        if path.parent != report_dir:
            raise WorkbenchAPIError(
                code="invalid_report_id",
                message="Unsupported report id.",
                status_code=400,
                details={"run_id": run_id},
            )
        return path

    def _read_report_summary(self, path: Path) -> AgentOpsReportSummary:
        payload = self._load_payload(path)
        baseline = self._baseline_metadata(payload, path)
        results = self._results(payload, path)
        pass_count = sum(1 for result in results if bool(result.get("passed")))
        fail_count = sum(1 for result in results if not bool(result.get("passed")))
        return AgentOpsReportSummary(
            run_id=self._required_string(payload, "eval_run_id", path),
            report_path=str(path),
            created_at=self._optional_string(payload, "created_at"),
            eval_backend=self._optional_string(payload, "eval_backend"),
            model=self._optional_string(payload, "model"),
            provider=self._string_from_mapping(baseline, "provider"),
            subset=self._string_from_mapping(baseline, "subset"),
            pass_count=pass_count,
            fail_count=fail_count,
            failure_case_count=fail_count,
        )

    def _read_report_detail(self, path: Path) -> AgentOpsReportDetail:
        payload = self._load_payload(path)
        baseline = self._baseline_metadata(payload, path)
        results = self._results(payload, path)
        return AgentOpsReportDetail(
            run_id=self._required_string(payload, "eval_run_id", path),
            report_path=str(path),
            created_at=self._optional_string(payload, "created_at"),
            eval_backend=self._optional_string(payload, "eval_backend"),
            model=self._optional_string(payload, "model"),
            provider=self._string_from_mapping(baseline, "provider"),
            subset=self._string_from_mapping(baseline, "subset"),
            baseline_metadata=baseline,
            metrics=self._mapping_field(payload, "metrics", path),
            cases=[self._read_case_summary(result, path) for result in results],
        )

    def _load_payload(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise self._artifact_parse_error(path, "Report artifact could not be parsed.") from exc
        if not isinstance(payload, dict):
            raise self._artifact_parse_error(path, "Report artifact must be a JSON object.")
        return payload

    def _baseline_metadata(self, payload: dict[str, Any], path: Path) -> dict[str, Any]:
        return self._mapping_field(payload, "baseline_metadata", path)

    def _results(self, payload: dict[str, Any], path: Path) -> list[dict[str, Any]]:
        results = payload.get("results", [])
        if not isinstance(results, list):
            raise self._artifact_parse_error(path, "Report field 'results' must be a list.")
        normalized: list[dict[str, Any]] = []
        for result in results:
            if not isinstance(result, dict):
                raise self._artifact_parse_error(
                    path, "Each report result entry must be a JSON object."
                )
            normalized.append(result)
        return normalized

    def _mapping_field(
        self, payload: dict[str, Any], field_name: str, path: Path
    ) -> dict[str, Any]:
        value = payload.get(field_name, {})
        if not isinstance(value, dict):
            raise self._artifact_parse_error(
                path, f"Report field '{field_name}' must be a JSON object."
            )
        return value

    def _required_string(
        self, payload: dict[str, Any], field_name: str, path: Path
    ) -> str:
        value = payload.get(field_name)
        if not isinstance(value, str) or not value:
            raise self._artifact_parse_error(
                path, f"Report field '{field_name}' is required."
            )
        return value

    def _required_result_string(
        self, payload: dict[str, Any], field_name: str, path: Path
    ) -> str:
        value = payload.get(field_name)
        if not isinstance(value, str) or not value:
            raise self._artifact_parse_error(
                path, f"Report result field '{field_name}' is required."
            )
        return value

    def _optional_string(self, payload: dict[str, Any], field_name: str) -> str:
        value = payload.get(field_name, "")
        return value if isinstance(value, str) else ""

    def _string_from_mapping(self, payload: dict[str, Any], field_name: str) -> str:
        value = payload.get(field_name, "")
        return value if isinstance(value, str) else ""

    def _read_case_summary(
        self, result: dict[str, Any], path: Path
    ) -> AgentOpsReportCaseSummary:
        try:
            return AgentOpsReportCaseSummary(
                case_id=self._required_result_string(result, "case_id", path),
                subset=result.get("subset"),
                passed=bool(result.get("passed")),
                failure_label=result.get("failure_label"),
                root_cause=result.get("failure_category"),
                trace_artifact_path=result.get("trace_artifact_path"),
            )
        except ValidationError as exc:
            raise self._artifact_parse_error(
                path, "Report result entry could not be parsed."
            ) from exc

    def _artifact_parse_error(self, path: Path, message: str) -> WorkbenchAPIError:
        return WorkbenchAPIError(
            code="artifact_parse_error",
            message=message,
            status_code=500,
            details={"report_path": str(path)},
        )
