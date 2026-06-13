from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from typing import Any, Dict, Iterable, List, Optional, Protocol

EVAL_REPORT_SCHEMA_VERSION = "phase2.eval_report.v1"
EVAL_RUN_SUMMARY_SCHEMA_VERSION = "phase2.eval_run_summary.v1"
EVAL_COMPARISON_SCHEMA_VERSION = "phase2.eval_comparison.v1"


class MetricResult(Protocol):
    case_id: str
    category: str
    trial: int
    passed: bool
    failure_label: Optional[str]
    trace_artifact_path: str
    expected_order_status: Optional[str]
    actual_order_status: Optional[str]
    expected_guard_block_reason: Optional[str]
    actual_guard_block_reasons: List[str]
    initial_db_hash: Optional[str]
    final_db_hash: Optional[str]
    db_changed: bool
    duration_seconds: float
    tool_call_count: int
    successful_tool_calls: int
    failed_tool_calls: int
    blocked_tool_calls: int
    tool_errors: int
    guard_blocks: int
    mutation_detected: bool
    unexpected_mutation: bool
    db_accuracy_passed: Optional[bool]
    db_accuracy_basis: Optional[str]
    failure_category: Optional[str]
    failure_summary: Optional[str]
    expected_actual_diff: Dict[str, Any]
    replay_metadata: Dict[str, Any]


class MetricCase(Protocol):
    case_id: str
    expected_no_write: bool
    expected_order_status: Optional[str]


def apply_case_diagnostics(result: Any, case: MetricCase) -> None:
    result.mutation_detected = _mutation_detected(result)
    result.db_changed = result.mutation_detected
    result.unexpected_mutation = bool(
        case.expected_no_write and (result.write_locks or result.mutation_detected)
    )
    db_passed, db_basis = db_accuracy_for_case(result, case)
    result.db_accuracy_passed = db_passed
    result.db_accuracy_basis = db_basis
    result.failure_category = failure_category(result.failure_label)
    result.failure_summary = failure_summary(result)
    result.expected_actual_diff = expected_actual_diff(result)


def db_accuracy_for_case(
    result: MetricResult, case: MetricCase
) -> tuple[Optional[bool], Optional[str]]:
    if case.expected_order_status:
        return (
            result.actual_order_status == case.expected_order_status,
            "order_status",
        )
    if case.expected_no_write and not case.expected_order_status:
        if result.initial_db_hash is None or result.final_db_hash is None:
            return False, "db_hash_no_write"
        return result.initial_db_hash == result.final_db_hash, "db_hash_no_write"
    return None, None


def compute_metrics(results: Iterable[MetricResult]) -> Dict[str, Any]:
    result_list = list(results)
    total = len(result_list)
    passed = sum(1 for result in result_list if result.passed)
    db_checkable = [
        result for result in result_list if result.db_accuracy_passed is not None
    ]
    total_tool_calls = sum(result.tool_call_count for result in result_list)
    successful_tool_calls = sum(result.successful_tool_calls for result in result_list)
    failed_tool_calls = sum(result.failed_tool_calls for result in result_list)
    blocked_tool_calls = sum(result.blocked_tool_calls for result in result_list)
    guard_blocks = sum(result.guard_blocks for result in result_list)
    mutation_errors = sum(1 for result in result_list if result.unexpected_mutation)
    db_changed_count = sum(1 for result in result_list if result.db_changed)
    durations = [result.duration_seconds for result in result_list]

    return {
        "pass_1": _rate(passed, total),
        "pass_k": _pass_k(result_list),
        "db_accuracy": _rate(
            sum(1 for result in db_checkable if result.db_accuracy_passed),
            len(db_checkable),
        ),
        "db_accuracy_count": sum(
            1 for result in db_checkable if result.db_accuracy_passed
        ),
        "db_accuracy_denominator": len(db_checkable),
        "tool_call_success_rate": _rate(successful_tool_calls, total_tool_calls),
        "tool_error_rate": _rate(failed_tool_calls, total_tool_calls),
        "guard_block_rate": _rate(guard_blocks, total_tool_calls),
        "mutation_error_rate": _rate(mutation_errors, total),
        "db_changed_rate": _rate(db_changed_count, total),
        "average_turns": _average_turns(result_list),
        "average_latency_seconds": round(sum(durations) / total, 3) if total else 0.0,
        "result_count": total,
        "passed_count": passed,
        "tool_call_count": total_tool_calls,
        "successful_tool_calls": successful_tool_calls,
        "failed_tool_calls": failed_tool_calls,
        "blocked_tool_calls": blocked_tool_calls,
        "mutation_error_count": mutation_errors,
        "db_changed_count": db_changed_count,
    }


def build_failure_analysis(results: Iterable[MetricResult]) -> Dict[str, Any]:
    result_list = list(results)
    labels = Counter(result.failure_label or "passed" for result in result_list)
    category_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    for result in result_list:
        category_counts[result.category][result.failure_label or "passed"] += 1

    failed_cases = [
        {
            "case_id": result.case_id,
            "trial": result.trial,
            "category": result.category,
            "failure_label": result.failure_label,
            "failure_category": failure_category(result.failure_label),
            "failure_summary": result.failure_summary,
            "trace_artifact_path": result.trace_artifact_path,
            "replay_metadata": result.replay_metadata,
            "expected_order_status": result.expected_order_status,
            "actual_order_status": result.actual_order_status,
            "expected_actual_diff": result.expected_actual_diff,
            "expected_guard_block_reason": result.expected_guard_block_reason,
            "actual_guard_block_reasons": result.actual_guard_block_reasons,
            "tool_errors": result.tool_errors,
            "guard_blocks": result.guard_blocks,
            "unexpected_mutation": result.unexpected_mutation,
        }
        for result in result_list
        if not result.passed
    ]

    # ── Generalization-specific aggregations ──
    family_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    variant_type_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    language_level_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    for result in result_list:
        family = getattr(result, "scenario_family", None) or "unknown"
        variant = getattr(result, "variant_type", None) or "unknown"
        language_level = (
            getattr(result, "language_variation_level", None) or "unknown"
        )
        family_counts[family][result.failure_label or "passed"] += 1
        variant_type_counts[variant][result.failure_label or "passed"] += 1
        language_level_counts[language_level][result.failure_label or "passed"] += 1

    # failure_source classification
    failure_source_map = {
        "wrong_intent": "parsing",
        "auth_failure": "parsing",
        "wrong_tool": "planning",
        "wrong_tool_sequence": "planning",
        "llm_json_failure": "planning",
        "expected_guard_block_missing": "guard",
        "guard_blocked": "guard",
        "tool_exception": "tool_mutation",
        "unexpected_mutation": "tool_mutation",
        "mutation_missing": "tool_mutation",
        "db_state_mismatch": "tool_mutation",
        "db_assertion_mismatch": "tool_mutation",
        "confirmation_status_mismatch": "response",
        "confirmation_failure": "response",
        "response_mismatch": "response",
    }
    source_counts: Counter[str] = Counter()
    for result in result_list:
        if result.failure_label:
            source = failure_source_map.get(result.failure_label, "unknown")
            source_counts[source] += 1

    return {
        "failure_label_counts": dict(sorted(labels.items())),
        "failure_category_counts": dict(
            sorted(
                Counter(
                    failure_category(result.failure_label)
                    for result in result_list
                    if result.failure_label
                ).items()
            )
        ),
        "category_counts": {
            category: dict(sorted(counts.items()))
            for category, counts in sorted(category_counts.items())
        },
        "failed_cases": failed_cases,
        # 🆕 Generalization dimensions
        "family_counts": {
            family: dict(sorted(counts.items()))
            for family, counts in sorted(family_counts.items())
        },
        "variant_type_counts": {
            variant: dict(sorted(counts.items()))
            for variant, counts in sorted(variant_type_counts.items())
        },
        "language_variation_level_counts": {
            language_level: dict(sorted(counts.items()))
            for language_level, counts in sorted(language_level_counts.items())
        },
        "failure_source_counts": dict(sorted(source_counts.items())),
    }


def build_report_artifact(summary: Any) -> Dict[str, Any]:
    return {
        "schema_version": EVAL_REPORT_SCHEMA_VERSION,
        "report_type": "phase2_eval_report",
        "artifact_created_at": summary.created_at,
        "eval_run_id": summary.eval_run_id,
        "created_at": summary.created_at,
        "subset": summary.subset,
        "trials": summary.trials,
        "agent_strategy": summary.agent_strategy,
        "model": summary.model,
        "llm_required": summary.llm_required,
        "llm_timeout_seconds": summary.llm_timeout_seconds,
        "llm_max_retries": summary.llm_max_retries,
        "dataset_root": summary.dataset_root,
        "dataset_db_path": summary.dataset_db_path,
        "code_commit": summary.code_commit,
        "prompt_metadata": summary.prompt_metadata,
        "result_artifact_path": summary.result_artifact_path,
        "report_artifact_path": summary.report_artifact_path,
        "metrics": summary.metrics,
        "failure_analysis": summary.failure_analysis,
        "results": [asdict(result) for result in summary.results],
    }


def build_comparison_artifact(
    *,
    baseline: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    baseline_metrics = baseline.get("metrics", {})
    candidate_metrics = candidate.get("metrics", {})
    metric_names = sorted(set(baseline_metrics) | set(candidate_metrics))
    metric_deltas = {
        name: {
            "baseline": baseline_metrics.get(name),
            "candidate": candidate_metrics.get(name),
            "delta": _numeric_delta(
                baseline_metrics.get(name),
                candidate_metrics.get(name),
            ),
        }
        for name in metric_names
    }
    return {
        "schema_version": EVAL_COMPARISON_SCHEMA_VERSION,
        "report_type": "phase2_eval_comparison",
        "baseline_eval_run_id": baseline.get("eval_run_id"),
        "candidate_eval_run_id": candidate.get("eval_run_id"),
        "baseline_model": baseline.get("model"),
        "candidate_model": candidate.get("model"),
        "baseline_code_commit": baseline.get("code_commit"),
        "candidate_code_commit": candidate.get("code_commit"),
        "metric_deltas": metric_deltas,
        "failure_label_counts": {
            "baseline": baseline.get("failure_analysis", {}).get(
                "failure_label_counts", {}
            ),
            "candidate": candidate.get("failure_analysis", {}).get(
                "failure_label_counts", {}
            ),
        },
    }


def failure_category(label: Optional[str]) -> Optional[str]:
    if label is None:
        return None
    mapping = {
        "auth_failure": "auth_failure",
        "wrong_intent": "intent_misclassification",
        "wrong_tool": "wrong_tool",
        "tool_exception": "tool_exception_not_recovered",
        "llm_json_failure": "policy_reasoning_error",
        "expected_guard_block_missing": "policy_reasoning_error",
        "guard_blocked": "policy_reasoning_error",
        "confirmation_status_mismatch": "confirmation_error",
        "confirmation_failure": "confirmation_error",
        "unexpected_mutation": "policy_reasoning_error",
        "mutation_missing": "wrong_tool",
        "db_state_mismatch": "wrong_tool_arguments",
        "response_mismatch": "incorrect_user_message",
    }
    return mapping.get(label, label)


def failure_summary(result: MetricResult) -> Optional[str]:
    if result.failure_label is None:
        return None
    category = failure_category(result.failure_label) or result.failure_label
    diff = expected_actual_diff(result)
    if diff:
        changed = ", ".join(sorted(diff))
        return f"{category}: mismatch in {changed}"
    return category


def expected_actual_diff(result: MetricResult) -> Dict[str, Dict[str, Any]]:
    diff: Dict[str, Dict[str, Any]] = {}
    if (
        result.expected_order_status is not None
        and result.actual_order_status != result.expected_order_status
    ):
        diff["order_status"] = {
            "expected": result.expected_order_status,
            "actual": result.actual_order_status,
        }
    if result.expected_guard_block_reason is not None:
        if result.expected_guard_block_reason not in result.actual_guard_block_reasons:
            diff["guard_block_reason"] = {
                "expected": result.expected_guard_block_reason,
                "actual": result.actual_guard_block_reasons,
            }
    if result.unexpected_mutation:
        diff["mutation"] = {
            "expected": "no_write",
            "actual": "write_or_db_hash_changed",
        }
    return diff


def _mutation_detected(result: MetricResult) -> bool:
    return bool(
        result.initial_db_hash
        and result.final_db_hash
        and result.initial_db_hash != result.final_db_hash
    )


def _pass_k(results: List[MetricResult]) -> float:
    if not results:
        return 0.0
    by_case: Dict[str, List[MetricResult]] = defaultdict(list)
    for result in results:
        by_case[result.case_id].append(result)
    passing_cases = sum(
        1
        for case_results in by_case.values()
        if all(result.passed for result in case_results)
    )
    return _rate(passing_cases, len(by_case))


def _average_turns(results: List[MetricResult]) -> float:
    if not results:
        return 0.0
    return round(
        sum(result.trial_turn_count for result in results) / len(results),
        3,
    )


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _numeric_delta(baseline: Any, candidate: Any) -> Optional[float]:
    if not isinstance(baseline, (int, float)) or not isinstance(
        candidate, (int, float)
    ):
        return None
    return candidate - baseline
