from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from app.eval.triage_bundle import build_triage_bundle

TOOL_PROTOCOL = "tool_protocol"
TOOL_ERROR = "tool_error"
TOOL_SELECTION = "tool_selection"
GUARD_BEHAVIOR = "guard_behavior"
RESPONSE_ORACLE = "response_oracle"
RUNTIME_ERROR = "runtime_error"
UNKNOWN_LIVE_BEHAVIOR = "unknown_live_behavior"

RUNTIME_BUG = "runtime_bug"
TOOL_SCHEMA_GAP = "tool_schema_gap"
PROMPT_GAP = "prompt_gap"
MODEL_REASONING_GAP = "model_reasoning_gap"
GUARD_POLICY_GAP = "guard_policy_gap"
DATA_FIXTURE_GAP = "data_fixture_gap"
PROVIDER_ERROR = "provider_error"
EXPECTED_BEHAVIOR_UNCLEAR = "expected_behavior_unclear"


_RUNNER_LABEL_TO_BUCKET = {
    "llm_json_failure": TOOL_PROTOCOL,
    "auth_failure": GUARD_BEHAVIOR,
    "wrong_tool": TOOL_SELECTION,
    "required_tool_missing": TOOL_SELECTION,
    "forbidden_tool_called": TOOL_SELECTION,
    "tool_exception": TOOL_ERROR,
    "expected_guard_block_missing": GUARD_BEHAVIOR,
    "guard_blocked": GUARD_BEHAVIOR,
    "confirmation_status_mismatch": GUARD_BEHAVIOR,
    "confirmation_failure": GUARD_BEHAVIOR,
    "unexpected_mutation": RESPONSE_ORACLE,
    "mutation_missing": RESPONSE_ORACLE,
    "db_state_mismatch": RESPONSE_ORACLE,
    "db_assertion_mismatch": RESPONSE_ORACLE,
    "response_mismatch": RESPONSE_ORACLE,
    "wrong_tool_sequence": TOOL_SELECTION,
}

_NEXT_ACTIONS = {
    TOOL_PROTOCOL: "Inspect provider tool-call messages and fix protocol assembly or replay handling.",
    TOOL_ERROR: "Open the trace, inspect the failing tool arguments/error, and add a deterministic regression before patching the tool surface.",
    TOOL_SELECTION: "Compare expected and actual tool calls, then tighten prompt or tool schema wording without case-id branches.",
    GUARD_BEHAVIOR: "Review guard block reasons and policy expectations; patch guard behavior only if policy handling is inconsistent.",
    RESPONSE_ORACLE: "Check whether DB/tool behavior is correct and update the oracle only if the assistant response is acceptable.",
    RUNTIME_ERROR: "Inspect the report/trace structure and runtime exception before classifying model behavior.",
    UNKNOWN_LIVE_BEHAVIOR: "Inspect the trace manually and add a more specific triage rule if the pattern repeats.",
}


def classify_failure(result: Mapping[str, Any]) -> str:
    if not _has_normal_result_shape(result):
        return RUNTIME_ERROR
    if _int(result.get("tool_protocol_violations")) > 0:
        return TOOL_PROTOCOL
    if _int(result.get("failed_tool_calls")) > 0 or _int(result.get("tool_errors")) > 0:
        return TOOL_ERROR
    if result.get("exception") or result.get("runtime_error"):
        return RUNTIME_ERROR
    label = str(result.get("failure_label") or "")
    if label in _RUNNER_LABEL_TO_BUCKET:
        return _RUNNER_LABEL_TO_BUCKET[label]
    if _has_guard_behavior(result):
        return GUARD_BEHAVIOR
    if _has_tool_selection_mismatch(result):
        return TOOL_SELECTION
    if _has_response_oracle_mismatch(result):
        return RESPONSE_ORACLE
    return UNKNOWN_LIVE_BEHAVIOR


def summarize_failure(result: Mapping[str, Any]) -> dict[str, Any]:
    bucket = classify_failure(result)
    trace_path = result.get("trace_artifact_path") or _nested(
        result, "replay_metadata", "trace_artifact_path"
    )
    expected_actual_diff = dict(result.get("expected_actual_diff") or {})
    tool_name_context = _extract_tool_name_context(result, expected_actual_diff)
    return {
        "case_id": result.get("case_id", "(unknown)"),
        "trial": result.get("trial"),
        "subset": result.get("subset"),
        "bucket": bucket,
        "root_cause": infer_root_cause(result),
        "failure_label": result.get("failure_label"),
        "failure_category": result.get("failure_category"),
        "failure_summary": result.get("failure_summary"),
        "trace_artifact_path": trace_path,
        "final_response": result.get("final_response")
        or result.get("assistant_response")
        or result.get("final_assistant_message"),
        "tool_call_count": _int(result.get("tool_call_count")),
        "successful_tool_calls": _int(result.get("successful_tool_calls")),
        "failed_tool_calls": _int(result.get("failed_tool_calls")),
        "tool_protocol_violations": _int(result.get("tool_protocol_violations")),
        "tool_errors": _int(result.get("tool_errors")),
        "guard_blocks": _int(result.get("guard_blocks")),
        "blocked_tool_calls": _int(result.get("blocked_tool_calls")),
        "actual_guard_block_reasons": list(result.get("actual_guard_block_reasons") or []),
        "tool_names": tool_name_context["tool_names"],
        "tool_mismatches": tool_name_context["tool_mismatches"],
        "db_assertion_failures": list(result.get("db_assertion_failures") or []),
        "expected_actual_diff": expected_actual_diff,
        "triage_bundle": build_triage_bundle(result),
        "suggested_next_action": _NEXT_ACTIONS[bucket],
    }


def infer_root_cause(result: Mapping[str, Any]) -> str:
    if result.get("provider_error") or result.get("runtime_error"):
        return PROVIDER_ERROR
    label = str(result.get("failure_label") or "")
    if label == "tool_exception":
        return RUNTIME_BUG
    if label in {
        "wrong_tool",
        "required_tool_missing",
        "forbidden_tool_called",
        "wrong_tool_sequence",
    }:
        return PROMPT_GAP
    if label == "llm_json_failure":
        return TOOL_SCHEMA_GAP
    if label in {
        "expected_guard_block_missing",
        "guard_blocked",
        "confirmation_status_mismatch",
        "confirmation_failure",
    }:
        return GUARD_POLICY_GAP
    if label in {
        "db_state_mismatch",
        "db_assertion_mismatch",
        "unexpected_mutation",
        "mutation_missing",
    }:
        return DATA_FIXTURE_GAP
    if label == "response_mismatch":
        return MODEL_REASONING_GAP
    return EXPECTED_BEHAVIOR_UNCLEAR


def summarize_report(report: Mapping[str, Any]) -> dict[str, Any]:
    results = list(report.get("results") or [])
    failed_results = [
        result
        for result in results
        if isinstance(result, Mapping) and result.get("passed") is not True
    ]
    subset = report.get("subset")
    failures = []
    for result in failed_results:
        enriched = dict(result)
        enriched.setdefault("subset", subset)
        failures.append(summarize_failure(enriched))

    metrics = report.get("metrics") if isinstance(report.get("metrics"), Mapping) else {}
    result_count = _int(metrics.get("result_count"), default=len(results))
    passed_count = _int(
        metrics.get("passed_count"),
        default=_int(report.get("passed_count"), default=result_count - len(failures)),
    )
    report_path = report.get("report_artifact_path") or _nested(
        report, "summary", "report_artifact_path"
    )
    return {
        "report_artifact_path": report_path,
        "eval_run_id": report.get("eval_run_id"),
        "subset": subset,
        "trials": report.get("trials"),
        "passed_count": passed_count,
        "result_count": result_count,
        "pass_rate": metrics.get("pass_1") or report.get("pass_rate"),
        "failure_count": len(failures),
        "failures": failures,
    }


def format_markdown(summary: Mapping[str, Any]) -> str:
    report_path = summary.get("report_artifact_path") or "(unknown report)"
    subset = summary.get("subset") or "(unknown subset)"
    passed_count = summary.get("passed_count", 0)
    result_count = summary.get("result_count", 0)
    lines = [
        "# Live Eval Triage",
        "",
        f"- Report: `{report_path}`",
        f"- Subset: `{subset}`",
        f"- Passed: {passed_count}/{result_count}",
        f"- Failures: {summary.get('failure_count', 0)}",
    ]

    failures = list(summary.get("failures") or [])
    if not failures:
        lines.extend(["", "No failed cases found."])
        return "\n".join(lines)

    lines.append("")
    lines.append("## Failed Cases")
    for failure in failures:
        case_id = failure.get("case_id", "(unknown)")
        bucket = failure.get("bucket", UNKNOWN_LIVE_BEHAVIOR)
        lines.extend(
            [
                "",
                f"### `{case_id}`",
                f"- Bucket: `{bucket}`",
                f"- Root cause: `{failure.get('root_cause')}`",
                f"- Failure label: `{failure.get('failure_label')}`",
                f"- Trial: {failure.get('trial')}",
            ]
        )
        trace_path = failure.get("trace_artifact_path")
        if trace_path:
            lines.append(f"- Trace: `{trace_path}`")
        lines.append(
            "- Tool calls: "
            f"{failure.get('tool_call_count', 0)} total, "
            f"{failure.get('successful_tool_calls', 0)} successful, "
            f"{failure.get('failed_tool_calls', 0)} failed"
        )
        lines.append(
            f"- Tool errors: {failure.get('tool_errors', 0)}"
        )
        lines.append(
            f"- Protocol violations: {failure.get('tool_protocol_violations', 0)}"
        )
        tool_names = failure.get("tool_names") or []
        if tool_names:
            lines.append(f"- Tool names: `{', '.join(map(str, tool_names))}`")
        tool_mismatches = failure.get("tool_mismatches") or {}
        if tool_mismatches:
            lines.append(
                f"- Expected/actual tool mismatch: {_format_tool_mismatches(tool_mismatches)}"
            )
        guard_reasons = failure.get("actual_guard_block_reasons") or []
        if guard_reasons:
            lines.append(f"- Guard reasons: `{', '.join(map(str, guard_reasons))}`")
        db_failures = failure.get("db_assertion_failures") or []
        if db_failures:
            lines.append(f"- DB assertion failures: {len(db_failures)}")
        final_response = failure.get("final_response")
        if final_response:
            lines.append(f"- Final response: {final_response}")
        lines.append(
            f"- Suggested next action: {failure.get('suggested_next_action')}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize live Phase 2 eval failures.")
    parser.add_argument("report", type=Path, help="Path to a Phase 2 report JSON file.")
    args = parser.parse_args(argv)

    with args.report.open(encoding="utf-8") as file:
        report = json.load(file)
    report.setdefault("report_artifact_path", str(args.report))
    print(format_markdown(summarize_report(report)))
    return 0


def _has_normal_result_shape(result: Mapping[str, Any]) -> bool:
    return "case_id" in result and "passed" in result


def _has_guard_behavior(result: Mapping[str, Any]) -> bool:
    if _int(result.get("guard_blocks")) > 0 or _int(result.get("blocked_tool_calls")) > 0:
        return True
    return bool(result.get("actual_guard_block_reasons"))


def _has_tool_selection_mismatch(result: Mapping[str, Any]) -> bool:
    diff = result.get("expected_actual_diff")
    if not isinstance(diff, Mapping):
        return False
    mismatch_keys = {
        "missing_tools",
        "missing_required_tools",
        "forbidden_tools",
        "unexpected_tools",
        "expected_tool_names",
        "actual_tool_names",
    }
    return any(key in diff for key in mismatch_keys)


def _has_response_oracle_mismatch(result: Mapping[str, Any]) -> bool:
    diff = result.get("expected_actual_diff")
    if not isinstance(diff, Mapping):
        return False
    response_keys = {
        "assistant_response",
        "final_response",
        "response_assertions",
        "missing_response_terms",
    }
    return any(key in diff for key in response_keys) and not result.get(
        "db_assertion_failures"
    )


def _extract_tool_name_context(
    result: Mapping[str, Any],
    expected_actual_diff: Mapping[str, Any],
) -> dict[str, Any]:
    tool_names = []
    for key in ("tool_names", "actual_tool_names", "expected_tool_names"):
        value = result.get(key)
        if isinstance(value, list):
            tool_names.extend(str(item) for item in value)
    if isinstance(expected_actual_diff.get("actual_tool_names"), list):
        tool_names.extend(str(item) for item in expected_actual_diff["actual_tool_names"])
    if isinstance(expected_actual_diff.get("expected_tool_names"), list):
        tool_names.extend(
            str(item) for item in expected_actual_diff["expected_tool_names"]
        )

    mismatches = {}
    for key in (
        "missing_tools",
        "missing_required_tools",
        "forbidden_tools",
        "unexpected_tools",
        "expected_tool_names",
        "actual_tool_names",
    ):
        value = expected_actual_diff.get(key)
        if isinstance(value, list) and value:
            mismatches[key] = [str(item) for item in value]

    return {
        "tool_names": _dedupe_preserve_order(tool_names),
        "tool_mismatches": mismatches,
    }


def _format_tool_mismatches(tool_mismatches: Mapping[str, Any]) -> str:
    parts = []
    for key, values in tool_mismatches.items():
        if isinstance(values, list):
            parts.append(f"{key}=[{', '.join(map(str, values))}]")
    return "; ".join(parts)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _int(value: Any, *, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    raise SystemExit(main())
