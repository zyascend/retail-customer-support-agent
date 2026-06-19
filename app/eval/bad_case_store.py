from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import yaml

from app.eval.cases import EvalCase


_CASE_FIELD_NAMES = {field.name for field in EvalCase.__dataclass_fields__.values()}


def _compact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if value is not None and value != [] and value != {}
    }


def _serialize_case(case: EvalCase) -> dict[str, Any]:
    data = _compact_mapping(asdict(case))
    data["required_tools"] = sorted(str(name) for name in case.required_tools)
    data["forbidden_tools"] = sorted(str(name) for name in case.forbidden_tools)
    return _compact_mapping(data)


def _deserialize_case(data: Mapping[str, Any]) -> EvalCase:
    unknown_fields = sorted(set(data) - _CASE_FIELD_NAMES)
    if unknown_fields:
        raise ValueError(f"bad case 'case' contains unknown fields: {unknown_fields}")
    payload = {name: data[name] for name in _CASE_FIELD_NAMES if name in data}
    payload["required_tools"] = set(str(name) for name in data.get("required_tools") or [])
    payload["forbidden_tools"] = set(
        str(name) for name in data.get("forbidden_tools") or []
    )
    return EvalCase(**payload)


@dataclass(frozen=True)
class BadCaseTriage:
    bucket: str
    root_cause: str
    failure_label: str | None = None
    failure_category: str | None = None
    failure_summary: str | None = None
    suggested_next_action: str | None = None
    tool_names: list[str] = field(default_factory=list)
    tool_mismatches: dict[str, Any] = field(default_factory=dict)
    actual_guard_block_reasons: list[str] = field(default_factory=list)
    db_assertion_failures: list[str] = field(default_factory=list)
    expected_actual_diff: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BadCaseTriage":
        return cls(
            bucket=str(data.get("bucket") or ""),
            root_cause=str(data.get("root_cause") or ""),
            failure_label=_optional_str(data.get("failure_label")),
            failure_category=_optional_str(data.get("failure_category")),
            failure_summary=_optional_str(data.get("failure_summary")),
            suggested_next_action=_optional_str(data.get("suggested_next_action")),
            tool_names=[str(name) for name in list(data.get("tool_names") or [])],
            tool_mismatches=dict(data.get("tool_mismatches") or {}),
            actual_guard_block_reasons=[
                str(reason) for reason in list(data.get("actual_guard_block_reasons") or [])
            ],
            db_assertion_failures=[
                str(item) for item in list(data.get("db_assertion_failures") or [])
            ],
            expected_actual_diff=dict(data.get("expected_actual_diff") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return _compact_mapping(asdict(self))


@dataclass(frozen=True)
class BadCaseRecord:
    case: EvalCase
    triage: BadCaseTriage
    recorded_on: str
    promoted: bool = False

    @property
    def case_id(self) -> str:
        return self.case.case_id

    @classmethod
    def from_case(
        cls,
        *,
        case: EvalCase,
        triage: BadCaseTriage,
        recorded_on: str,
        promoted: bool = False,
    ) -> "BadCaseRecord":
        return cls(case=case, triage=triage, recorded_on=recorded_on, promoted=promoted)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BadCaseRecord":
        case_data = data.get("case")
        triage_data = data.get("triage")
        if not isinstance(case_data, Mapping):
            raise ValueError("bad case record must contain a 'case' mapping")
        if not isinstance(triage_data, Mapping):
            raise ValueError("bad case record must contain a 'triage' mapping")
        top_level_case_id = data.get("case_id")
        if top_level_case_id is not None and str(top_level_case_id) != str(
            case_data.get("case_id") or ""
        ):
            raise ValueError("bad case record case_id mismatch")
        return cls(
            case=_deserialize_case(case_data),
            triage=BadCaseTriage.from_dict(triage_data),
            recorded_on=str(data.get("recorded_on") or ""),
            promoted=bool(data.get("promoted", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "recorded_on": self.recorded_on,
            "promoted": self.promoted,
            "case": _serialize_case(self.case),
            "triage": self.triage.to_dict(),
        }


@dataclass(frozen=True)
class BadCaseStore:
    root: Path

    @classmethod
    def from_path(cls, path: Path) -> "BadCaseStore":
        return cls(root=path.expanduser())

    def path_for_date(self, recorded_date: date) -> Path:
        return self.root / f"{recorded_date.isoformat()}.yaml"

    def load(self, path: Path) -> list[BadCaseRecord]:
        if not path.exists():
            return []
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("bad case yaml must contain a mapping at the top level")
        raw_records = data.get("bad_cases", [])
        if not isinstance(raw_records, list):
            raise ValueError("bad case yaml 'bad_cases' must be a list")
        return [BadCaseRecord.from_dict(record) for record in raw_records]

    def write(self, path: Path, records: list[BadCaseRecord]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"bad_cases": [record.to_dict() for record in records]}
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def load_for_date(self, recorded_date: date) -> list[BadCaseRecord]:
        return self.load(self.path_for_date(recorded_date))

    def find_by_case_id(self, case_id: str, *, recorded_date: date) -> BadCaseRecord | None:
        for record in self.load_for_date(recorded_date):
            if record.case_id == case_id:
                return record
        return None

    def upsert(self, record: BadCaseRecord, *, recorded_date: date) -> Path:
        path = self.path_for_date(recorded_date)
        records = self.load(path)
        deduped: list[BadCaseRecord] = []
        replaced = False
        for current in records:
            if current.case_id == record.case_id:
                deduped.append(record)
                replaced = True
            else:
                deduped.append(current)
        if not replaced:
            deduped.append(record)
        self.write(path, deduped)
        return path

    def mark_promoted(self, case_id: str, *, recorded_date: date) -> bool:
        path = self.path_for_date(recorded_date)
        records = self.load(path)
        updated = False
        rewritten: list[BadCaseRecord] = []
        for record in records:
            if record.case_id == case_id and not record.promoted:
                rewritten.append(
                    BadCaseRecord(
                        case=record.case,
                        triage=record.triage,
                        recorded_on=record.recorded_on,
                        promoted=True,
                    )
                )
                updated = True
            else:
                rewritten.append(record)
        if updated:
            self.write(path, rewritten)
        return updated


def build_bad_case_record(
    *,
    case: EvalCase,
    triage_summary: Mapping[str, Any],
    recorded_on: date,
) -> BadCaseRecord:
    triage = BadCaseTriage.from_dict(triage_summary)
    return BadCaseRecord.from_case(
        case=case,
        triage=triage,
        recorded_on=recorded_on.isoformat(),
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
