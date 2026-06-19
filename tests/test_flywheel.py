from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.eval.bad_case_store import BadCaseStore, build_bad_case_record
from app.eval.cases import EvalCase
from app.eval.flywheel import Flywheel, check, collect, generate, promote
from app.eval.golden_set import GoldenSet


def _case(
    case_id: str,
    *,
    subset: str = "synthetic_seeded_v1",
    variant_type: str | None = None,
    seed: int | None = None,
) -> EvalCase:
    return EvalCase(
        case_id=case_id,
        category="cancel",
        messages=[
            {
                "role": "user",
                "content": "My email is test@example.com. Cancel order #W123 because no longer needed.",
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="user_1",
        expected_intent="cancel_order",
        order_id="#W123",
        expected_write_lock="order:#W123:cancel",
        expected_order_status="cancelled",
        expected_confirmation_status="confirmed",
        expected_tool_names=["cancel_pending_order"],
        subset=subset,
        variant_type=variant_type,
        language_variation_level="base" if variant_type else None,
        seed=seed,
    )


def _triage_summary() -> dict[str, object]:
    return {
        "bucket": "tool_selection",
        "root_cause": "prompt_gap",
        "failure_label": "wrong_tool",
        "failure_summary": "Wrong tool called",
        "suggested_next_action": "Tighten tool instructions.",
    }


def test_collect_filters_failures_rehydrates_cases_and_dedupes(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "subset": "synthetic_seeded_v1",
                "results": [
                    {"case_id": "collect_me", "passed": False, "failure_label": "wrong_tool"},
                    {"case_id": "collect_me", "passed": False, "failure_label": "wrong_tool"},
                    {"case_id": "passed_case", "passed": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    bad_case_store = BadCaseStore.from_path(tmp_path / "bad_cases")
    golden_path = tmp_path / "golden.yaml"
    golden_path.write_text("cases: []\n", encoding="utf-8")
    flywheel = Flywheel(
        golden_set=GoldenSet.load(golden_path),
        bad_case_store=bad_case_store,
    )

    monkeypatch.setattr(
        "app.eval.flywheel.get_cases",
        lambda subset: [_case("collect_me", subset=subset, variant_type="cancel_success", seed=100)],
    )
    monkeypatch.setattr(
        "app.eval.flywheel.summarize_failure",
        lambda result: {
            "bucket": "tool_selection",
            "root_cause": "prompt_gap",
            "failure_label": result.get("failure_label"),
            "failure_summary": "summarized",
            "suggested_next_action": "tighten prompt",
        },
    )

    result = collect(
        flywheel=flywheel,
        report_path=report_path,
        recorded_on=date(2026, 6, 19),
    )
    stored = bad_case_store.load(result.output_path)

    assert result.failed_results == 2
    assert result.collected_count == 1
    assert result.deduped_count == 1
    assert result.case_ids == ["collect_me"]
    assert len(stored) == 1
    assert stored[0].case.case_id == "collect_me"
    assert stored[0].triage.failure_summary == "summarized"


def test_generate_skips_non_synthetic_and_writes_gate_variants(tmp_path) -> None:
    store = BadCaseStore.from_path(tmp_path / "bad_cases")
    recorded_date = date(2026, 6, 19)
    synthetic_case = _case(
        "shipping_express_s200", variant_type="shipping_success_express", seed=200
    )
    curated_case = _case("handwritten_case", subset="curated_mvp")
    path = store.path_for_date(recorded_date)
    store.write(
        path,
        [
            build_bad_case_record(
                case=synthetic_case,
                triage_summary=_triage_summary(),
                recorded_on=recorded_date,
            ),
            build_bad_case_record(
                case=curated_case,
                triage_summary=_triage_summary(),
                recorded_on=recorded_date,
            ),
        ],
    )

    result = generate(bad_cases_path=path)
    payload = GoldenSet.load(result.output_path)

    assert result.generated_count == 3
    assert result.skipped_case_ids == ["handwritten_case"]
    assert [case.language_variation_level for case in payload.cases] == ["base", "L1", "L2"]
    assert all(case.variant_type == "shipping_success_express" for case in payload.cases)
    assert all(case.seed == 200 for case in payload.cases)
    assert all(case.subset == "golden" for case in payload.cases)


def test_promote_requires_confirmation_and_is_idempotent(tmp_path) -> None:
    store = BadCaseStore.from_path(tmp_path / "bad_cases")
    recorded_date = date(2026, 6, 19)
    case = _case("promote_me", variant_type="cancel_success", seed=100)
    bad_case_path = store.path_for_date(recorded_date)
    store.write(
        bad_case_path,
        [
            build_bad_case_record(
                case=case,
                triage_summary=_triage_summary(),
                recorded_on=recorded_date,
            )
        ],
    )
    golden_path = tmp_path / "golden.yaml"
    golden_path.write_text("cases: []\n", encoding="utf-8")
    flywheel = Flywheel(
        golden_set=GoldenSet.load(golden_path),
        bad_case_store=store,
    )

    with pytest.raises(ValueError, match="confirmed=True"):
        promote(
            flywheel=flywheel,
            bad_cases_path=bad_case_path,
            case_id="promote_me",
            confirmed=False,
        )

    first = promote(
        flywheel=flywheel,
        bad_cases_path=bad_case_path,
        case_id="promote_me",
        confirmed=True,
    )
    second = promote(
        flywheel=flywheel,
        bad_cases_path=bad_case_path,
        case_id="promote_me",
        confirmed=True,
    )
    reloaded = GoldenSet.load(golden_path)
    stored = store.load(bad_case_path)

    assert first.added_to_golden is True
    assert first.already_in_golden is False
    assert first.record_marked_promoted is True
    assert second.added_to_golden is False
    assert second.already_in_golden is True
    assert second.record_marked_promoted is False
    assert [item.case_id for item in reloaded.cases] == ["promote_me"]
    assert stored[0].promoted is True


def test_check_reports_pass_regression_missing_and_unexpected_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.eval.flywheel.get_cases",
        lambda subset: [_case("case_pass", subset="golden"), _case("case_missing", subset="golden")],
    )
    summary = SimpleNamespace(
        results=[
            {"case_id": "case_pass", "passed": True, "failure_label": None},
            {"case_id": "case_regression", "passed": False, "failure_label": "wrong_tool"},
            {"case_id": "case_extra", "passed": True, "failure_label": None},
        ]
    )

    result = check(run_golden=lambda: summary)
    statuses = {item.case_id: item.status for item in result.statuses}

    assert result.has_regressions is True
    assert result.exit_code == 1
    assert statuses["case_pass"] == "pass"
    assert statuses["case_regression"] == "regression"
    assert statuses["case_missing"] == "missing"
    assert statuses["case_extra"] == "unexpected_pass"


def test_check_failing_unexpected_case_trips_gate_without_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.eval.flywheel.get_cases",
        lambda subset: [_case("case_pass", subset="golden")],
    )
    summary = SimpleNamespace(
        results=[
            {"case_id": "case_pass", "passed": True, "failure_label": None},
            {"case_id": "case_unknown_fail", "passed": False, "failure_label": "wrong_tool"},
        ]
    )

    result = check(run_golden=lambda: summary)
    statuses = {item.case_id: item.status for item in result.statuses}

    assert result.has_regressions is True
    assert result.exit_code == 1
    assert statuses["case_pass"] == "pass"
    assert statuses["case_unknown_fail"] == "regression"
