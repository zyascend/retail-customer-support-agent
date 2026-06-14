# CLI Replay And Baseline Compare Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `phase2-eval` so it can replay a whole trace directory, replay a single case trace as a one-case eval report, and compare two reports with summary plus case-level deltas.

**Architecture:** Reuse the existing `CuratedEvalRunner`, `TraceReplayHarness`, eval report schema, and comparison builder. Add replay as a first-class eval backend, then enrich the compare artifact/output with case-level deltas and persist a comparison JSON artifact under `artifacts/phase2/comparisons/`.

**Tech Stack:** Python, `argparse`, existing Phase 2 eval runner/report pipeline, `TraceReplayHarness`, `pytest`, `ruff`

---

## File Structure

- Modify: `app/cli/eval.py`
  - Add `--replay` / `--replay-case` CLI flags.
  - Enforce flag exclusivity and required combinations.
  - Write richer compare output and comparison artifact.
- Modify: `app/eval/runner.py`
  - Add replay execution modes for whole-run trace directories and single-case trace files.
  - Mark replay outputs with `eval_backend="replay"`.
  - Reuse standard summary/report writing.
- Modify: `app/eval/metrics.py`
  - Extend `build_comparison_artifact()` with case-level deltas and overlap metadata.
  - Add helpers for case indexing and delta classification.
- Modify: `app/agent/replay.py`
  - Expose just enough trace metadata access to support eval-runner replay without duplicating trace parsing logic.
- Modify: `tests/test_eval_runner.py`
  - Add deterministic replay-backend tests and richer comparison-artifact tests.
- Modify: `tests/test_trace_replay_harness.py`
  - Add small helpers or fixtures if replay-runner tests need stable trace metadata.
- Create: `tests/test_eval_cli.py`
  - Cover CLI flag validation and compare output shape at the command-entry level.

## Task 1: Add Replay Backend To Eval Runner

**Files:**
- Modify: `app/eval/runner.py`
- Modify: `app/agent/replay.py`
- Test: `tests/test_eval_runner.py`

- [ ] **Step 1: Write the failing replay-backend tests in `tests/test_eval_runner.py`**

Append focused tests that describe the new runner behavior:

```python
def test_replay_run_sets_eval_backend_and_writes_report(self):
    with tempfile.TemporaryDirectory() as tmp:
        config = resolve_config(artifact_dir=tmp)
        trace_dir = Path(tmp) / "traces" / "seeded"
        trace_dir.mkdir(parents=True)
        # copy or synthesize one valid trace file under trace_dir / "runs"
        summary = CuratedEvalRunner(
            config=config,
            artifact_dir=Path(tmp),
            replay_trace_dir=trace_dir,
        ).run(subset="curated_mvp", trials=1)
        self.assertEqual(summary.eval_backend, "replay")
        self.assertEqual(
            {result.eval_backend for result in summary.results},
            {"replay"},
        )
        report = json.loads(Path(summary.report_artifact_path).read_text())
        self.assertEqual(report["eval_backend"], "replay")


def test_replay_case_builds_one_case_report(self):
    with tempfile.TemporaryDirectory() as tmp:
        config = resolve_config(artifact_dir=tmp)
        trace_path = Path(tmp) / "single-trace.json"
        trace_path.write_text(json.dumps(_trace_fixture_for_case("lookup_pending_order")))
        summary = CuratedEvalRunner(
            config=config,
            artifact_dir=Path(tmp),
            replay_case_path=trace_path,
        ).run()
        self.assertEqual(summary.case_count, 1)
        self.assertEqual(len(summary.results), 1)
        self.assertEqual(summary.results[0].case_id, "lookup_pending_order")
        self.assertEqual(summary.eval_backend, "replay")
```

- [ ] **Step 2: Run the new replay-backend tests to verify RED**

Run:

```bash
uv run python -m pytest tests/test_eval_runner.py -k "replay_run_sets_eval_backend or replay_case_builds_one_case_report" -q
```

Expected:

- FAIL because `CuratedEvalRunner` does not yet accept `replay_trace_dir` / `replay_case_path`.

- [ ] **Step 3: Extend `CuratedEvalRunner.__init__` with replay inputs**

Update the runner signature and state:

```python
class CuratedEvalRunner:
    def __init__(
        self,
        *,
        config: AppConfig,
        artifact_dir: Path = DEFAULT_EVAL_ARTIFACT_DIR,
        require_llm: bool = False,
        live: bool = False,
        replay_trace_dir: Optional[Path] = None,
        replay_case_path: Optional[Path] = None,
        progress_callback: Optional[Callable[[str, EvalCaseResult], None]] = None,
    ) -> None:
        self.config = config
        self.artifact_dir = artifact_dir
        self.require_llm = require_llm
        self.live = live
        self.replay_trace_dir = replay_trace_dir
        self.replay_case_path = replay_case_path
        self.progress_callback = progress_callback
```

- [ ] **Step 4: Add replay-mode branching at the start of `run()`**

Add mode selection before the normal case loop:

```python
if self.replay_case_path is not None:
    results = [self._run_replay_case(eval_run_id, self.replay_case_path)]
elif self.replay_trace_dir is not None:
    if subset is None:
        raise ValueError("subset is required when replaying a trace directory")
    cases = get_cases(subset)
    results = self._run_replay_subset(eval_run_id, cases)
else:
    cases = get_cases(subset)
    # existing live/scripted path remains unchanged
```

Keep the existing summary/report writing path shared.

- [ ] **Step 5: Implement `_run_replay_subset()` in `app/eval/runner.py`**

Add a helper that resolves each expected case trace and replays it:

```python
def _run_replay_subset(
    self,
    eval_run_id: str,
    cases: List[EvalCase],
) -> List[EvalCaseResult]:
    results: List[EvalCaseResult] = []
    for case in cases:
        trace_path = self._resolve_trace_for_case(case.case_id, 0)
        results.append(self._run_replay_case(eval_run_id, trace_path, case=case, trial=0))
    return results
```

Use `trial` loops when you wire the final version; do not hard-code `0` outside the first green step.

- [ ] **Step 6: Implement `_run_replay_case()` in `app/eval/runner.py`**

Build `EvalCaseResult` by replaying through `TraceReplayHarness`:

```python
def _run_replay_case(
    self,
    eval_run_id: str,
    trace_path: Path,
    *,
    case: Optional[EvalCase] = None,
    trial: Optional[int] = None,
) -> EvalCaseResult:
    trace = self._load_trace(trace_path)
    resolved_case = case or self._case_from_trace(trace)
    resolved_trial = 0 if trial is None else trial
    runtime = AgentRuntime(self.config, provider=DeterministicProvider(), offline_demo=True)
    harness = TraceReplayHarness(trace_path, runtime.registry)
    session = SessionState(
        session_id=f"{eval_run_id}-{resolved_case.case_id}-trial-{resolved_trial}",
        task_id=resolved_case.case_id,
    )
    replay_turn = harness.replay(
        session,
        self._trace_user_message(trace),
        context_builder=runtime._context_builder,
    )
    ...
```

Do not invent a second result schema. Populate normal `EvalCaseResult` fields and set `eval_backend="replay"`.

- [ ] **Step 7: Add trace-loading helpers and explicit error messages**

Implement helpers in `app/eval/runner.py`:

```python
def _load_trace(self, trace_path: Path) -> Dict[str, Any]:
    if not trace_path.exists():
        raise FileNotFoundError(f"Replay trace not found: {trace_path}")
    with trace_path.open(encoding="utf-8") as file:
        return json.load(file)


def _resolve_trace_for_case(self, case_id: str, trial: int) -> Path:
    runs_dir = Path(self.replay_trace_dir) / "runs"
    matches = sorted(runs_dir.glob(f"*{case_id}*trial-{trial}.json"))
    if not matches:
        raise FileNotFoundError(
            f"Missing replay trace for case={case_id} trial={trial} under {runs_dir}"
        )
    return matches[0]


def _case_from_trace(self, trace: Dict[str, Any]) -> EvalCase:
    case_id = (
        trace.get("metadata", {}).get("task_id")
        or trace.get("task_id")
    )
    if not case_id:
        raise ValueError("Replay trace missing case id metadata")
    for subset_name in ("curated_mvp", "generalized_mvp", "synthetic_seeded_v1"):
        matches = [case for case in get_cases(subset_name) if case.case_id == case_id]
        if matches:
            return matches[0]
    raise ValueError(f"Unknown replay case_id: {case_id}")


def _trace_user_message(self, trace: Dict[str, Any]) -> str:
    for message in trace.get("messages", []):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    raise ValueError("Replay trace missing initial user message")
```

Add a small helper in `app/agent/replay.py` if you need a reusable trace metadata accessor instead of duplicating path/JSON logic.

- [ ] **Step 8: Mark replay outputs as `eval_backend=\"replay\"`**

Update:

- `EvalRunSummary(eval_backend=...)`
- each replay `EvalCaseResult(eval_backend=...)`
- progress placeholder when replay is active

Use:

```python
eval_backend = (
    "replay" if self.replay_trace_dir or self.replay_case_path
    else "live" if self.live
    else "scripted"
)
```

- [ ] **Step 9: Run the replay-backend tests to verify GREEN**

Run:

```bash
uv run python -m pytest tests/test_eval_runner.py -k "replay_run_sets_eval_backend or replay_case_builds_one_case_report" -q
```

Expected:

- PASS

- [ ] **Step 10: Commit the replay-backend slice**

```bash
git add app/eval/runner.py app/agent/replay.py tests/test_eval_runner.py tests/test_trace_replay_harness.py
git commit -m "feat: add replay backend to phase2 eval runner"
```

## Task 2: Extend The CLI For Replay Modes

**Files:**
- Modify: `app/cli/eval.py`
- Test: `tests/test_eval_cli.py`

- [ ] **Step 1: Write the failing CLI tests in `tests/test_eval_cli.py`**

Create `tests/test_eval_cli.py` with focused flag-behavior tests:

```python
from __future__ import annotations

import pytest

from app.cli.eval import eval_main


def test_replay_and_live_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        eval_main(["--subset", "curated_mvp", "--live", "--replay", "artifacts/x"])


def test_replay_case_does_not_require_subset(tmp_path):
    trace = tmp_path / "trace.json"
    trace.write_text("{}")
    code = eval_main(["--replay-case", str(trace), "--json"])
    assert code in {0, 1}
```

Use `pytest.raises(SystemExit)` for parser errors and `unittest.mock.patch` around `CuratedEvalRunner` when you want to avoid running the real runner.

- [ ] **Step 2: Run the CLI tests to verify RED**

Run:

```bash
uv run python -m pytest tests/test_eval_cli.py -q
```

Expected:

- FAIL because replay flags and validation do not exist yet.

- [ ] **Step 3: Add replay flags in `app/cli/eval.py`**

Add arguments:

```python
parser.add_argument("--replay", help="Replay a whole trace directory.")
parser.add_argument("--replay-case", help="Replay a single trace JSON file.")
```

- [ ] **Step 4: Add CLI validation rules**

Before constructing the runner, add:

```python
if args.replay and args.replay_case:
    parser.error("--replay and --replay-case are mutually exclusive")
if (args.replay or args.replay_case) and args.live:
    parser.error("--live cannot be combined with replay mode")
if args.replay and not args.subset:
    parser.error("--subset is required with --replay")
```

- [ ] **Step 5: Wire replay inputs into `CuratedEvalRunner`**

Construct the runner with:

```python
summary = CuratedEvalRunner(
    config=config,
    artifact_dir=Path(args.artifact_dir).expanduser(),
    require_llm=args.require_llm,
    live=args.live,
    replay_trace_dir=Path(args.replay).expanduser() if args.replay else None,
    replay_case_path=Path(args.replay_case).expanduser() if args.replay_case else None,
    progress_callback=None if args.no_progress else _print_progress,
).run(
    subset=None if args.replay_case else args.subset,
    trials=args.trials,
    max_workers=args.max_workers,
    seed=args.seed,
)
```

- [ ] **Step 6: Run the CLI tests to verify GREEN**

Run:

```bash
uv run python -m pytest tests/test_eval_cli.py -q
```

Expected:

- PASS

- [ ] **Step 7: Commit the CLI replay slice**

```bash
git add app/cli/eval.py tests/test_eval_cli.py
git commit -m "feat: add replay flags to phase2 eval cli"
```

## Task 3: Enrich Comparison Artifacts With Case-Level Deltas

**Files:**
- Modify: `app/eval/metrics.py`
- Modify: `tests/test_eval_runner.py`

- [ ] **Step 1: Write the failing comparison-artifact tests**

Add focused tests to `tests/test_eval_runner.py`:

```python
def test_comparison_artifact_includes_case_level_deltas(self):
    comparison = build_comparison_artifact(
        baseline={
            "eval_run_id": "baseline",
            "report_artifact_path": "artifacts/phase2/reports/base.json",
            "results": [
                {"case_id": "case_a", "passed": False, "failure_label": "wrong_tool", "trace_artifact_path": "base-a.json"},
                {"case_id": "case_b", "passed": True, "failure_label": None, "trace_artifact_path": "base-b.json"},
            ],
            "failure_analysis": {"failure_label_counts": {"wrong_tool": 1}},
            "metrics": {"pass_1": 0.5},
        },
        candidate={
            "eval_run_id": "candidate",
            "report_artifact_path": "artifacts/phase2/reports/cand.json",
            "results": [
                {"case_id": "case_a", "passed": True, "failure_label": None, "trace_artifact_path": "cand-a.json"},
                {"case_id": "case_b", "passed": False, "failure_label": "response_mismatch", "trace_artifact_path": "cand-b.json"},
            ],
            "failure_analysis": {"failure_label_counts": {"response_mismatch": 1}},
            "metrics": {"pass_1": 0.5},
        },
    )
    assert comparison["case_deltas"]["fixed"][0]["case_id"] == "case_a"
    assert comparison["case_deltas"]["new_failures"][0]["case_id"] == "case_b"
```

- [ ] **Step 2: Run the comparison tests to verify RED**

Run:

```bash
uv run python -m pytest tests/test_eval_runner.py -k "comparison_artifact" -q
```

Expected:

- FAIL because `case_deltas` and overlap metadata are not present yet.

- [ ] **Step 3: Add result-indexing helpers in `app/eval/metrics.py`**

Add helpers:

```python
def _results_by_case(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    results = report.get("results", [])
    return {
        str(result["case_id"]): result
        for result in results
        if isinstance(result, dict) and "case_id" in result
    }


def _case_delta_entry(case_id: str, baseline: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": case_id,
        "baseline_failure_label": baseline.get("failure_label"),
        "candidate_failure_label": candidate.get("failure_label"),
        "baseline_trace_artifact_path": baseline.get("trace_artifact_path"),
        "candidate_trace_artifact_path": candidate.get("trace_artifact_path"),
        "baseline_report_artifact_path": baseline.get("report_artifact_path"),
        "candidate_report_artifact_path": candidate.get("report_artifact_path"),
    }
```

- [ ] **Step 4: Extend `build_comparison_artifact()`**

Add overlap-aware case deltas:

```python
baseline_results = _results_by_case(baseline)
candidate_results = _results_by_case(candidate)
overlap_case_ids = sorted(set(baseline_results) & set(candidate_results))

new_failures = []
fixed = []
still_failing = []
failure_label_changed = []

for case_id in overlap_case_ids:
    baseline_case = dict(baseline_results[case_id], report_artifact_path=baseline.get("report_artifact_path"))
    candidate_case = dict(candidate_results[case_id], report_artifact_path=candidate.get("report_artifact_path"))
    ...
```

Return:

```python
"case_deltas": {
    "overlap_case_count": len(overlap_case_ids),
    "baseline_only_case_ids": sorted(set(baseline_results) - set(candidate_results)),
    "candidate_only_case_ids": sorted(set(candidate_results) - set(baseline_results)),
    "new_failures": new_failures,
    "fixed": fixed,
    "still_failing": still_failing,
    "failure_label_changed": failure_label_changed,
},
```

Keep this first version scoped to pass/fail and failure-label deltas. Do not add triage-bucket deltas in this phase.

- [ ] **Step 5: Run the comparison tests to verify GREEN**

Run:

```bash
uv run python -m pytest tests/test_eval_runner.py -k "comparison_artifact" -q
```

Expected:

- PASS

- [ ] **Step 6: Commit the comparison-artifact slice**

```bash
git add app/eval/metrics.py tests/test_eval_runner.py
git commit -m "feat: add case-level deltas to eval comparisons"
```

## Task 4: Improve Compare CLI Output And Persist Comparison Artifacts

**Files:**
- Modify: `app/cli/eval.py`
- Modify: `tests/test_eval_cli.py`

- [ ] **Step 1: Write the failing compare-output test**

Add a CLI-level test that exercises `_compare()` with small temp JSON files and asserts human-readable output includes summary and case-level sections:

```python
def test_compare_prints_summary_and_case_sections(tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps({...}))
    candidate.write_text(json.dumps({...}))
    code = eval_main(["--compare", str(baseline), str(candidate)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Phase 2 eval comparison" in out
    assert "new_failures" in out
    assert "fixed" in out
```

- [ ] **Step 2: Run the compare-output test to verify RED**

Run:

```bash
uv run python -m pytest tests/test_eval_cli.py -k "compare_prints_summary_and_case_sections" -q
```

Expected:

- FAIL because `_print_comparison()` only prints metric deltas.

- [ ] **Step 3: Extend `_print_comparison()`**

Print both summary and case-level sections:

```python
print("Phase 2 eval comparison")
print(f"baseline: {comparison['baseline_eval_run_id']}")
print(f"candidate: {comparison['candidate_eval_run_id']}")
print(f"overlap_cases: {comparison['case_deltas']['overlap_case_count']}")
...
for section_name in ("new_failures", "fixed", "still_failing", "failure_label_changed"):
    entries = comparison["case_deltas"][section_name]
    if not entries:
        continue
    print(section_name + ":")
    for entry in entries:
        print(
            f"  - {entry['case_id']} "
            f"baseline={entry['baseline_failure_label']} "
            f"candidate={entry['candidate_failure_label']}"
        )
```

- [ ] **Step 4: Write comparison artifacts under `artifacts/phase2/comparisons/`**

Add a helper in `app/cli/eval.py`:

```python
def _write_comparison_artifact(artifact_dir: Path, comparison: dict) -> Path:
    out_dir = artifact_dir / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline = comparison["baseline_eval_run_id"] or "baseline"
    candidate = comparison["candidate_eval_run_id"] or "candidate"
    path = out_dir / f"{baseline}__vs__{candidate}.json"
    with path.open("w", encoding="utf-8") as file:
        json.dump(comparison, file, indent=2, sort_keys=True)
        file.write("\\n")
    return path
```

Call it from `_compare()` using the parent report artifact path when available, otherwise fall back to `DEFAULT_EVAL_ARTIFACT_DIR`.

- [ ] **Step 5: Run the compare-output test to verify GREEN**

Run:

```bash
uv run python -m pytest tests/test_eval_cli.py -k "compare_prints_summary_and_case_sections" -q
```

Expected:

- PASS

- [ ] **Step 6: Commit the compare-CLI slice**

```bash
git add app/cli/eval.py tests/test_eval_cli.py
git commit -m "feat: persist and print richer eval comparisons"
```

## Task 5: Replay Smoke Coverage And Full Verification

**Files:**
- Modify: `tests/test_eval_runner.py`
- Modify: `tests/test_trace_replay_harness.py` if fixture helpers are needed

- [ ] **Step 1: Add one whole-run replay smoke test and one single-case replay smoke test**

Add deterministic tests that use a real trace fixture already covered by `tests/test_trace_replay_harness.py`:

```python
def test_replay_subset_smoke_uses_trace_directory(self):
    ...


def test_replay_case_smoke_uses_single_trace_file(self):
    ...
```

Each test should assert:

- replay summary/report writes successfully,
- `eval_backend == "replay"`,
- case ids match expected trace identity.

- [ ] **Step 1.1: Add the missing helper fixture in `tests/test_eval_runner.py`**

Before writing the replay-runner tests, add a small trace fixture helper so the earlier steps are executable:

```python
def _trace_fixture_for_case(case_id: str, *, trial: int = 0) -> dict:
    return {
        "metadata": {
            "task_id": case_id,
            "trial": trial,
            "trace_artifact_path": f"artifacts/phase2/traces/fake/runs/{case_id}-trial-{trial}.json",
        },
        "llm_responses": [
            {
                "assistant_content": "Done.",
                "tool_calls": [],
                "finish_reason": "stop",
            }
        ],
        "tool_calls": [],
        "messages": [],
        "steps": [],
    }
```

Use this helper in the replay tests instead of inventing ad hoc JSON inline in multiple places.

- [ ] **Step 2: Run the replay smoke tests to verify RED then GREEN**

Run:

```bash
uv run python -m pytest tests/test_eval_runner.py -k "replay_subset_smoke or replay_case_smoke" -q
```

Expected:

- First RED before the implementation is complete.
- Then PASS once replay wiring is complete.

- [ ] **Step 3: Run focused verification**

Run:

```bash
uv run python -m pytest tests/test_eval_runner.py tests/test_eval_cli.py tests/test_trace_replay_harness.py -q
uv run python -m pytest tests/test_live_eval_triage.py tests/test_tool_observations.py -q
```

Expected:

- All focused tests PASS.

- [ ] **Step 4: Run full verification**

Run:

```bash
uv run python -m pytest tests/ -q
uv run ruff check .
```

Expected:

- All tests PASS.
- Ruff reports no issues.

- [ ] **Step 5: Run CLI smoke commands with real artifacts**

Use a real recent trace/report set from `artifacts/phase2/`:

```bash
uv run phase2-eval --subset generalized_mvp --replay artifacts/phase2/traces/<eval_run_id>
uv run phase2-eval --replay-case artifacts/phase2/traces/<eval_run_id>/runs/<case-trace>.json
uv run phase2-eval --compare artifacts/phase2/reports/<baseline>.json artifacts/phase2/reports/<candidate>.json
```

Expected:

- replay whole-run produces a replay report under `artifacts/phase2/reports/`
- replay single-case produces a one-case replay report
- compare prints summary plus case-level sections and writes a comparison artifact under `artifacts/phase2/comparisons/`

- [ ] **Step 6: Commit the verification slice**

```bash
git add tests/test_eval_runner.py tests/test_eval_cli.py tests/test_trace_replay_harness.py
git commit -m "test: verify replay and comparison cli flows"
```

## Self-Review

- Spec coverage:
  - replay whole-run backend → Task 1
  - replay single-case backend → Task 1 + Task 5
  - compare summary + case delta → Task 3 + Task 4
  - comparison artifact persistence → Task 4
  - CLI-only scope → Tasks 1-5, no Workbench/nightly tasks added
- Completeness scan:
  - no unfinished markers, deferred steps, or vague “just handle it” instructions remain
- Type consistency:
  - replay inputs use `replay_trace_dir` / `replay_case_path` consistently
  - comparison output uses `case_deltas` consistently across metrics, CLI, and tests
