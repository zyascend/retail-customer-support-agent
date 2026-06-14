# CLI Replay And Baseline Compare Design

Date: 2026-06-14
Status: Ready for implementation planning

## Context

The project now has the pieces needed for a tighter eval-debug loop:

- `curated_mvp` live passes.
- `generalized_mvp` live passes.
- Phase 2 reports already carry stable per-case metadata such as failure labels, tool metrics, and trace metadata.
- `TraceReplayHarness` already exists for replaying recorded turns.
- `app/eval/live_triage.py` already summarizes failed reports into actionable buckets.
- The eval CLI already has report-comparison helpers in `app/eval/metrics.py` and `app/cli/eval.py`.

What is still missing is a single, local, repeatable workflow that connects these pieces:

1. replay an entire eval run from traces,
2. replay a single failed case from one trace file,
3. compare two reports and see both summary-level and case-level deltas.

This phase focuses only on the CLI workflow. It does not add Nightly, Workbench UI, or dashboards.

## Goal

Create a CLI-only replay-and-compare loop that makes Phase 2 eval results easier to reproduce and compare:

1. Replay a whole trace directory through the eval runner.
2. Replay a single trace file as a one-case eval report.
3. Emit replay results using the same eval-style report structure used by scripted and live runs.
4. Compare baseline and candidate reports with both summary deltas and per-case deltas.
5. Keep the new behavior compatible with existing triage tooling.

## Non-Goals

- Do not add Nightly automation.
- Do not add Workbench replay/report UI.
- Do not add report browsing, run history, or trace visualization.
- Do not change production agent/runtime behavior.
- Do not redesign the eval report schema beyond the minimum needed to support replay parity.

## User-Facing Outcome

After this phase, a developer should be able to do all of the following locally:

```bash
# Replay a whole run from trace artifacts
uv run phase2-eval --subset generalized_mvp --replay artifacts/phase2/traces/eval-XXXXX

# Replay a single failed case from one trace file
uv run phase2-eval --replay-case artifacts/phase2/traces/eval-XXXXX/runs/<case-trace>.json

# Compare two reports with summary + case-level delta output
uv run phase2-eval --compare artifacts/phase2/reports/<baseline>.json artifacts/phase2/reports/<candidate>.json
```

## Design Principles

### Reuse the existing eval surface

Replay and compare should extend the existing `phase2-eval` workflow, not create parallel CLIs. The current runner, report schema, metrics builder, and triage helper are already the shared language of eval work. This phase should reinforce that language.

### Replay is an eval backend, not a special debug mode

Replay should be treated as another eval backend alongside `scripted` and `live`. That means replay outputs should look like normal eval outputs and should be consumable by the same report-comparison and triage tooling.

### Single-case replay should still be report-shaped

A one-case replay should still emit a standard eval-style artifact, just with one result. This keeps compare, triage, and future automation paths uniform.

### Compare should help humans decide what changed

The compare command should not stop at pass-rate deltas. It should explain which cases regressed, which recovered, and which changed failure mode, with enough path information to inspect the underlying reports and traces.

## Proposed Scope

### 1. Replay backend in the eval runner

Extend `CuratedEvalRunner` so it can run in replay mode:

- `--replay <trace_dir>` means replay a trace directory for a known subset.
- `--replay-case <trace_file>` means replay exactly one trace file and build a one-case eval report.
- `eval_backend` becomes `"replay"` for those outputs.

The runner should continue to produce:

- eval run artifact under `artifacts/phase2/eval_runs/`
- eval report under `artifacts/phase2/reports/`
- normal per-case `EvalCaseResult` structures

### 2. Whole-run replay path

When replaying a trace directory:

- the runner should resolve each case/trial trace file from the supplied trace root,
- load the trace with `TraceReplayHarness`,
- replay it into an `EvalCaseResult`,
- preserve `replay_metadata` and trace path references in the result.

If a trace for a requested case is missing, the runner should fail clearly rather than silently skipping the case.

### 3. Single-case replay path

When replaying one trace file:

- load the trace directly,
- recover case identity and trial index from the trace metadata or filename,
- run replay for that single case,
- emit a one-case eval artifact/report with `eval_backend="replay"`.

This keeps the output compatible with existing report processors and avoids inventing a one-off debug artifact.

### 4. Compare output: summary + case-level delta

The compare command should produce two layers of output.

Summary layer:

- baseline eval run id
- candidate eval run id
- subset when available
- pass-rate / passed-count delta
- key metric deltas
- failure-label count deltas
- bucket count deltas when available

Case layer:

- newly failing cases
- newly fixed cases
- still failing cases
- cases whose failure label changed
- cases whose triage bucket changed

Each case entry should include:

- case id
- baseline failure label
- candidate failure label
- baseline report path when available
- candidate report path when available
- baseline trace path when available
- candidate trace path when available

### 5. Comparison artifact

In addition to human-readable CLI output, write a JSON comparison artifact under:

`artifacts/phase2/comparisons/`

That artifact should contain:

- baseline metadata
- candidate metadata
- metric deltas
- failure-label deltas
- case-level delta lists

This is enough to support future Nightly, dashboards, or Workbench entry points without designing those now.

## CLI Shape

Keep a single CLI entry point and extend it conservatively.

### Existing compare path

The current `--compare` flow stays in place, but its output becomes richer by including case-level delta sections in addition to metric deltas.

### New replay flags

Add:

- `--replay <trace_dir>`
- `--replay-case <trace_file>`

Behavior rules:

- `--replay` and `--replay-case` are mutually exclusive.
- `--replay-case` does not require `--subset`.
- `--replay` requires `--subset` because a whole-run replay needs to know which case list to evaluate against.
- `--live` and replay flags are mutually exclusive.

## Data Model Expectations

### Eval backend

Replay outputs must mark:

- summary `eval_backend = "replay"`
- per-case `eval_backend = "replay"`

### Replay metadata

Replay results should keep enough path references to support triage and compare:

- trace artifact path
- original run id when available
- case id
- trial index

### Compare input assumptions

Compare should work on any pair of eval reports that share case ids, including:

- live vs live
- live vs replay
- replay vs replay
- scripted vs replay

If subsets differ, compare should still run but clearly report that only overlapping case ids are being compared.

## Error Handling

### Replay input errors

Fail clearly when:

- the trace directory does not exist,
- the trace file does not exist,
- a replay trace lacks required metadata,
- a whole-run replay is missing one or more requested case traces,
- an old trace is structurally incompatible with the current harness.

Error messages should point to the missing path or missing field directly.

### Compare input errors

Fail clearly when:

- either report file is missing,
- the input is not valid JSON,
- required report fields are absent,
- there are no overlapping case ids to compare.

## Testing Strategy

This phase should be driven by deterministic tests and one small CLI smoke layer.

### Required deterministic coverage

- runner supports `eval_backend="replay"`
- whole-run replay produces a standard eval report
- single-case replay produces a one-case eval report
- compare output includes summary delta and case delta sections
- compare JSON artifact contains case-level delta lists
- subset mismatch behavior is explicit and stable

### Required smoke verification

- replay an existing trace directory from a real recent eval run
- replay one real single-case trace file
- compare two real reports and confirm case-level delta output

## Success Criteria

- `phase2-eval --replay <trace_dir>` works for a real trace directory.
- `phase2-eval --replay-case <trace_file>` works for a real case trace.
- replay outputs standard eval-style artifacts and reports.
- `phase2-eval --compare ...` prints both summary and case-level deltas.
- comparison artifacts are written to `artifacts/phase2/comparisons/`.
- existing `live_triage` can consume replay-generated reports without schema-specific branching.
- full local verification remains green.

## Risks

### Old trace compatibility

Some existing traces may not carry the metadata needed for single-case replay or compare. Mitigation: fail explicitly on missing metadata and keep the requirement narrow rather than silently synthesizing uncertain values.

### CLI sprawl

Adding replay flags to `phase2-eval` can make the command harder to reason about. Mitigation: keep the flags mutually exclusive and document a small number of valid command forms.

### Case identity mismatch

Comparing reports from different subsets or partial runs can create misleading deltas. Mitigation: compare by overlapping case ids only and report the overlap explicitly.

## Out Of Scope Follow-Up

- Nightly advisory benchmark
- Workbench replay/report entry points
- report browser and run history
- trace navigation UI
- multi-trial stability scoring
