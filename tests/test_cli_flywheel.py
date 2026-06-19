from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.cli.flywheel import flywheel_main
from app.eval.flywheel import (
    CheckCaseStatus,
    CheckResult,
    CollectResult,
    GenerateResult,
    PromoteResult,
)


def test_collect_dispatches_arguments(monkeypatch, capsys, tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_build_flywheel(*, golden_path: Path, bad_cases_path: Path):
        calls["golden_path"] = golden_path
        calls["bad_cases_path"] = bad_cases_path
        return SimpleNamespace()

    def fake_collect(*, flywheel, report_path: Path, subset: str, recorded_on):
        calls["flywheel"] = flywheel
        calls["report_path"] = report_path
        calls["subset"] = subset
        calls["recorded_on"] = recorded_on
        return CollectResult(
            report_path=report_path,
            output_path=tmp_path / "bad_cases" / "2026-06-19.yaml",
            subset=subset,
            failed_results=3,
            collected_count=2,
            deduped_count=1,
            case_ids=["case_a", "case_b"],
        )

    monkeypatch.setattr("app.eval.flywheel.build_flywheel", fake_build_flywheel)
    monkeypatch.setattr("app.eval.flywheel.collect", fake_collect)

    result = flywheel_main(
        [
            "collect",
            "--report",
            str(tmp_path / "report.json"),
            "--subset",
            "golden",
            "--date",
            "2026-06-19",
            "--golden-path",
            str(tmp_path / "golden.yaml"),
            "--bad-cases-path",
            str(tmp_path / "bad_cases"),
        ]
    )

    out = capsys.readouterr().out
    assert result == 0
    assert calls["subset"] == "golden"
    assert str(calls["recorded_on"]) == "2026-06-19"
    assert calls["report_path"] == tmp_path / "report.json"
    assert "collected_count: 2" in out


def test_generate_dispatches_input(monkeypatch, capsys, tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_generate(*, bad_cases_path: Path):
        calls["bad_cases_path"] = bad_cases_path
        return GenerateResult(
            source_path=bad_cases_path,
            output_path=tmp_path / "variants.yaml",
            input_count=2,
            generated_count=4,
            skipped_case_ids=["case_skip"],
            generated_case_ids=["a", "b", "c", "d"],
        )

    monkeypatch.setattr("app.eval.flywheel.generate", fake_generate)

    result = flywheel_main(["generate", "--input", str(tmp_path / "bad.yaml")])

    out = capsys.readouterr().out
    assert result == 0
    assert calls["bad_cases_path"] == tmp_path / "bad.yaml"
    assert "generated_count: 4" in out


def test_promote_dispatches_confirmed_path(monkeypatch, capsys, tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_build_flywheel(*, golden_path: Path, bad_cases_path: Path):
        calls["golden_path"] = golden_path
        calls["bad_cases_path"] = bad_cases_path
        return SimpleNamespace()

    def fake_promote(*, flywheel, bad_cases_path: Path, case_id: str, confirmed: bool):
        calls["flywheel"] = flywheel
        calls["input"] = bad_cases_path
        calls["case_id"] = case_id
        calls["confirmed"] = confirmed
        return PromoteResult(
            case_id=case_id,
            confirmed=confirmed,
            added_to_golden=True,
            already_in_golden=False,
            record_marked_promoted=True,
            failure_label="wrong_tool",
            root_cause="prompt_gap",
            suggested_next_action="tighten prompt",
        )

    monkeypatch.setattr("app.eval.flywheel.build_flywheel", fake_build_flywheel)
    monkeypatch.setattr("app.eval.flywheel.promote", fake_promote)

    result = flywheel_main(
        [
            "golden",
            "promote",
            "--input",
            str(tmp_path / "bad.yaml"),
            "--case-id",
            "case_123",
            "--confirm",
            "--golden-path",
            str(tmp_path / "golden.yaml"),
            "--bad-cases-path",
            str(tmp_path / "bad_cases"),
        ]
    )

    out = capsys.readouterr().out
    assert result == 0
    assert calls["case_id"] == "case_123"
    assert calls["confirmed"] is True
    assert "added_to_golden: True" in out


def test_promote_forwards_unconfirmed_path(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_build_flywheel(*, golden_path: Path, bad_cases_path: Path):
        return SimpleNamespace()

    def fake_promote(*, flywheel, bad_cases_path: Path, case_id: str, confirmed: bool):
        calls["confirmed"] = confirmed
        raise ValueError("promotion requires confirmed=True")

    monkeypatch.setattr("app.eval.flywheel.build_flywheel", fake_build_flywheel)
    monkeypatch.setattr("app.eval.flywheel.promote", fake_promote)

    result = flywheel_main(
        [
            "golden",
            "promote",
            "--input",
            str(tmp_path / "bad.yaml"),
            "--case-id",
            "case_123",
        ]
    )

    assert result == 1
    assert calls["confirmed"] is False


def test_check_returns_check_result_exit_code(monkeypatch, capsys, tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_resolve_config(**kwargs):
        calls["config_kwargs"] = kwargs
        return SimpleNamespace(name="config")

    class FakeRunner:
        def __init__(self, **kwargs):
            calls["runner_kwargs"] = kwargs

        def run(self, **kwargs):
            calls["run_kwargs"] = kwargs
            return SimpleNamespace()

    def fake_check(*, runner=None, run_golden=None):
        calls["runner"] = runner
        calls["run_golden"] = run_golden
        return CheckResult(
            statuses=[
                CheckCaseStatus(
                    case_id="golden_case",
                    status="regression",
                    passed=False,
                    failure_label="wrong_tool",
                )
            ],
            has_regressions=True,
            exit_code=1,
        )

    monkeypatch.setattr("app.cli.flywheel.resolve_config", fake_resolve_config)
    monkeypatch.setattr("app.cli.flywheel.CuratedEvalRunner", FakeRunner)
    monkeypatch.setattr("app.eval.flywheel.check", fake_check)

    result = flywheel_main(
        [
            "check",
            "--artifact-dir",
            str(tmp_path / "artifacts"),
            "--tau3-retail-root",
            str(tmp_path / "tau3"),
            "--tau2-bench-root",
            str(tmp_path / "tau2"),
            "--require-llm",
            "--live",
            "--max-workers",
            "7",
            "--seed",
            "99",
            "--no-progress",
        ]
    )

    out = capsys.readouterr().out
    assert result == 1
    assert calls["config_kwargs"]["artifact_dir"] == str(tmp_path / "artifacts")
    assert calls["runner_kwargs"]["artifact_dir"] == tmp_path / "artifacts"
    assert calls["runner_kwargs"]["require_llm"] is True
    assert calls["runner_kwargs"]["live"] is True
    assert calls["runner"] is None
    assert calls["run_golden"] is not None
    calls["run_golden"]()
    assert calls["run_kwargs"] == {"subset": "golden", "max_workers": 7, "seed": 99}
    assert "has_regressions: True" in out


def test_check_json_output(monkeypatch, capsys):
    def fake_resolve_config(**kwargs):
        return SimpleNamespace(name="config")

    class FakeRunner:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            return SimpleNamespace()

    def fake_check(*, runner=None, run_golden=None):
        return CheckResult(
            statuses=[
                CheckCaseStatus(
                    case_id="golden_case",
                    status="pass",
                    passed=True,
                    failure_label=None,
                )
            ],
            has_regressions=False,
            exit_code=0,
        )

    monkeypatch.setattr("app.cli.flywheel.resolve_config", fake_resolve_config)
    monkeypatch.setattr("app.cli.flywheel.CuratedEvalRunner", FakeRunner)
    monkeypatch.setattr("app.eval.flywheel.check", fake_check)

    result = flywheel_main(["check", "--json", "--no-progress"])

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert result == 0
    assert payload["exit_code"] == 0
    assert payload["statuses"][0]["case_id"] == "golden_case"


def test_missing_command_returns_parser_error(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        flywheel_main([])

    err = capsys.readouterr().err
    assert exc_info.value.code == 2
    assert "usage:" in err


if __name__ == "__main__":
    pytest.main([__file__])
