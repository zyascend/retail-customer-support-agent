from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.agent.models import AgentStep, Message, SessionState, ToolCallRecord
from app.workbench.agentops_models import (
    AgentOpsCaseDetail,
    AgentOpsReportCaseSummary,
    AgentOpsReportDetail,
    AgentOpsReportSummary,
    AgentOpsTraceDetail,
)
from app.workbench.errors import WorkbenchAPIError
from app.workbench.snapshot import build_timeline, redact_value


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
                "guard_block_count": sum(
                    1 for call in trace.tool_calls if call.get("status") == "blocked"
                ),
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
        if not path.is_absolute():
            raise WorkbenchAPIError(
                code="invalid_trace_path",
                message="Trace path must be absolute.",
                status_code=400,
                details={"trace_path": raw_path},
            )
        if not path.exists():
            raise WorkbenchAPIError(
                code="trace_not_found",
                message=f"Trace '{raw_path}' was not found.",
                status_code=404,
                details={"trace_path": raw_path},
            )

        payload = self._load_trace_payload(path)
        trace_state = SessionState(session_id=str(payload.get("run_id", path.stem)))
        trace_state.messages.extend(self._trace_messages(payload, path))
        trace_state.steps.extend(self._trace_steps(payload, path))
        trace_state.tool_results.extend(self._trace_tool_calls(payload, path))
        timeline = build_timeline(trace_state)
        llm_responses = self._trace_llm_responses(payload, path)
        redacted_messages = redact_value([message.model_dump() for message in trace_state.messages])
        redacted_llm_responses = redact_value(llm_responses)
        redacted_tool_calls = redact_value(
            [record.model_dump() for record in trace_state.tool_results]
        )

        return AgentOpsTraceDetail(
            trace_id=str(payload.get("run_id") or path.stem),
            trace_artifact_path=str(path),
            metadata=redact_value(payload.get("metadata", {})),
            timeline=timeline,
            turns=self._assemble_trace_turns(redacted_messages, redacted_llm_responses),
            final_state=redact_value(self._trace_final_state(payload, path)),
            db_hashes={
                "initial_db_hash": payload.get("metadata", {}).get("initial_db_hash"),
                "final_db_hash": payload.get("metadata", {}).get("final_db_hash"),
            },
            llm_responses=redacted_llm_responses,
            tool_calls=redacted_tool_calls,
        )

    def _report_paths(self) -> list[Path]:
        report_dir = self.artifact_dir / "reports"
        if not report_dir.exists():
            return []
        return sorted(report_dir.glob("*.json"))

    def _report_result(self, run_id: str, case_id: str) -> dict[str, Any]:
        path = self._report_path_for_run_id(run_id)
        payload = self._load_payload(path)
        for result in self._results(payload, path):
            if result.get("case_id") == case_id:
                return result
        raise WorkbenchAPIError(
            code="case_not_found",
            message=f"Case '{case_id}' was not found in report '{run_id}'.",
            status_code=404,
            details={"run_id": run_id, "case_id": case_id},
        )

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

    def _load_trace_payload(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise self._trace_artifact_parse_error(
                path, "Trace artifact could not be parsed."
            ) from exc
        if not isinstance(payload, dict):
            raise self._trace_artifact_parse_error(
                path, "Trace artifact must be a JSON object."
            )
        return payload

    def _trace_messages(self, payload: dict[str, Any], path: Path) -> list[Message]:
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            raise self._trace_artifact_parse_error(
                path, "Trace field 'messages' must be a list."
            )
        parsed: list[Message] = []
        for message in messages:
            if not isinstance(message, dict):
                raise self._trace_artifact_parse_error(
                    path, "Each trace message entry must be a JSON object."
                )
            try:
                parsed.append(Message(**message))
            except ValidationError as exc:
                raise self._trace_artifact_parse_error(
                    path, "Trace message entry could not be parsed."
                ) from exc
        return parsed

    def _trace_steps(self, payload: dict[str, Any], path: Path) -> list[AgentStep]:
        steps = payload.get("steps", [])
        if not isinstance(steps, list):
            raise self._trace_artifact_parse_error(path, "Trace field 'steps' must be a list.")
        parsed: list[AgentStep] = []
        for step in steps:
            if not isinstance(step, dict):
                raise self._trace_artifact_parse_error(
                    path, "Each trace step entry must be a JSON object."
                )
            try:
                parsed.append(AgentStep(**step))
            except ValidationError as exc:
                raise self._trace_artifact_parse_error(
                    path, "Trace step entry could not be parsed."
                ) from exc
        return parsed

    def _trace_tool_calls(
        self, payload: dict[str, Any], path: Path
    ) -> list[ToolCallRecord]:
        tool_calls = payload.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            raise self._trace_artifact_parse_error(
                path, "Trace field 'tool_calls' must be a list."
            )
        parsed: list[ToolCallRecord] = []
        for call in tool_calls:
            if not isinstance(call, dict):
                raise self._trace_artifact_parse_error(
                    path, "Each trace tool call entry must be a JSON object."
                )
            try:
                parsed.append(ToolCallRecord(**call))
            except ValidationError as exc:
                raise self._trace_artifact_parse_error(
                    path, "Trace tool call entry could not be parsed."
                ) from exc
        return parsed

    def _trace_llm_responses(self, payload: dict[str, Any], path: Path) -> list[dict[str, Any]]:
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise self._trace_artifact_parse_error(
                path, "Trace field 'metadata' must be a JSON object."
            )
        llm_responses = metadata.get("llm_responses", [])
        if not isinstance(llm_responses, list):
            raise self._trace_artifact_parse_error(
                path, "Trace field 'metadata.llm_responses' must be a list."
            )
        parsed: list[dict[str, Any]] = []
        for response in llm_responses:
            if not isinstance(response, dict):
                raise self._trace_artifact_parse_error(
                    path, "Each trace llm response entry must be a JSON object."
                )
            parsed.append(response)
        return parsed

    def _trace_final_state(self, payload: dict[str, Any], path: Path) -> dict[str, Any]:
        final_state = payload.get("final_state", {})
        if not isinstance(final_state, dict):
            raise self._trace_artifact_parse_error(
                path, "Trace field 'final_state' must be a JSON object."
            )
        return final_state

    def _assemble_trace_turns(
        self, messages: list[dict[str, Any]], llm_responses: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        turns: list[dict[str, Any]] = []
        current_messages: list[dict[str, Any]] = []

        for message in messages:
            if message.get("role") == "user" and current_messages:
                turns.append(
                    {
                        "index": len(turns),
                        "messages": current_messages,
                        "llm_responses": [],
                    }
                )
                current_messages = []
            current_messages.append(message)

        if current_messages:
            turns.append(
                {
                    "index": len(turns),
                    "messages": current_messages,
                    "llm_responses": [],
                }
            )

        if not turns:
            return [{"index": 0, "messages": [], "llm_responses": llm_responses}]

        for index, response in enumerate(llm_responses):
            target_index = min(index, len(turns) - 1)
            turns[target_index]["llm_responses"].append(response)
        return turns

    def _trace_artifact_parse_error(self, path: Path, message: str) -> WorkbenchAPIError:
        return WorkbenchAPIError(
            code="artifact_parse_error",
            message=message,
            status_code=500,
            details={"trace_path": str(path)},
        )
