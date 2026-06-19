from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
        raise ValueError(f"golden case contains unknown fields: {unknown_fields}")
    payload = {name: data[name] for name in _CASE_FIELD_NAMES if name in data}
    payload["required_tools"] = set(str(name) for name in data.get("required_tools") or [])
    payload["forbidden_tools"] = set(
        str(name) for name in data.get("forbidden_tools") or []
    )
    return EvalCase(**payload)


@dataclass(frozen=True)
class GoldenSet:
    path: Path
    cases: list[EvalCase] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "GoldenSet":
        if not path.exists():
            raise FileNotFoundError(f"golden set file not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("golden.yaml must contain a mapping at the top level")
        cases = data.get("cases", [])
        if not isinstance(cases, list):
            raise ValueError("golden.yaml 'cases' must be a list")
        loaded_cases: list[EvalCase] = []
        for index, case in enumerate(cases):
            if not isinstance(case, Mapping):
                raise ValueError(f"golden case at index {index} must be a mapping")
            loaded_cases.append(_deserialize_case(case))
        return cls(path=path, cases=loaded_cases)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"cases": [_serialize_case(case) for case in self.cases]}
        self.path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
