import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.config import resolve_config
from app.eval.cases import EvalCase, get_cases
from app.eval.metrics import (
    apply_case_diagnostics,
    build_comparison_artifact,
    compute_metrics,
)
from app.eval.runner import CuratedEvalRunner, EvalCaseResult, classify_failure


class CuratedEvalTests(unittest.TestCase):
    def test_curated_subset_contains_mvp_categories(self):
        cases = get_cases("curated_mvp")
        categories = {case.category for case in cases}

        self.assertEqual(len(cases), 11)
        self.assertEqual(
            categories,
            {
                "lookup",
                "cancel",
                "modify_address",
                "return",
                "exchange",
                "transfer",
                "confirmation",
                "guard",
            },
        )

    def test_classify_failure_detects_auth_failure_first(self):
        case = get_cases("curated_mvp")[0]

        label = classify_failure(
            case=case,
            authenticated_user_id="wrong_user",
            final_intent=case.expected_intent,
            write_locks=[],
            actual_order_status=None,
            assistant_messages=[],
            tool_names=case.expected_tool_names,
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="not_required",
        )

        self.assertEqual(label, "auth_failure")

    def test_classify_failure_accepts_expected_guard_block(self):
        case = next(
            item
            for item in get_cases("curated_mvp")
            if item.case_id == "block_cancel_processed_order"
        )

        label = classify_failure(
            case=case,
            authenticated_user_id=case.expected_user_id,
            final_intent=case.expected_intent,
            write_locks=[],
            actual_order_status=case.expected_order_status,
            assistant_messages=[],
            tool_names=case.expected_tool_names,
            guard_block_reasons=[case.expected_guard_block_reason],
            tool_errors=0,
            guard_blocks=1,
            pending_action=False,
            llm_errors=0,
            confirmation_status=case.expected_confirmation_status,
        )

        self.assertIsNone(label)

    def test_curated_eval_runner_writes_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "AGENT_LLM_TIMEOUT_SECONDS": "30",
                    "AGENT_LLM_MAX_RETRIES": "2",
                },
            ):
                config = resolve_config(artifact_dir=tmp)
                summary = CuratedEvalRunner(
                    config=config,
                    artifact_dir=Path(tmp),
                ).run(subset="curated_mvp", trials=1)
            payload = json.loads(
                Path(summary.result_artifact_path).read_text(encoding="utf-8")
            )
            report_exists = Path(summary.report_artifact_path).exists()
            report = json.loads(
                Path(summary.report_artifact_path).read_text(encoding="utf-8")
            )

        self.assertEqual(summary.case_count, 11)
        self.assertEqual(summary.schema_version, "phase2.eval_run_summary.v1")
        self.assertEqual(summary.passed_count, 11)
        self.assertEqual(summary.pass_rate, 1.0)
        self.assertEqual(payload["passed_count"], 11)
        self.assertEqual(len(payload["results"]), 11)
        self.assertIn("prompt_metadata", payload)
        self.assertIn("dataset_db_path", payload)
        self.assertEqual(payload["llm_timeout_seconds"], 30.0)
        self.assertEqual(payload["llm_max_retries"], 2)
        self.assertIsInstance(payload["results"][0]["duration_seconds"], float)
        self.assertGreaterEqual(payload["results"][0]["duration_seconds"], 0.0)
        self.assertIn("metrics", payload)
        self.assertIn("failure_analysis", payload)
        self.assertEqual(payload["metrics"]["pass_1"], 1.0)
        self.assertEqual(payload["metrics"]["pass_k"], 1.0)
        self.assertEqual(payload["metrics"]["db_accuracy"], 1.0)
        self.assertEqual(payload["metrics"]["db_accuracy_denominator"], 9)
        self.assertEqual(payload["metrics"]["tool_error_rate"], 0.0)
        self.assertEqual(payload["metrics"]["mutation_error_rate"], 0.0)
        self.assertEqual(payload["schema_version"], "phase2.eval_run_summary.v1")
        self.assertIn("failure_label_counts", payload["failure_analysis"])
        self.assertIn("run_id", payload["results"][0])
        self.assertIn("session_id", payload["results"][0])
        self.assertIn("replay_metadata", payload["results"][0])
        self.assertIn("message_count", payload["results"][0])
        self.assertIn("policy_check_count", payload["results"][0])
        self.assertTrue(report_exists)
        self.assertEqual(report["schema_version"], "phase2.eval_report.v1")
        self.assertEqual(report["report_type"], "phase2_eval_report")
        self.assertEqual(report["metrics"]["pass_1"], 1.0)

    def test_curated_eval_runner_reports_progress(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            CuratedEvalRunner(
                config=config,
                artifact_dir=Path(tmp),
                progress_callback=lambda event, result: events.append(
                    (event, result.case_id, result.trial)
                ),
            ).run(subset="curated_mvp", trials=1)

        self.assertEqual(events[0], ("start", "lookup_pending_order", 0))
        self.assertEqual(events[1][0], "finish")
        self.assertEqual(len(events), 22)

    def test_metrics_compute_pass_k_by_unique_case(self):
        results = [
            _result("case_a", 0, passed=True),
            _result("case_a", 1, passed=False, failure_label="wrong_tool"),
            _result("case_b", 0, passed=True),
            _result("case_b", 1, passed=True),
        ]

        metrics = compute_metrics(results)

        self.assertEqual(metrics["pass_1"], 0.75)
        self.assertEqual(metrics["pass_k"], 0.5)

    def test_expected_guard_block_is_not_tool_error(self):
        result = _result(
            "guard_case",
            0,
            passed=True,
            tool_call_count=1,
            successful_tool_calls=0,
            failed_tool_calls=0,
            blocked_tool_calls=1,
            guard_blocks=1,
        )

        metrics = compute_metrics([result])

        self.assertEqual(metrics["tool_error_rate"], 0.0)
        self.assertEqual(metrics["guard_block_rate"], 1.0)

    def test_no_write_case_flags_unexpected_mutation(self):
        case = SimpleNamespace(
            case_id="no_write_without_order_status",
            expected_no_write=True,
            expected_order_status=None,
        )
        result = _result(
            case.case_id,
            0,
            initial_db_hash="before",
            final_db_hash="after",
        )

        apply_case_diagnostics(result, case)
        metrics = compute_metrics([result])

        self.assertTrue(result.mutation_detected)
        self.assertTrue(result.unexpected_mutation)
        self.assertFalse(result.db_accuracy_passed)
        self.assertEqual(result.db_accuracy_basis, "db_hash_no_write")
        self.assertEqual(result.expected_actual_diff["mutation"]["expected"], "no_write")
        self.assertEqual(result.failure_category, None)
        self.assertEqual(metrics["mutation_error_rate"], 1.0)

    def test_failure_diagnostics_include_summary_and_diff(self):
        result = _result(
            "case_with_status_mismatch",
            0,
            passed=False,
            failure_label="db_state_mismatch",
        )
        result.expected_order_status = "cancelled"
        result.actual_order_status = "pending"

        apply_case_diagnostics(
            result,
            SimpleNamespace(
                case_id=result.case_id,
                expected_no_write=False,
                expected_order_status="cancelled",
            ),
        )

        self.assertEqual(result.failure_category, "wrong_tool_arguments")
        self.assertEqual(
            result.expected_actual_diff["order_status"],
            {"expected": "cancelled", "actual": "pending"},
        )
        self.assertIn("order_status", result.failure_summary)

    def test_comparison_artifact_reports_metric_deltas(self):
        comparison = build_comparison_artifact(
            baseline={
                "eval_run_id": "baseline",
                "model": "model-a",
                "code_commit": "abc",
                "metrics": {"pass_1": 0.5, "average_latency_seconds": 2.0},
                "failure_analysis": {"failure_label_counts": {"wrong_tool": 1}},
            },
            candidate={
                "eval_run_id": "candidate",
                "model": "model-b",
                "code_commit": "def",
                "metrics": {"pass_1": 0.75, "average_latency_seconds": 1.5},
                "failure_analysis": {"failure_label_counts": {"passed": 3}},
            },
        )

        self.assertEqual(comparison["schema_version"], "phase2.eval_comparison.v1")
        self.assertEqual(comparison["metric_deltas"]["pass_1"]["delta"], 0.25)
        self.assertEqual(
            comparison["metric_deltas"]["average_latency_seconds"]["delta"],
            -0.5,
        )

    def test_generalized_subset_starts_as_curated_regression_copy(self):
        curated_cases = get_cases("curated_mvp")
        generalized_cases = get_cases("generalized_mvp")

        self.assertGreater(len(generalized_cases), len(curated_cases))
        self.assertEqual({case.subset for case in curated_cases}, {"curated_mvp"})
        self.assertEqual({case.subset for case in generalized_cases}, {"generalized_mvp"})
        curated_ids = {case.case_id for case in curated_cases}
        generalized_ids = {case.case_id for case in generalized_cases}
        self.assertTrue(curated_ids.issubset(generalized_ids))
        self.assertIsNot(generalized_cases[0].messages, curated_cases[0].messages)

    def test_expected_tool_sequence_detects_wrong_order(self):
        case = EvalCase(
            case_id="ordered_tools",
            category="test",
            messages=[],
            expected_user_id="user",
            expected_intent="lookup",
            expected_tool_names=["first_tool", "second_tool"],
            expected_tool_sequence=["first_tool", "second_tool"],
        )

        label = classify_failure(
            case=case,
            authenticated_user_id="user",
            final_intent="lookup",
            write_locks=[],
            actual_order_status=None,
            assistant_messages=[],
            tool_names=["second_tool", "first_tool"],
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="not_required",
        )

        self.assertEqual(label, "wrong_tool_sequence")

    def test_generalized_mvp_has_minimum_case_count(self):
        cases = get_cases("generalized_mvp")
        self.assertGreaterEqual(
            len(cases), 30,
            f"generalized_mvp has {len(cases)} cases, expected at least 30"
        )
        subsets = {case.subset for case in cases}
        self.assertEqual(subsets, {"generalized_mvp"})

    def test_phase5_cases_cover_multi_item_exchange_and_user_address_write(self):
        cases = {case.case_id: case for case in get_cases("generalized_mvp")}

        exchange_case = cases["multi_item_exchange_success"]
        exchange_text = " ".join(message["content"] for message in exchange_case.messages)
        exchange_item_ids = re.findall(r"\b\d{8,}\b", exchange_text)
        self.assertGreaterEqual(len(set(exchange_item_ids)), 4)
        self.assertEqual(
            exchange_case.expected_write_lock,
            "item:6700049080,6777246137:exchange",
        )
        self.assertEqual(exchange_case.capability, "multi_item_exchange")

        address_case = cases["modify_user_default_address_success"]
        self.assertEqual(
            address_case.expected_write_lock,
            "user:sofia_rossi_8776:modify_address",
        )
        self.assertEqual(
            address_case.expected_db_assertions,
            {
                "user_id": "sofia_rossi_8776",
                "address": {
                    "address1": "12 Oak St",
                    "address2": "Unit 4",
                    "city": "Austin",
                    "state": "TX",
                    "country": "USA",
                    "zip": "78701",
                },
            },
        )

    def test_expected_db_assertions_detect_user_address_mismatch(self):
        case = EvalCase(
            case_id="user_address_assertion",
            category="modify_address",
            messages=[],
            expected_user_id="user",
            expected_intent="modify_user_address",
            expected_db_assertions={
                "user_id": "user",
                "address": {"zip": "78701"},
            },
        )

        label = classify_failure(
            case=case,
            authenticated_user_id="user",
            final_intent="modify_user_address",
            write_locks=[],
            actual_order_status=None,
            assistant_messages=[],
            tool_names=[],
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="confirmed",
            db_assertion_failures=["user:user address.zip expected 78701 actual 78702"],
        )

        self.assertEqual(label, "db_assertion_mismatch")

    def test_phase5_capability_matrix_lists_implemented_cases(self):
        matrix = Path("docs/phase5-capability-matrix.md").read_text(encoding="utf-8")
        self.assertIn("## Implemented Cases", matrix)
        missing = [
            case.case_id
            for case in get_cases("generalized_mvp")
            if case.case_id not in matrix
        ]
        self.assertEqual(missing, [])

    def test_generalized_eval_runner_passes_phase5_subset(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            summary = CuratedEvalRunner(
                config=config,
                artifact_dir=Path(tmp),
            ).run(subset="generalized_mvp", trials=1)

            self.assertGreaterEqual(summary.case_count, 30)
            self.assertEqual(summary.passed_count, summary.case_count)
            self.assertEqual(summary.metrics["pass_1"], 1.0)
            self.assertEqual(summary.metrics["pass_k"], 1.0)
            self.assertEqual(summary.metrics["mutation_error_rate"], 0.0)
            self.assertEqual(summary.metrics["tool_error_rate"], 0.0)


def _result(
    case_id: str,
    trial: int,
    *,
    passed: bool = True,
    failure_label: str | None = None,
    tool_call_count: int = 0,
    successful_tool_calls: int = 0,
    failed_tool_calls: int = 0,
    blocked_tool_calls: int = 0,
    guard_blocks: int = 0,
    initial_db_hash: str = "same",
        final_db_hash: str = "same",
) -> EvalCaseResult:
    return EvalCaseResult(
        run_id=f"{case_id}-{trial}",
        session_id=f"{case_id}-{trial}",
        case_id=case_id,
        category="test",
        trial=trial,
        passed=passed,
        failure_label=failure_label,
        trace_artifact_path="trace.json",
        authenticated_user_id="user",
        final_intent="lookup",
        termination_reason="script_completed",
        expected_write_lock=None,
        initial_db_hash=initial_db_hash,
        final_db_hash=final_db_hash,
        tool_call_count=tool_call_count,
        successful_tool_calls=successful_tool_calls,
        failed_tool_calls=failed_tool_calls,
        blocked_tool_calls=blocked_tool_calls,
        guard_blocks=guard_blocks,
        tool_errors=failed_tool_calls,
        db_accuracy_passed=True,
        db_accuracy_basis="test",
        trial_turn_count=1,
    )


if __name__ == "__main__":
    unittest.main()
