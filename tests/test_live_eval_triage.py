from __future__ import annotations

from app.eval.live_triage import (
    classify_failure,
    format_markdown,
    summarize_report,
)


def _result(**overrides):
    result = {
        "case_id": "case_1",
        "passed": False,
        "trial": 0,
        "failure_label": "wrong_tool",
        "trace_artifact_path": "artifacts/phase2/traces/eval-x/runs/case_1.json",
        "tool_protocol_violations": 0,
        "tool_errors": 0,
        "failed_tool_calls": 0,
        "guard_blocks": 0,
        "blocked_tool_calls": 0,
        "actual_guard_block_reasons": [],
        "expected_actual_diff": {},
        "db_assertion_failures": [],
    }
    result.update(overrides)
    return result


def test_classifies_tool_protocol_before_other_buckets() -> None:
    result = _result(tool_protocol_violations=1, failed_tool_calls=1)

    assert classify_failure(result) == "tool_protocol"


def test_classifies_tool_error_from_tool_error_metrics() -> None:
    result = _result(failure_label="tool_exception", tool_errors=1)

    assert classify_failure(result) == "tool_error"


def test_classifies_tool_selection_from_required_tool_mismatch() -> None:
    result = _result(
        failure_label="required_tool_missing",
        expected_actual_diff={"missing_required_tools": ["get_order_details"]},
    )

    assert classify_failure(result) == "tool_selection"


def test_classifies_guard_behavior_from_guard_metrics() -> None:
    result = _result(
        failure_label="expected_guard_block_missing",
        guard_blocks=1,
        actual_guard_block_reasons=["order_status_not_pending"],
    )

    assert classify_failure(result) == "guard_behavior"


def test_classifies_response_oracle_when_only_response_assertions_fail() -> None:
    result = _result(
        failure_label="response_mismatch",
        expected_actual_diff={"assistant_response": {"missing_terms": ["pending"]}},
    )

    assert classify_failure(result) == "response_oracle"


def test_classifies_db_assertion_mismatch_into_response_oracle_bucket() -> None:
    result = _result(
        failure_label="db_assertion_mismatch",
        db_assertion_failures=["user:U1 address.zip expected 78701 actual 78784"],
    )

    assert classify_failure(result) == "response_oracle"


def test_classifies_wrong_tool_sequence_into_tool_selection_bucket() -> None:
    result = _result(
        failure_label="wrong_tool_sequence",
        expected_actual_diff={
            "expected_tool_names": ["find_user_id_by_email", "get_user_details"],
            "actual_tool_names": ["get_user_details", "find_user_id_by_email"],
        },
    )

    assert classify_failure(result) == "tool_selection"


def test_classifies_unknown_live_behavior_when_no_rule_matches() -> None:
    result = _result(failure_label="unexpected_model_behavior")

    assert classify_failure(result) == "unknown_live_behavior"


def test_classifies_runtime_error_when_result_shape_is_incomplete() -> None:
    result = {"failure_label": "tool_exception"}

    assert classify_failure(result) == "runtime_error"


def test_markdown_includes_report_case_bucket_and_next_action() -> None:
    report = {
        "report_artifact_path": "artifacts/phase2/reports/eval-x.json",
        "subset": "generalized_mvp",
        "metrics": {"passed_count": 1, "result_count": 2},
        "results": [
            _result(
                case_id="failed_case",
                failure_label="tool_exception",
                tool_errors=1,
                tool_call_count=3,
                successful_tool_calls=2,
                failed_tool_calls=1,
                tool_protocol_violations=0,
                expected_actual_diff={
                    "missing_required_tools": ["get_order_details"],
                    "actual_tool_names": ["find_user_id_by_email", "modify_user_address"],
                },
            ),
            _result(case_id="passed_case", passed=True, failure_label=None),
        ],
    }

    markdown = format_markdown(summarize_report(report))

    assert "artifacts/phase2/reports/eval-x.json" in markdown
    assert "failed_case" in markdown
    assert "tool_error" in markdown
    assert "Tool calls: 3 total, 2 successful, 1 failed" in markdown
    assert "Protocol violations: 0" in markdown
    assert "Expected/actual tool mismatch" in markdown
    assert "get_order_details" in markdown
    assert "find_user_id_by_email" in markdown
    assert "Suggested next action" in markdown
