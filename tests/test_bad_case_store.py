from __future__ import annotations

from datetime import date

from app.eval.bad_case_store import BadCaseStore, build_bad_case_record
from app.eval.cases import EvalCase


def _case(case_id: str = "bad_case_1") -> EvalCase:
    return EvalCase(
        case_id=case_id,
        category="guard",
        messages=[{"role": "user", "content": "Cancel order #W123."}],
        expected_user_id="user_1",
        expected_intent="cancel_order",
        order_id="#W123",
        expected_tool_names=["cancel_pending_order"],
        required_tools={"cancel_pending_order"},
        forbidden_tools={"modify_user_address"},
    )


def _triage_summary(*, summary: str = "Wrong tool called") -> dict[str, object]:
    return {
        "bucket": "tool_selection",
        "root_cause": "prompt_gap",
        "failure_label": "wrong_tool",
        "failure_summary": summary,
        "suggested_next_action": "Tighten tool instructions.",
        "tool_names": ["find_user_id_by_email", "modify_user_address"],
        "tool_mismatches": {"missing_required_tools": ["cancel_pending_order"]},
        "expected_actual_diff": {"actual_tool_names": ["modify_user_address"]},
        "triage_bundle": {"ignored": True},
        "final_response": "bulky response omitted",
    }


def test_bad_case_record_yaml_roundtrip(tmp_path) -> None:
    store = BadCaseStore.from_path(tmp_path / "cases" / "bad_cases")
    recorded_date = date(2026, 6, 19)
    record = build_bad_case_record(
        case=_case(),
        triage_summary=_triage_summary(),
        recorded_on=recorded_date,
    )

    path = store.upsert(record, recorded_date=recorded_date)
    loaded = store.load(path)

    assert path == tmp_path / "cases" / "bad_cases" / "2026-06-19.yaml"
    assert loaded == [record]
    assert loaded[0].triage.failure_summary == "Wrong tool called"
    assert loaded[0].case.required_tools == {"cancel_pending_order"}
    assert loaded[0].case.forbidden_tools == {"modify_user_address"}
    assert not hasattr(loaded[0].triage, "triage_bundle")


def test_upsert_dedupes_by_case_id(tmp_path) -> None:
    store = BadCaseStore.from_path(tmp_path / "cases" / "bad_cases")
    recorded_date = date(2026, 6, 19)
    first = build_bad_case_record(
        case=_case("duplicate_case"),
        triage_summary=_triage_summary(summary="First summary"),
        recorded_on=recorded_date,
    )
    second = build_bad_case_record(
        case=_case("duplicate_case"),
        triage_summary=_triage_summary(summary="Updated summary"),
        recorded_on=recorded_date,
    )

    store.upsert(first, recorded_date=recorded_date)
    store.upsert(second, recorded_date=recorded_date)
    loaded = store.load_for_date(recorded_date)

    assert len(loaded) == 1
    assert loaded[0].case_id == "duplicate_case"
    assert loaded[0].triage.failure_summary == "Updated summary"


def test_mark_promoted_updates_existing_record_and_persists(tmp_path) -> None:
    store = BadCaseStore.from_path(tmp_path / "cases" / "bad_cases")
    recorded_date = date(2026, 6, 19)
    record = build_bad_case_record(
        case=_case("promote_me"),
        triage_summary=_triage_summary(),
        recorded_on=recorded_date,
    )
    store.upsert(record, recorded_date=recorded_date)

    updated = store.mark_promoted("promote_me", recorded_date=recorded_date)
    reloaded = store.load_for_date(recorded_date)
    loaded = store.find_by_case_id("promote_me", recorded_date=recorded_date)

    assert updated is True
    assert loaded is not None
    assert loaded.promoted is True
    assert reloaded[0].promoted is True
