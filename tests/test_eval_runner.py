import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.agent.models import SessionState
from app.config import resolve_config
from app.eval.cases import EvalCase, get_cases
from app.eval.metrics import (
    apply_case_diagnostics,
    build_comparison_artifact,
    build_failure_analysis,
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

    def test_live_smoke_core_subset_pins_representative_cases(self):
        cases = get_cases("live_smoke_core")

        self.assertEqual(
            [case.case_id for case in cases],
            [
                "lookup_pending_order",
                "cancel_pending_order",
                "return_delivered_order_item",
                "exchange_delivered_order_item",
                "deny_cancel_confirmation",
                "block_wrong_user_order_access",
            ],
        )
        self.assertTrue(all(case.subset == "live_smoke_core" for case in cases))

    def test_live_guard_smoke_subset_pins_guard_cases(self):
        cases = get_cases("live_guard_smoke")

        self.assertEqual(
            [case.case_id for case in cases],
            [
                "block_cancel_processed_order",
                "block_return_pending_order",
                "block_wrong_user_order_access",
            ],
        )
        self.assertTrue(all(case.category == "guard" for case in cases))
        self.assertTrue(all(case.expected_no_write for case in cases))

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
        self.assertEqual(summary.schema_version, "phase5.eval_run_summary.v1")
        # Deterministic mode now handles write intents directly → all 11 pass
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
        # db_accuracy computed from db assertions; score depends on pre-flight lookups
        self.assertIsInstance(payload["metrics"]["db_accuracy"], float)
        self.assertEqual(payload["metrics"]["db_accuracy_denominator"], 9)
        self.assertEqual(payload["metrics"]["tool_error_rate"], 0.0)
        self.assertEqual(payload["metrics"]["mutation_error_rate"], 0.0)
        self.assertEqual(payload["schema_version"], "phase5.eval_run_summary.v1")
        self.assertIn("failure_label_counts", payload["failure_analysis"])
        self.assertIn("run_id", payload["results"][0])
        self.assertIn("session_id", payload["results"][0])
        self.assertIn("replay_metadata", payload["results"][0])
        self.assertIn("message_count", payload["results"][0])
        self.assertIn("policy_check_count", payload["results"][0])
        self.assertTrue(report_exists)
        self.assertEqual(report["schema_version"], "phase5.eval_report.v1")
        self.assertEqual(report["report_type"], "phase5_eval_report")
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

    def test_metrics_aggregate_llm_token_usage_and_loop_iterations(self):
        results = [
            _result(
                "case_a",
                0,
                llm_token_usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
                llm_loop_iterations=2,
            ),
            _result(
                "case_b",
                0,
                llm_token_usage={
                    "prompt_tokens": 50,
                    "completion_tokens": 10,
                    "total_tokens": 60,
                },
                llm_loop_iterations=4,
            ),
        ]

        metrics = compute_metrics(results)

        self.assertEqual(
            metrics["total_token_usage"],
            {
                "completion_tokens": 30,
                "prompt_tokens": 150,
                "total_tokens": 180,
            },
        )
        self.assertEqual(metrics["average_llm_loop_iterations"], 3.0)

    def test_metrics_aggregate_runtime_fallback_counters(self):
        metrics = compute_metrics(
            [
                _result(
                    "case_a",
                    0,
                    auto_load_count=2,
                    premature_refusal_corrected_count=1,
                ),
                _result(
                    "case_b",
                    0,
                    auto_load_count=1,
                    premature_refusal_corrected_count=0,
                ),
            ]
        )

        self.assertEqual(metrics["auto_load_count"], 3)
        self.assertEqual(metrics["premature_refusal_corrected_count"], 1)

    def test_eval_report_contains_phase9_baseline_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            summary = CuratedEvalRunner(
                config=config,
                artifact_dir=Path(tmp),
            ).run(subset="live_guard_smoke", trials=1)
            report = json.loads(
                Path(summary.report_artifact_path).read_text(encoding="utf-8")
            )

        metadata = report["baseline_metadata"]
        self.assertEqual(metadata["eval_backend"], "scripted_offline_demo")
        self.assertEqual(metadata["subset"], "live_guard_smoke")
        self.assertIn("model", metadata)
        self.assertIn("provider", metadata)
        self.assertRegex(metadata["prompt_hash"], r"^[0-9a-f]{64}$")
        self.assertRegex(metadata["tool_schema_hash"], r"^[0-9a-f]{64}$")
        self.assertRegex(metadata["action_specs_hash"], r"^[0-9a-f]{64}$")
        self.assertIn("total_token_usage", report["metrics"])
        self.assertIn("average_llm_loop_iterations", report["metrics"])
        self.assertIn("llm_loop_iterations", report["results"][0])
        self.assertIn("llm_token_usage", report["results"][0])

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

    def test_failure_analysis_groups_by_language_variation_level(self):
        base = _result("cancel_success_s100", 0)
        base.scenario_family = "cancel"
        base.variant_type = "cancel_success"
        base.language_variation_level = "base"
        l1 = _result(
            "cancel_success_s100_l1",
            0,
            passed=False,
            failure_label="wrong_intent",
        )
        l1.scenario_family = "cancel"
        l1.variant_type = "cancel_success"
        l1.language_variation_level = "L1"

        analysis = build_failure_analysis([base, l1])

        self.assertEqual(
            analysis["language_variation_level_counts"],
            {
                "L1": {"wrong_intent": 1},
                "base": {"passed": 1},
            },
        )

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
        self.assertEqual(
            result.expected_actual_diff["mutation"]["expected"], "no_write"
        )
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

    def test_comparison_artifact_reports_case_level_deltas(self):
        comparison = build_comparison_artifact(
            baseline={
                "eval_run_id": "baseline",
                "model": "model-a",
                "code_commit": "abc",
                "metrics": {"pass_1": 0.5},
                "failure_analysis": {"failure_label_counts": {"wrong_tool": 2}},
                "report_artifact_path": "baseline-report.json",
                "results": [
                    {
                        "case_id": "fixed_case",
                        "passed": False,
                        "failure_label": "wrong_tool",
                        "trace_artifact_path": "baseline-fixed.trace.json",
                    },
                    {
                        "case_id": "still_failing_case",
                        "passed": False,
                        "failure_label": "wrong_tool",
                        "trace_artifact_path": "baseline-still.trace.json",
                    },
                    {
                        "case_id": "new_failure_case",
                        "passed": True,
                        "failure_label": None,
                        "trace_artifact_path": "baseline-new.trace.json",
                    },
                    {
                        "case_id": "baseline_only_case",
                        "passed": True,
                        "failure_label": None,
                        "trace_artifact_path": "baseline-only.trace.json",
                    },
                ],
            },
            candidate={
                "eval_run_id": "candidate",
                "model": "model-b",
                "code_commit": "def",
                "metrics": {"pass_1": 0.75},
                "failure_analysis": {"failure_label_counts": {"passed": 2}},
                "report_artifact_path": "candidate-report.json",
                "results": [
                    {
                        "case_id": "fixed_case",
                        "passed": True,
                        "failure_label": None,
                        "trace_artifact_path": "candidate-fixed.trace.json",
                    },
                    {
                        "case_id": "new_failure_case",
                        "passed": False,
                        "failure_label": "auth_failure",
                        "trace_artifact_path": "candidate-new.trace.json",
                    },
                    {
                        "case_id": "still_failing_case",
                        "passed": False,
                        "failure_label": "response_mismatch",
                        "trace_artifact_path": "candidate-still.trace.json",
                    },
                    {
                        "case_id": "candidate_only_case",
                        "passed": True,
                        "failure_label": None,
                        "trace_artifact_path": "candidate-only.trace.json",
                    },
                ],
            },
        )

        self.assertEqual(comparison["case_deltas"]["overlap_case_count"], 3)
        self.assertEqual(
            comparison["case_deltas"]["baseline_only_case_ids"],
            ["baseline_only_case"],
        )
        self.assertEqual(
            comparison["case_deltas"]["candidate_only_case_ids"],
            ["candidate_only_case"],
        )
        self.assertEqual(
            comparison["case_deltas"]["fixed"],
            [
                {
                    "case_id": "fixed_case",
                    "baseline_failure_label": "wrong_tool",
                    "candidate_failure_label": None,
                    "baseline_trace_artifact_path": "baseline-fixed.trace.json",
                    "candidate_trace_artifact_path": "candidate-fixed.trace.json",
                    "baseline_report_artifact_path": "baseline-report.json",
                    "candidate_report_artifact_path": "candidate-report.json",
                }
            ],
        )
        self.assertEqual(
            comparison["case_deltas"]["new_failures"],
            [
                {
                    "case_id": "new_failure_case",
                    "baseline_failure_label": None,
                    "candidate_failure_label": "auth_failure",
                    "baseline_trace_artifact_path": "baseline-new.trace.json",
                    "candidate_trace_artifact_path": "candidate-new.trace.json",
                    "baseline_report_artifact_path": "baseline-report.json",
                    "candidate_report_artifact_path": "candidate-report.json",
                }
            ],
        )
        self.assertEqual(
            comparison["case_deltas"]["still_failing"],
            [
                {
                    "case_id": "still_failing_case",
                    "baseline_failure_label": "wrong_tool",
                    "candidate_failure_label": "response_mismatch",
                    "baseline_trace_artifact_path": "baseline-still.trace.json",
                    "candidate_trace_artifact_path": "candidate-still.trace.json",
                    "baseline_report_artifact_path": "baseline-report.json",
                    "candidate_report_artifact_path": "candidate-report.json",
                }
            ],
        )
        self.assertEqual(
            comparison["case_deltas"]["failure_label_changed"],
            [
                {
                    "case_id": "still_failing_case",
                    "baseline_failure_label": "wrong_tool",
                    "candidate_failure_label": "response_mismatch",
                    "baseline_trace_artifact_path": "baseline-still.trace.json",
                    "candidate_trace_artifact_path": "candidate-still.trace.json",
                    "baseline_report_artifact_path": "baseline-report.json",
                    "candidate_report_artifact_path": "candidate-report.json",
                }
            ],
        )

    def test_comparison_artifact_aggregates_multi_trial_cases_deterministically(self):
        comparison = build_comparison_artifact(
            baseline={
                "report_artifact_path": "baseline-report.json",
                "results": [
                    {
                        "case_id": "trial_case",
                        "trial": 0,
                        "passed": False,
                        "failure_label": "wrong_tool",
                        "trace_artifact_path": "baseline-fail.trace.json",
                    },
                    {
                        "case_id": "trial_case",
                        "trial": 1,
                        "passed": True,
                        "failure_label": None,
                        "trace_artifact_path": "baseline-pass.trace.json",
                    },
                ],
            },
            candidate={
                "report_artifact_path": "candidate-report.json",
                "results": [
                    {
                        "case_id": "trial_case",
                        "trial": 0,
                        "passed": True,
                        "failure_label": None,
                        "trace_artifact_path": "candidate-pass.trace.json",
                    }
                ],
            },
        )

        self.assertEqual(
            comparison["case_deltas"]["fixed"],
            [
                {
                    "case_id": "trial_case",
                    "baseline_failure_label": "wrong_tool",
                    "candidate_failure_label": None,
                    "baseline_trace_artifact_path": "baseline-fail.trace.json",
                    "candidate_trace_artifact_path": "candidate-pass.trace.json",
                    "baseline_report_artifact_path": "baseline-report.json",
                    "candidate_report_artifact_path": "candidate-report.json",
                }
            ],
        )

    def test_comparison_artifact_skips_malformed_rows_without_passed_flag(self):
        comparison = build_comparison_artifact(
            baseline={
                "report_artifact_path": "baseline-report.json",
                "results": [
                    {
                        "case_id": "valid_case",
                        "passed": False,
                        "failure_label": "wrong_tool",
                        "trace_artifact_path": "baseline-valid.trace.json",
                    },
                    {
                        "case_id": "malformed_case",
                        "failure_label": "wrong_tool",
                        "trace_artifact_path": "baseline-malformed.trace.json",
                    },
                ],
            },
            candidate={
                "report_artifact_path": "candidate-report.json",
                "results": [
                    {
                        "case_id": "valid_case",
                        "passed": True,
                        "failure_label": None,
                        "trace_artifact_path": "candidate-valid.trace.json",
                    }
                ],
            },
        )

        self.assertEqual(
            comparison["case_deltas"]["baseline_only_case_ids"],
            [],
        )
        self.assertEqual(
            comparison["case_deltas"]["fixed"],
            [
                {
                    "case_id": "valid_case",
                    "baseline_failure_label": "wrong_tool",
                    "candidate_failure_label": None,
                    "baseline_trace_artifact_path": "baseline-valid.trace.json",
                    "candidate_trace_artifact_path": "candidate-valid.trace.json",
                    "baseline_report_artifact_path": "baseline-report.json",
                    "candidate_report_artifact_path": "candidate-report.json",
                }
            ],
        )

    def test_generalized_subset_starts_as_curated_regression_copy(self):
        curated_cases = get_cases("curated_mvp")
        generalized_cases = get_cases("generalized_mvp")

        self.assertGreater(len(generalized_cases), len(curated_cases))
        self.assertEqual({case.subset for case in curated_cases}, {"curated_mvp"})
        self.assertEqual(
            {case.subset for case in generalized_cases}, {"generalized_mvp"}
        )
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
            len(cases),
            30,
            f"generalized_mvp has {len(cases)} cases, expected at least 30",
        )
        subsets = {case.subset for case in cases}
        self.assertEqual(subsets, {"generalized_mvp"})

    def test_phase5_cases_cover_multi_item_exchange_and_user_address_write(self):
        cases = {case.case_id: case for case in get_cases("generalized_mvp")}

        exchange_case = cases["multi_item_exchange_success"]
        exchange_text = " ".join(
            message["content"] for message in exchange_case.messages
        )
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

    def test_tau_phase12_nl_evidence_defers_recovered_tool_errors_to_final_checks(self):
        case = EvalCase(
            case_id="tau_recovered_tool_error",
            category="return",
            messages=[],
            expected_user_id=None,
            expected_intent="",
            expected_tool_names=["return_delivered_order_items"],
            expected_assistant_contains="$1.00",
            expected_db_assertions={"order_id": "#W1"},
            subset="tau_phase12_nl_evidence",
        )

        label = classify_failure(
            case=case,
            authenticated_user_id="user",
            final_intent="",
            write_locks=["item:1:return"],
            actual_order_status=None,
            assistant_messages=["The total refund is $1.00."],
            tool_names=["get_order_details", "return_delivered_order_items"],
            guard_block_reasons=["non_delivered_order_cannot_be_returned"],
            tool_errors=1,
            guard_blocks=1,
            pending_action=False,
            llm_errors=0,
            confirmation_status="confirmed",
            db_assertion_failures=[],
        )

        self.assertIsNone(label)

    def test_tau_phase12_nl_evidence_still_checks_response_after_tool_errors(self):
        case = EvalCase(
            case_id="tau_recovered_tool_error_bad_response",
            category="return",
            messages=[],
            expected_user_id=None,
            expected_intent="",
            expected_tool_names=["return_delivered_order_items"],
            expected_assistant_contains="$1.00",
            expected_db_assertions={"order_id": "#W1"},
            subset="tau_phase12_nl_evidence",
        )

        label = classify_failure(
            case=case,
            authenticated_user_id="user",
            final_intent="",
            write_locks=["item:1:return"],
            actual_order_status=None,
            assistant_messages=["The return is complete."],
            tool_names=["get_order_details", "return_delivered_order_items"],
            guard_block_reasons=[],
            tool_errors=1,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="confirmed",
            db_assertion_failures=[],
        )

        self.assertEqual(label, "response_mismatch")

    def test_curated_cases_still_fail_on_tool_errors_before_final_checks(self):
        case = EvalCase(
            case_id="curated_tool_error",
            category="return",
            messages=[],
            expected_user_id="user",
            expected_intent="return",
            expected_tool_names=["return_delivered_order_items"],
            expected_assistant_contains="$1.00",
        )

        label = classify_failure(
            case=case,
            authenticated_user_id="user",
            final_intent="return",
            write_locks=["item:1:return"],
            actual_order_status=None,
            assistant_messages=["The total refund is $1.00."],
            tool_names=["return_delivered_order_items"],
            guard_block_reasons=[],
            tool_errors=1,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="confirmed",
            db_assertion_failures=[],
        )

        self.assertEqual(label, "tool_exception")

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
            # Offline demo harness is not a generalized pass-rate gate; this
            # verifies the subset still runs without mutation/tool errors.
            self.assertEqual(summary.metrics["mutation_error_rate"], 0.0)
            self.assertEqual(summary.metrics["tool_error_rate"], 0.0)

    def test_required_tool_missing_fails_classify(self):
        case = EvalCase(
            case_id="req_test",
            category="test",
            messages=[],
            expected_user_id="user",
            expected_intent="lookup",
            required_tools={"must_have_tool"},
        )

        label = classify_failure(
            case=case,
            authenticated_user_id="user",
            final_intent="lookup",
            write_locks=[],
            actual_order_status=None,
            assistant_messages=[],
            tool_names=["other_tool"],
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="not_required",
        )

        self.assertEqual(label, "required_tool_missing")

    def test_forbidden_tool_called_fails_classify(self):
        case = EvalCase(
            case_id="forbid_test",
            category="test",
            messages=[],
            expected_user_id="user",
            expected_intent="lookup",
            forbidden_tools={"dangerous_tool"},
        )

        label = classify_failure(
            case=case,
            authenticated_user_id="user",
            final_intent="lookup",
            write_locks=[],
            actual_order_status=None,
            assistant_messages=[],
            tool_names=["dangerous_tool", "other_tool"],
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="not_required",
        )

        self.assertEqual(label, "forbidden_tool_called")

    def test_eval_case_result_defaults_to_scripted_backend(self):
        result = _result("test_case", 0)
        self.assertEqual(result.eval_backend, "scripted_offline_demo")

    def test_eval_case_result_carries_llm_metrics(self):
        result = _result("test_case", 0)
        result.llm_token_usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        result.llm_loop_iterations = 3

        self.assertEqual(result.eval_backend, "scripted_offline_demo")
        self.assertEqual(result.llm_token_usage["total_tokens"], 150)
        self.assertEqual(result.llm_loop_iterations, 3)

    def test_eval_run_summary_has_eval_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            summary = CuratedEvalRunner(
                config=config,
                artifact_dir=Path(tmp),
            ).run(subset="curated_mvp", trials=1)
        self.assertEqual(summary.eval_backend, "scripted_offline_demo")

    def test_eval_backend_names_scripted_offline_demo_for_ci_harness(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            runner = CuratedEvalRunner(config=config, artifact_dir=Path(tmp))

            self.assertEqual(runner._eval_backend(), "scripted_offline_demo")

    def test_required_and_forbidden_pass_when_satisfied(self):
        case = EvalCase(
            case_id="both_test",
            category="test",
            messages=[],
            expected_user_id="user",
            expected_intent="lookup",
            required_tools={"good_tool"},
            forbidden_tools={"bad_tool"},
        )

        label = classify_failure(
            case=case,
            authenticated_user_id="user",
            final_intent="lookup",
            write_locks=[],
            actual_order_status=None,
            assistant_messages=[],
            tool_names=["good_tool", "neutral_tool"],
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="not_required",
        )

        self.assertIsNone(label)

    def test_session_state_has_no_phase4_compat_fields(self):
        from app.agent.models import SessionState

        state = SessionState(session_id="test")
        for removed_field in ("current_intent", "slots", "policy_decision", "risk_level"):
            with self.subTest(field=removed_field):
                with self.assertRaises(AttributeError):
                    getattr(state, removed_field)

    def test_live_flag_passes_provider_none_to_runtime(self):
        """Verify live=False produces scripted eval_backend and runs all cases."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            summary = CuratedEvalRunner(
                config=config,
                artifact_dir=Path(tmp),
                live=False,
            ).run(subset="curated_mvp", trials=1)
            self.assertEqual(summary.eval_backend, "scripted_offline_demo")
            self.assertEqual(summary.case_count, 11)

    def test_eval_backend_in_summary_matches_live_flag(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            summary = CuratedEvalRunner(
                config=config,
                artifact_dir=Path(tmp),
                live=False,
            ).run(subset="curated_mvp", trials=1)
            self.assertEqual(summary.eval_backend, "scripted_offline_demo")
            for result in summary.results:
                self.assertEqual(result.eval_backend, "scripted_offline_demo")

    def test_replay_run_sets_eval_backend_and_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            artifact_dir = Path(tmp)
            case = next(
                item for item in get_cases("curated_mvp")
                if item.case_id == "transfer_to_human"
            )
            trace_dir = artifact_dir / "replay"
            _trace_fixture_for_case(trace_dir, case)

            with patch("app.eval.runner.get_cases", return_value=[case]):
                summary = CuratedEvalRunner(
                    config=config,
                    artifact_dir=artifact_dir,
                    replay_trace_dir=trace_dir,
                ).run(subset="curated_mvp", trials=1)

            payload = json.loads(
                Path(summary.result_artifact_path).read_text(encoding="utf-8")
            )
            report = json.loads(
                Path(summary.report_artifact_path).read_text(encoding="utf-8")
            )

        self.assertEqual(summary.eval_backend, "replay")
        self.assertEqual(summary.case_count, 1)
        self.assertEqual(summary.results[0].eval_backend, "replay")
        self.assertEqual(payload["eval_backend"], "replay")
        self.assertEqual(payload["results"][0]["eval_backend"], "replay")
        self.assertEqual(report["eval_backend"], "replay")

    def test_replay_run_indexes_runs_subdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            artifact_dir = Path(tmp)
            case = next(
                item for item in get_cases("curated_mvp")
                if item.case_id == "transfer_to_human"
            )
            trace_dir = artifact_dir / "replay"
            _trace_fixture_for_case(trace_dir / "runs", case)

            with patch("app.eval.runner.get_cases", return_value=[case]):
                summary = CuratedEvalRunner(
                    config=config,
                    artifact_dir=artifact_dir,
                    replay_trace_dir=trace_dir,
                ).run(subset="curated_mvp", trials=1)

        self.assertEqual(summary.eval_backend, "replay")
        self.assertEqual(summary.case_count, 1)
        self.assertEqual(summary.results[0].case_id, case.case_id)

    def test_replay_case_builds_one_case_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            artifact_dir = Path(tmp)
            case = next(
                item for item in get_cases("curated_mvp")
                if item.case_id == "transfer_to_human"
            )
            trace_path = _trace_fixture_for_case(artifact_dir, case)

            summary = CuratedEvalRunner(
                config=config,
                artifact_dir=artifact_dir,
                replay_case_path=trace_path,
            ).run()

            payload = json.loads(
                Path(summary.result_artifact_path).read_text(encoding="utf-8")
            )

        self.assertEqual(summary.eval_backend, "replay")
        self.assertEqual(summary.case_count, 1)
        self.assertEqual(summary.results[0].case_id, case.case_id)
        self.assertEqual(summary.results[0].eval_backend, "replay")
        self.assertEqual(payload["results"][0]["case_id"], case.case_id)
        self.assertEqual(payload["results"][0]["trace_artifact_path"], str(trace_path))

    def test_replay_case_requires_llm_responses(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            artifact_dir = Path(tmp)
            case = next(
                item for item in get_cases("curated_mvp")
                if item.case_id == "transfer_to_human"
            )
            trace_path = _trace_fixture_for_case(
                artifact_dir,
                case,
                trace_messages=[
                    *case.messages,
                    {
                        "role": "assistant",
                        "content": case.expected_assistant_contains,
                    },
                ],
                llm_responses=[],
            )

            with self.assertRaisesRegex(
                ValueError,
                "Replay trace is missing llm_responses",
            ):
                CuratedEvalRunner(
                    config=config,
                    artifact_dir=artifact_dir,
                    replay_case_path=trace_path,
                ).run()

    def test_replay_case_requires_metadata_task_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            artifact_dir = Path(tmp)
            case = next(
                item for item in get_cases("curated_mvp")
                if item.case_id == "transfer_to_human"
            )
            trace_path = _trace_fixture_for_case(artifact_dir, case)
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["metadata"].pop("task_id", None)
            trace_path.write_text(json.dumps(trace), encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "Replay trace is missing case identity metadata",
            ):
                CuratedEvalRunner(
                    config=config,
                    artifact_dir=artifact_dir,
                    replay_case_path=trace_path,
                ).run()

    def test_replay_case_missing_trace_raises_explicit_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            missing_trace = Path(tmp) / "missing-trace.json"

            with self.assertRaisesRegex(
                FileNotFoundError,
                re.escape(f"Replay trace file not found: {missing_trace}"),
            ):
                CuratedEvalRunner(
                    config=config,
                    artifact_dir=Path(tmp),
                    replay_case_path=missing_trace,
                ).run()

    def test_replay_case_resolution_searches_tau_subset(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            artifact_dir = Path(tmp)
            tau_case = EvalCase(
                case_id="tau_transfer_case",
                category="transfer",
                messages=[
                    {
                        "role": "user",
                        "content": "Please connect me to a human.",
                    }
                ],
                expected_user_id="tau_user",
                expected_intent="transfer",
                expected_tool_names=["transfer_to_human_agents"],
                subset="tau_retail_smoke",
            )
            trace_path = _trace_fixture_for_case(artifact_dir, tau_case)
            requested_subsets: list[str] = []

            def fake_get_cases(subset: str):
                requested_subsets.append(subset)
                if subset == "tau_retail_smoke":
                    return [tau_case]
                return []

            with patch("app.eval.runner.get_cases", side_effect=fake_get_cases):
                summary = CuratedEvalRunner(
                    config=config,
                    artifact_dir=artifact_dir,
                    replay_case_path=trace_path,
                ).run()

        self.assertEqual(summary.results[0].case_id, tau_case.case_id)
        self.assertIn("tau_retail_smoke", requested_subsets)

    def test_phase12_tau_subset_uses_tau_user_simulator(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            artifact_dir = Path(tmp)
            captured: dict[str, object] = {}
            case = EvalCase(
                case_id="tau_49",
                category="exchange",
                messages=[
                    {
                        "role": "user",
                        "content": "Raw converted tau instruction should not be used.",
                    }
                ],
                expected_user_id="",
                expected_intent="",
                expected_tool_names=["calculate"],
                subset="tau_phase12_schema_ready",
            )
            task = {
                "id": 49,
                "user_scenario": {
                    "instructions": {
                        "known_info": "You are Casey Morgan in zip code 10001.",
                        "reason_for_call": "You want to exchange an item.",
                    }
                },
            }

            class FakeRuntime:
                def __init__(self, *args, **kwargs):
                    self.retail_runtime = SimpleNamespace(db={})

                def run_script(
                    self,
                    *,
                    messages,
                    session_id,
                    task_id,
                    max_turns,
                    user_simulator_callback=None,
                ):
                    captured["messages"] = messages
                    captured["callback"] = user_simulator_callback
                    state = SessionState(session_id=session_id, task_id=task_id)
                    state.messages = []
                    return SimpleNamespace(
                        run_id="fake-run",
                        state=state,
                        trace_artifact_path=artifact_dir / "missing-trace.json",
                        turn_contexts=[],
                    )

            with (
                patch("app.eval.runner.AgentRuntime", FakeRuntime),
                patch("app.eval.runner._load_tau_task_by_id", return_value=task),
            ):
                CuratedEvalRunner(
                    config=config,
                    artifact_dir=artifact_dir,
                )._run_case("eval-phase12", case, 0)

        self.assertIsNotNone(captured["callback"])
        self.assertNotEqual(captured["messages"], case.messages)
        self.assertIn("I want to exchange an item", captured["messages"][0]["content"])
        self.assertIn("My name is Casey Morgan", captured["messages"][0]["content"])

    def test_replay_case_resolution_accepts_none_subset(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            artifact_dir = Path(tmp)
            case = next(
                item for item in get_cases("curated_mvp")
                if item.case_id == "transfer_to_human"
            )
            trace_path = _trace_fixture_for_case(artifact_dir, case)

            requested_subsets: list[str] = []

            def fake_get_cases(subset: str):
                requested_subsets.append(subset)
                if subset is None:
                    raise AssertionError("get_cases(None) should not be called")
                return [case]

            with patch("app.eval.runner.get_cases", side_effect=fake_get_cases):
                summary = CuratedEvalRunner(
                    config=config,
                    artifact_dir=artifact_dir,
                    replay_case_path=trace_path,
                ).run(subset=None)

        self.assertEqual(summary.results[0].case_id, case.case_id)
        self.assertEqual(summary.eval_backend, "replay")
        self.assertTrue(requested_subsets)

    def test_replay_case_does_not_seed_authenticated_user_from_final_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            artifact_dir = Path(tmp)
            case = next(
                item for item in get_cases("curated_mvp")
                if item.case_id == "transfer_to_human"
            )
            trace_path = _trace_fixture_for_case(
                artifact_dir,
                case,
                final_state_overrides={
                    "authenticated_user_id": case.expected_user_id,
                },
            )

            summary = CuratedEvalRunner(
                config=config,
                artifact_dir=artifact_dir,
                replay_case_path=trace_path,
            ).run()

        self.assertIsNone(summary.results[0].authenticated_user_id)
        self.assertEqual(summary.results[0].failure_label, "auth_failure")

    def test_replay_case_prefers_successful_write_order_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            artifact_dir = Path(tmp)
            case = EvalCase(
                case_id="replay_write_status_case",
                category="cancel",
                messages=[
                    {
                        "role": "user",
                        "content": "My email is test@example.com. Cancel order #W1 because no longer needed.",
                    }
                ],
                expected_user_id="user_1",
                expected_intent="cancel_order",
                order_id="#W1",
                expected_order_status="cancelled",
                expected_tool_names=[
                    "find_user_id_by_email",
                    "cancel_pending_order",
                ],
                subset="curated_mvp",
            )
            trace_path = _trace_fixture_for_case(
                artifact_dir,
                case,
                llm_responses=[
                    {
                        "assistant_content": "Let me verify your account.",
                        "tool_calls": [
                            {
                                "id": "call_auth",
                                "tool_name": "find_user_id_by_email",
                                "arguments": {"email": "test@example.com"},
                            }
                        ],
                        "finish_reason": "tool_calls",
                    },
                    {
                        "assistant_content": "I'll cancel the order now.",
                        "tool_calls": [
                            {
                                "id": "call_cancel",
                                "tool_name": "cancel_pending_order",
                                "arguments": {
                                    "order_id": "#W1",
                                    "reason": "no longer needed",
                                },
                            }
                        ],
                        "finish_reason": "tool_calls",
                    },
                    {
                        "assistant_content": "Your order is cancelled.",
                        "tool_calls": [],
                        "finish_reason": "stop",
                    },
                ],
                tool_calls=[
                    {
                        "tool_name": "find_user_id_by_email",
                        "arguments": {"email": "test@example.com"},
                        "tool_kind": "read",
                        "status": "success",
                        "observation": "user_1",
                    },
                    {
                        "tool_name": "cancel_pending_order",
                        "arguments": {
                            "order_id": "#W1",
                            "reason": "no longer needed",
                        },
                        "tool_kind": "write",
                        "status": "success",
                        "observation": {"order_id": "#W1", "status": "cancelled"},
                    },
                ],
                final_state_overrides={
                    "authenticated_user_id": "spoofed_user",
                    "confirmation_status": "confirmed",
                },
            )

            with patch("app.eval.runner.get_cases", return_value=[case]):
                summary = CuratedEvalRunner(
                    config=config,
                    artifact_dir=artifact_dir,
                    replay_case_path=trace_path,
                ).run()

        self.assertEqual(summary.results[0].authenticated_user_id, "user_1")
        self.assertEqual(summary.results[0].actual_order_status, "cancelled")
        self.assertTrue(summary.results[0].passed)

    def test_replay_case_replays_confirmation_yes_via_confirm_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            artifact_dir = Path(tmp)
            case = EvalCase(
                case_id="replay_confirm_yes_case",
                category="cancel",
                messages=[
                    {
                        "role": "user",
                        "content": "My email is test@example.com. Cancel order #W1 because no longer needed.",
                    },
                    {"role": "user", "content": "yes"},
                ],
                expected_user_id="user_1",
                expected_intent="cancel_order",
                order_id="#W1",
                expected_order_status="cancelled",
                expected_confirmation_status="confirmed",
                expected_tool_names=[
                    "find_user_id_by_email",
                    "cancel_pending_order",
                ],
                subset="curated_mvp",
            )
            trace_path = _trace_fixture_for_case(
                artifact_dir,
                case,
                llm_responses=[
                    {
                        "assistant_content": "Let me verify your account.",
                        "tool_calls": [
                            {
                                "id": "call_auth",
                                "tool_name": "find_user_id_by_email",
                                "arguments": {"email": "test@example.com"},
                            }
                        ],
                        "finish_reason": "tool_calls",
                    },
                    {
                        "assistant_content": "I can cancel that order for you.",
                        "tool_calls": [
                            {
                                "id": "call_cancel",
                                "tool_name": "cancel_pending_order",
                                "arguments": {
                                    "order_id": "#W1",
                                    "reason": "no longer needed",
                                },
                            }
                        ],
                        "finish_reason": "tool_calls",
                    },
                ],
                tool_calls=[
                    {
                        "tool_name": "find_user_id_by_email",
                        "arguments": {"email": "test@example.com"},
                        "tool_kind": "read",
                        "status": "success",
                        "observation": "user_1",
                    },
                    {
                        "tool_name": "cancel_pending_order",
                        "arguments": {
                            "order_id": "#W1",
                            "reason": "no longer needed",
                        },
                        "tool_kind": "write",
                        "status": "blocked",
                        "error": "explicit_confirmation_required",
                    },
                    {
                        "tool_name": "cancel_pending_order",
                        "arguments": {
                            "order_id": "#W1",
                            "reason": "no longer needed",
                        },
                        "tool_kind": "write",
                        "status": "success",
                        "observation": {"order_id": "#W1", "status": "cancelled"},
                        "resource_lock": "order:#W1:cancel",
                    },
                ],
                final_state_overrides={
                    "confirmation_status": "confirmed",
                },
            )

            with patch("app.eval.runner.get_cases", return_value=[case]):
                summary = CuratedEvalRunner(
                    config=config,
                    artifact_dir=artifact_dir,
                    replay_case_path=trace_path,
                ).run()

        self.assertTrue(summary.results[0].passed)
        self.assertEqual(summary.results[0].actual_confirmation_status, "confirmed")
        self.assertEqual(summary.results[0].actual_order_status, "cancelled")
        self.assertEqual(summary.results[0].tool_call_count, 3)
        self.assertEqual(summary.results[0].write_locks, ["order:#W1:cancel"])

    def test_replay_case_unknown_confirmation_falls_back_to_agent_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            artifact_dir = Path(tmp)
            case = EvalCase(
                case_id="replay_confirm_unknown_case",
                category="cancel",
                messages=[
                    {
                        "role": "user",
                        "content": "My email is test@example.com. Cancel order #W1 because no longer needed.",
                    },
                    {"role": "user", "content": "Can you explain a bit more?"},
                ],
                expected_user_id="user_1",
                expected_intent="cancel_order",
                expected_confirmation_status="required",
                expected_tool_names=[
                    "find_user_id_by_email",
                    "cancel_pending_order",
                ],
                subset="curated_mvp",
            )
            trace_path = _trace_fixture_for_case(
                artifact_dir,
                case,
                llm_responses=[
                    {
                        "assistant_content": "Let me verify your account.",
                        "tool_calls": [
                            {
                                "id": "call_auth",
                                "tool_name": "find_user_id_by_email",
                                "arguments": {"email": "test@example.com"},
                            }
                        ],
                        "finish_reason": "tool_calls",
                    },
                    {
                        "assistant_content": "I can cancel that order for you.",
                        "tool_calls": [
                            {
                                "id": "call_cancel",
                                "tool_name": "cancel_pending_order",
                                "arguments": {
                                    "order_id": "#W1",
                                    "reason": "no longer needed",
                                },
                            }
                        ],
                        "finish_reason": "tool_calls",
                    },
                    {
                        "assistant_content": "Please answer yes or no so I know whether to proceed.",
                        "tool_calls": [],
                        "finish_reason": "stop",
                    },
                ],
                tool_calls=[
                    {
                        "tool_name": "find_user_id_by_email",
                        "arguments": {"email": "test@example.com"},
                        "tool_kind": "read",
                        "status": "success",
                        "observation": "user_1",
                    },
                    {
                        "tool_name": "cancel_pending_order",
                        "arguments": {
                            "order_id": "#W1",
                            "reason": "no longer needed",
                        },
                        "tool_kind": "write",
                        "status": "blocked",
                        "error": "explicit_confirmation_required",
                    },
                ],
                final_state_overrides={
                    "confirmation_status": "confirmed",
                },
            )

            with patch("app.eval.runner.get_cases", return_value=[case]):
                summary = CuratedEvalRunner(
                    config=config,
                    artifact_dir=artifact_dir,
                    replay_case_path=trace_path,
                ).run()

        self.assertEqual(summary.results[0].actual_confirmation_status, "required")
        self.assertEqual(summary.results[0].message_count, 4)
        self.assertEqual(summary.results[0].tool_call_count, 2)
        self.assertEqual(summary.results[0].failure_label, "confirmation_failure")

    def test_replay_case_uses_replayed_confirmation_status_not_final_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            artifact_dir = Path(tmp)
            case = EvalCase(
                case_id="replay_confirm_denied_case",
                category="cancel",
                messages=[
                    {
                        "role": "user",
                        "content": "My email is test@example.com. Cancel order #W1 because no longer needed.",
                    },
                    {"role": "user", "content": "no"},
                ],
                expected_user_id="user_1",
                expected_intent="cancel_order",
                expected_confirmation_status="confirmed",
                expected_tool_names=[
                    "find_user_id_by_email",
                    "cancel_pending_order",
                ],
                subset="curated_mvp",
            )
            trace_path = _trace_fixture_for_case(
                artifact_dir,
                case,
                llm_responses=[
                    {
                        "assistant_content": "Let me verify your account.",
                        "tool_calls": [
                            {
                                "id": "call_auth",
                                "tool_name": "find_user_id_by_email",
                                "arguments": {"email": "test@example.com"},
                            }
                        ],
                        "finish_reason": "tool_calls",
                    },
                    {
                        "assistant_content": "I can cancel that order for you.",
                        "tool_calls": [
                            {
                                "id": "call_cancel",
                                "tool_name": "cancel_pending_order",
                                "arguments": {
                                    "order_id": "#W1",
                                    "reason": "no longer needed",
                                },
                            }
                        ],
                        "finish_reason": "tool_calls",
                    },
                ],
                tool_calls=[
                    {
                        "tool_name": "find_user_id_by_email",
                        "arguments": {"email": "test@example.com"},
                        "tool_kind": "read",
                        "status": "success",
                        "observation": "user_1",
                    },
                    {
                        "tool_name": "cancel_pending_order",
                        "arguments": {
                            "order_id": "#W1",
                            "reason": "no longer needed",
                        },
                        "tool_kind": "write",
                        "status": "blocked",
                        "error": "explicit_confirmation_required",
                    },
                ],
                final_state_overrides={
                    "confirmation_status": "confirmed",
                },
            )

            with patch("app.eval.runner.get_cases", return_value=[case]):
                summary = CuratedEvalRunner(
                    config=config,
                    artifact_dir=artifact_dir,
                    replay_case_path=trace_path,
                ).run()

        self.assertEqual(summary.results[0].actual_confirmation_status, "denied")
        self.assertEqual(
            summary.results[0].failure_label,
            "confirmation_status_mismatch",
        )

    def test_replay_case_raises_on_unconsumed_tool_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            artifact_dir = Path(tmp)
            case = EvalCase(
                case_id="replay_orphan_tool_case",
                category="transfer",
                messages=[
                    {
                        "role": "user",
                        "content": "My email is test@example.com. Please transfer me to a human.",
                    }
                ],
                expected_user_id="user_1",
                expected_intent="transfer",
                expected_tool_names=[
                    "find_user_id_by_email",
                    "transfer_to_human_agents",
                ],
                subset="curated_mvp",
            )
            trace_path = _trace_fixture_for_case(
                artifact_dir,
                case,
                llm_responses=[
                    {
                        "assistant_content": "Let me verify your account.",
                        "tool_calls": [
                            {
                                "id": "call_auth",
                                "tool_name": "find_user_id_by_email",
                                "arguments": {"email": "test@example.com"},
                            }
                        ],
                        "finish_reason": "tool_calls",
                    },
                    {
                        "assistant_content": "I'll transfer you now.",
                        "tool_calls": [
                            {
                                "id": "call_transfer",
                                "tool_name": "transfer_to_human_agents",
                                "arguments": {"summary": "user requested human support"},
                            }
                        ],
                        "finish_reason": "tool_calls",
                    },
                    {
                        "assistant_content": "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.",
                        "tool_calls": [],
                        "finish_reason": "stop",
                    },
                ],
                tool_calls=[
                    {
                        "tool_name": "find_user_id_by_email",
                        "arguments": {"email": "test@example.com"},
                        "tool_kind": "read",
                        "status": "success",
                        "observation": "user_1",
                    },
                    {
                        "tool_name": "transfer_to_human_agents",
                        "arguments": {"summary": "user requested human support"},
                        "tool_kind": "generic",
                        "status": "success",
                        "observation": "transferred",
                    },
                    {
                        "tool_name": "get_order_details",
                        "arguments": {"order_id": "#W999"},
                        "tool_kind": "read",
                        "status": "success",
                        "observation": {"order_id": "#W999", "status": "pending"},
                    },
                ],
            )

            with patch("app.eval.runner.get_cases", return_value=[case]):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "Unconsumed replay tool results remain",
                ):
                    CuratedEvalRunner(
                        config=config,
                        artifact_dir=artifact_dir,
                        replay_case_path=trace_path,
                    ).run()


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
    llm_token_usage: dict | None = None,
    llm_loop_iterations: int = 0,
    auto_load_count: int = 0,
    premature_refusal_corrected_count: int = 0,
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
        llm_token_usage=llm_token_usage,
        llm_loop_iterations=llm_loop_iterations,
        auto_load_count=auto_load_count,
        premature_refusal_corrected_count=premature_refusal_corrected_count,
    )


def _trace_fixture_for_case(
    base_dir: Path,
    case: EvalCase,
    *,
    trace_messages: list[dict] | None = None,
    llm_responses: list[dict] | None = None,
    tool_calls: list[dict] | None = None,
    final_state_overrides: dict | None = None,
) -> Path:
    trace_dir = Path(base_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / f"{case.case_id}.json"
    if llm_responses is None:
        llm_responses = [
            {
                "assistant_content": "Let me transfer you.",
                "tool_calls": [
                    {
                        "id": "call_transfer",
                        "tool_name": "transfer_to_human_agents",
                        "arguments": {"summary": "user requested a human agent"},
                    }
                ],
                "finish_reason": "tool_calls",
            },
            {
                "assistant_content": (
                    "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
                ),
                "tool_calls": [],
                "finish_reason": "stop",
            },
        ]
    if tool_calls is None:
        tool_calls = [
            {
                "tool_name": "transfer_to_human_agents",
                "arguments": {"summary": "user requested a human agent"},
                "tool_kind": "generic",
                "status": "success",
                "observation": "transferred",
            }
        ]
    final_state = {
        "session_id": f"trace-{case.case_id}",
        "task_id": case.case_id,
        "authenticated_user_id": case.expected_user_id,
        "confirmation_status": "not_required",
        "write_locks": [],
        "termination_reason": "script_completed",
    }
    if final_state_overrides:
        final_state.update(final_state_overrides)
    if trace_messages is None:
        trace_messages = case.messages
    trace = {
        "run_id": f"replay-{case.case_id}",
        "metadata": {
            "task_id": case.case_id,
            "initial_db_hash": "same",
            "final_db_hash": "same",
        },
        "messages": trace_messages,
        "llm_responses": llm_responses,
        "tool_calls": tool_calls,
        "final_state": final_state,
    }
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    return trace_path


class TimingTests(unittest.TestCase):
    def test_step_durations_populated_after_run(self):
        import tempfile

        from app.agent.runtime import AgentRuntime
        from app.config import resolve_config

        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            runtime = AgentRuntime(config, require_llm=False)
            result = runtime.run_script(
                messages=[{"role": "user", "content": "find my order"}]
            )
            state = result.state
            durations = state.step_durations
            self.assertGreater(
                len(durations), 0, "step_durations should be non-empty after a run"
            )
            for node_name, ms in durations.items():
                self.assertGreaterEqual(
                    ms, 0, f"{node_name} duration should be >= 0, got {ms}"
                )
                self.assertIsInstance(
                    ms, float, f"{node_name} duration should be float"
                )

    def test_trace_contains_timing_section(self):
        from app.agent.models import SessionState
        from app.ops.tracing import build_trace_payload

        state = SessionState(session_id="test")
        state.step_durations = {"identity_resolver": 5.0, "run_logger": 1.0}
        trace = build_trace_payload(run_id="test", state=state, metadata={})
        self.assertIn("timing", trace)
        timing = trace["timing"]
        self.assertIn("step_durations_ms", timing)
        self.assertIn("llm_calls", timing)
        self.assertEqual(timing["total_ms"], 6.0)
        self.assertEqual(timing["llm_total_ms"], 0.0)

    def test_timing_fields_serializable(self):
        import json

        from app.agent.models import SessionState

        state = SessionState(session_id="test")
        state.step_durations = {"node1": 1.5}
        dumped = state.model_dump()
        self.assertIn("step_durations", dumped)
        encoded = json.dumps(dumped)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["step_durations"], {"node1": 1.5})


if __name__ == "__main__":
    unittest.main()
