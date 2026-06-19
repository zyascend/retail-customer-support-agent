from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from app.eval.bad_case_store import BadCaseStore, build_bad_case_record
from app.eval.cases import EvalCase, get_cases
from app.eval.golden_set import GoldenSet
from app.eval.live_triage import summarize_failure
from app.eval.runner import CuratedEvalRunner
from app.synthetic.generator import SyntheticDBGenerator
from app.synthetic.language_variation import build_language_variants
from app.synthetic.oracle import derive_oracle, select_entity_for_variant


@dataclass(frozen=True)
class Flywheel:
    golden_set: GoldenSet
    bad_case_store: BadCaseStore


@dataclass(frozen=True)
class CollectResult:
    report_path: Path
    output_path: Path
    subset: str
    failed_results: int
    collected_count: int
    deduped_count: int
    case_ids: list[str]


@dataclass(frozen=True)
class GenerateResult:
    source_path: Path
    output_path: Path
    input_count: int
    generated_count: int
    skipped_case_ids: list[str]
    generated_case_ids: list[str]


@dataclass(frozen=True)
class PromoteResult:
    case_id: str
    confirmed: bool
    added_to_golden: bool
    already_in_golden: bool
    record_marked_promoted: bool
    failure_label: str | None
    root_cause: str
    suggested_next_action: str | None


@dataclass(frozen=True)
class CheckCaseStatus:
    case_id: str
    status: str
    passed: bool | None
    failure_label: str | None


@dataclass(frozen=True)
class CheckResult:
    statuses: list[CheckCaseStatus]
    has_regressions: bool
    exit_code: int


def build_flywheel(*, golden_path: Path, bad_cases_path: Path) -> Flywheel:
    return Flywheel(
        golden_set=GoldenSet.load(golden_path),
        bad_case_store=BadCaseStore.from_path(bad_cases_path),
    )


def collect(
    *,
    flywheel: Flywheel,
    report_path: Path,
    subset: str | None = None,
    recorded_on: date | None = None,
) -> CollectResult:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    report_subset = subset or str(payload.get("subset") or "")
    if not report_subset:
        raise ValueError("subset is required when report does not include one")

    cases_by_id = {case.case_id: case for case in get_cases(report_subset)}
    failed_results = [
        result
        for result in list(payload.get("results") or [])
        if isinstance(result, Mapping) and result.get("passed") is not True
    ]

    collected_date = recorded_on or date.today()
    path = flywheel.bad_case_store.path_for_date(collected_date)
    existing_records = flywheel.bad_case_store.load(path)
    existing_by_id = {record.case_id: record for record in existing_records}

    collected_case_ids: list[str] = []
    for result in failed_results:
        case_id = str(result.get("case_id") or "")
        case = cases_by_id.get(case_id)
        if case is None:
            continue
        enriched = dict(result)
        enriched.setdefault("subset", report_subset)
        existing_by_id[case_id] = build_bad_case_record(
            case=case,
            triage_summary=summarize_failure(enriched),
            recorded_on=collected_date,
        )
        collected_case_ids.append(case_id)

    flywheel.bad_case_store.write(path, list(existing_by_id.values()))
    unique_collected_ids = sorted(set(collected_case_ids))
    return CollectResult(
        report_path=report_path,
        output_path=path,
        subset=report_subset,
        failed_results=len(failed_results),
        collected_count=len(unique_collected_ids),
        deduped_count=max(0, len(collected_case_ids) - len(unique_collected_ids)),
        case_ids=unique_collected_ids,
    )


def generate(*, bad_cases_path: Path) -> GenerateResult:
    store = BadCaseStore.from_path(bad_cases_path.parent)
    records = store.load(bad_cases_path)
    generated_cases: list[EvalCase] = []
    skipped_case_ids: list[str] = []

    for record in records:
        case = record.case
        if not case.variant_type or case.seed is None:
            skipped_case_ids.append(case.case_id)
            continue
        generated_cases.extend(_build_gate_variants(case))

    output_path = bad_cases_path.with_name(f"{bad_cases_path.stem}_variants.yaml")
    _write_cases_yaml(output_path, generated_cases)
    return GenerateResult(
        source_path=bad_cases_path,
        output_path=output_path,
        input_count=len(records),
        generated_count=len(generated_cases),
        skipped_case_ids=skipped_case_ids,
        generated_case_ids=[case.case_id for case in generated_cases],
    )


def promote(
    *,
    flywheel: Flywheel,
    bad_cases_path: Path,
    case_id: str,
    confirmed: bool,
) -> PromoteResult:
    records = flywheel.bad_case_store.load(bad_cases_path)
    record = next((item for item in records if item.case_id == case_id), None)
    if record is None:
        raise ValueError(f"bad case not found: {case_id}")
    if not confirmed:
        raise ValueError("promotion requires confirmed=True")

    existing_ids = {case.case_id for case in flywheel.golden_set.cases}
    already_in_golden = case_id in existing_ids
    added_to_golden = False
    if not already_in_golden:
        flywheel.golden_set.cases.append(record.case)
        flywheel.golden_set.save()
        added_to_golden = True

    record_marked_promoted = flywheel.bad_case_store.mark_promoted(
        case_id,
        recorded_date=date.fromisoformat(record.recorded_on),
    )
    return PromoteResult(
        case_id=case_id,
        confirmed=True,
        added_to_golden=added_to_golden,
        already_in_golden=already_in_golden,
        record_marked_promoted=record_marked_promoted,
        failure_label=record.triage.failure_label,
        root_cause=record.triage.root_cause,
        suggested_next_action=record.triage.suggested_next_action,
    )


def check(
    *,
    runner: CuratedEvalRunner | None = None,
    run_golden: Callable[[], Any] | None = None,
) -> CheckResult:
    golden_cases = get_cases("golden")
    if not golden_cases:
        return CheckResult(statuses=[], has_regressions=False, exit_code=0)

    if run_golden is not None:
        summary = run_golden()
    else:
        if runner is None:
            raise ValueError("runner or run_golden is required")
        summary = runner.run(subset="golden")

    golden_case_ids = {case.case_id for case in golden_cases}
    results = list(getattr(summary, "results", []) or [])
    statuses: list[CheckCaseStatus] = []
    has_regressions = False
    seen: set[str] = set()

    for result in results:
        case_id = str(_result_value(result, "case_id") or "")
        passed = _result_value(result, "passed")
        failure_label = _result_value(result, "failure_label")
        seen.add(case_id)

        if case_id not in golden_case_ids:
            status = "unexpected_pass" if passed is True else "regression"
            if status == "regression":
                has_regressions = True
        else:
            status = "pass" if passed is True else "regression"
            if status == "regression":
                has_regressions = True

        statuses.append(
            CheckCaseStatus(
                case_id=case_id,
                status=status,
                passed=bool(passed) if passed is not None else None,
                failure_label=str(failure_label) if failure_label is not None else None,
            )
        )

    for case in golden_cases:
        if case.case_id not in seen:
            has_regressions = True
            statuses.append(
                CheckCaseStatus(
                    case_id=case.case_id,
                    status="missing",
                    passed=None,
                    failure_label=None,
                )
            )

    return CheckResult(
        statuses=sorted(statuses, key=lambda item: item.case_id),
        has_regressions=has_regressions,
        exit_code=1 if has_regressions else 0,
    )


def _build_gate_variants(case: EvalCase) -> list[EvalCase]:
    world = SyntheticDBGenerator.from_seed(case.seed)
    entities = select_entity_for_variant(world, case.variant_type)
    variants = build_language_variants(case.messages, case.variant_type, entities)
    oracle = derive_oracle(world, entities, case.variant_type)
    built: list[EvalCase] = []
    for variant in variants:
        if not variant.gate:
            continue
        built.append(
            EvalCase(
                case_id=f"{case.case_id}{variant.suffix}",
                category=case.category,
                messages=variant.messages,
                expected_user_id=oracle.expected_user_id,
                expected_intent=oracle.expected_intent,
                order_id=oracle.order_id,
                expected_write_lock=oracle.expected_write_lock,
                expected_order_status=oracle.expected_order_status,
                expected_confirmation_status=oracle.expected_confirmation_status,
                expected_guard_block_reason=oracle.expected_guard_block_reason,
                expected_no_write=oracle.expected_no_write,
                expected_tool_names=oracle.expected_tool_names,
                expected_tool_sequence=oracle.expected_tool_sequence,
                expected_db_assertions=oracle.expected_db_assertions,
                max_turns=case.max_turns,
                subset="golden",
                capability=case.capability,
                policy_area=case.policy_area,
                scenario_family=case.scenario_family,
                variant_type=case.variant_type,
                language_variation_level=variant.level,
                seed=case.seed,
                required_tools=set(case.required_tools),
                forbidden_tools=set(case.forbidden_tools),
            )
        )
    return built


def _write_cases_yaml(path: Path, cases: list[EvalCase]) -> None:
    from app.eval.golden_set import _serialize_case

    path.write_text(
        yaml.safe_dump(
            {"cases": [_serialize_case(case) for case in cases]},
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def _result_value(result: Any, key: str) -> Any:
    if isinstance(result, Mapping):
        return result.get(key)
    return getattr(result, key, None)
