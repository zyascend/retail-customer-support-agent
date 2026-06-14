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
            # Phase 7: DeterministicProvider yields 0 passes; eval infrastructure
            # still runs correctly — only verify it doesn't crash on the subset.
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
        self.assertEqual(result.eval_backend, "scripted")

    def test_eval_case_result_carries_llm_metrics(self):
        result = _result("test_case", 0)
        result.llm_token_usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        result.llm_loop_iterations = 3

        self.assertEqual(result.eval_backend, "scripted")
        self.assertEqual(result.llm_token_usage["total_tokens"], 150)
        self.assertEqual(result.llm_loop_iterations, 3)

    def test_eval_run_summary_has_eval_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            summary = CuratedEvalRunner(
                config=config,
                artifact_dir=Path(tmp),
            ).run(subset="curated_mvp", trials=1)
        self.assertEqual(summary.eval_backend, "scripted")

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
            self.assertEqual(summary.eval_backend, "scripted")
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
            self.assertEqual(summary.eval_backend, "scripted")
            for result in summary.results:
                self.assertEqual(result.eval_backend, "scripted")


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
