# Live Eval Hardening Design

Date: 2026-06-14
Status: Ready for implementation planning

## Context

The LLM agent tool-calling architecture is now in the intended shape:

- Production runtime uses the real LLM tool-calling loop.
- Offline deterministic behavior is explicit harness behavior via `offline_demo=True`.
- `curated_mvp` live eval passes after the observation-format fix.
- Reports already include live/runtime metadata such as `eval_backend`, `runtime_backend`, `offline_demo`, token usage, and loop iterations.

The remaining risk is no longer whether the architecture can run live. The next risk is whether live behavior remains understandable and improvable as we broaden from curated cases to generalized scenarios.

## Goal

Create a repeatable live-eval hardening loop for `generalized_mvp`:

1. Capture a live baseline with enough metadata to diagnose failures.
2. Classify failures into actionable buckets.
3. Apply small, eval-driven hardening patches.
4. Preserve each fixed behavior as a deterministic regression test or replayable trace check.
5. Re-run live eval to verify the improvement without regressing `curated_mvp`.

## Non-Goals

- Do not make generalized live eval a required CI gate yet.
- Do not introduce a new agent framework or planner.
- Do not redesign Workbench in this phase.
- Do not add new business tools unless a live failure proves the current tool surface is insufficient.
- Do not use offline-demo pass rate as evidence of live model quality.

## Success Criteria

- A `generalized_mvp` live baseline report is produced and retained under `artifacts/phase2/reports/`.
- Failed live cases can be summarized into stable failure buckets:
  - `tool_selection`
  - `tool_protocol`
  - `tool_error`
  - `observation_contract`
  - `prompt_instruction`
  - `guard_behavior`
  - `response_oracle`
  - `runtime_error`
  - `unknown_live_behavior`
- The triage output points to the report, trace artifact, case id, failure label, final response, tool calls, and suggested next action.
- Tool-observation formatting is centralized and covered by focused tests.
- Every behavior fixed from a live failure gets a deterministic regression test or replay-style test before the implementation patch is considered complete.
- `curated_mvp` live remains green.
- Full local verification remains green: `pytest`, `ruff`, and live eval smoke commands.

## Design Principles

### Runtime remains single

The runtime boundary from the architecture spec stays intact. The live hardening loop improves prompts, schemas, observations, tests, reports, and eval tooling around the runtime. It must not reintroduce deterministic fallback behavior inside production execution.

### Failures become data

Live model failures should not be handled as anecdotes. Each failure should produce a compact triage record with enough context to decide whether the problem belongs to the agent prompt, tool schema, observation format, guard behavior, oracle expectation, or runtime.

### Observation contract is explicit

Tool observations are part of the LLM-facing contract. High-value fields such as order status, order id, user id, email, pending confirmation state, and guard decisions should be predictably visible before truncation.

### Live eval is advisory until stable

Live generalized eval should be runnable and comparable, but not a merge-blocking gate yet. It is too sensitive to model drift and cost until we collect enough baseline history.

## Proposed Components

### 1. Generalized live baseline capture

Run `generalized_mvp` live eval and preserve the generated JSON report. The first baseline is allowed to fail. The goal is to observe actual behavior before patching.

Expected command:

```bash
uv run phase2-eval --subset generalized_mvp --trials 1 --live
```

The report path should be referenced in the implementation notes and triage output.

### 2. Failure triage helper

Add a small report-inspection helper that reads a Phase 2 eval report and emits concise failure summaries.

The helper should:

- Load the report JSON.
- Select failed case results.
- Extract case id, subset, trial, failure label, expected tool mismatches, DB assertion failures, guard metrics, tool errors, protocol violations, final response, and trace path when present.
- Classify each failure into one primary bucket.
- Emit markdown or JSON so it can be pasted into reviews and PR descriptions.

Initial classification rules can be conservative:

- `tool_protocol`: protocol violations are present.
- `tool_error`: failed tool calls or tool errors are present.
- `guard_behavior`: guardrail blocks or refusals explain the mismatch.
- `tool_selection`: required/forbidden tool mismatch is present.
- `response_oracle`: tool calls and DB assertions look correct, but final answer assertions fail.
- `runtime_error`: uncaught runtime exception or missing report fields prevent normal evaluation.
- `unknown_live_behavior`: none of the above fits.

More nuanced `observation_contract` and `prompt_instruction` classification can be added after the first baseline, using trace details.

### 3. Tool observation contract module

Move LLM-visible observation formatting out of the loop body into a focused module. This keeps the contract testable without running a full LLM loop.

The module should:

- Prioritize high-value top-level keys before lower-priority payload.
- Produce compact JSON when possible.
- Preserve the existing truncation behavior.
- Return a safe string for non-JSON-serializable observations.

Focused tests should cover:

- Order status remains visible after formatting.
- Priority keys stay near the front of the observation.
- Oversized payloads are truncated without removing priority fields.
- Non-dict observations still serialize predictably.

### 4. Eval-driven hardening patch loop

Each live failure should be processed through the same sequence:

1. Add or update a regression test that reproduces the failure deterministically.
2. Patch the smallest surface that explains the failure.
3. Run focused tests.
4. Run `curated_mvp` live to ensure the proven live path still passes.
5. Run `generalized_mvp` live again to compare against the baseline.

Allowed patch surfaces:

- Prompt instructions.
- Tool descriptions and argument schema descriptions.
- Observation formatting.
- Eval oracle expectations, when the oracle is too narrow.
- Guardrail handling, when refusal or confirmation behavior is inconsistent with policy.

Disallowed patch surfaces:

- Reintroducing deterministic production fallback.
- Special-casing individual eval case ids in runtime behavior.
- Treating offline-demo success as live success.

## Verification Strategy

Minimum verification for the implementation PR:

```bash
uv run python -m pytest tests/test_llm_agent.py -q
uv run python -m pytest tests/ -q
uv run ruff check .
uv run phase2-eval --subset curated_mvp --trials 1 --live
uv run phase2-eval --subset generalized_mvp --trials 1 --live
```

If generalized live still has failures after the first patch, the PR can still be useful if:

- The baseline and candidate reports are both retained.
- The failure count or failure quality improved.
- Remaining failures have triage records and a follow-up recommendation.
- `curated_mvp` live remains green.

## Risks

### Model nondeterminism

Live eval results can vary across model versions and sampling. Mitigation: store report ids, compare failure classes instead of only raw pass rate, and avoid making generalized live a hard gate immediately.

### Overfitting eval prompts

Prompt and schema changes can accidentally optimize for specific eval phrasing. Mitigation: prefer general policy wording, observation contracts, and deterministic regression tests over case-id branches.

### Oracle mismatch

Some live failures may be acceptable responses that the current oracle does not recognize. Mitigation: classify these as `response_oracle` only after tool calls and DB state are correct.

### Cost and latency

Repeated live eval runs cost time and model usage. Mitigation: use `trials 1` during development and reserve multi-trial runs for stabilization.

## Open Follow-Up After This Phase

- Nightly advisory benchmark.
- Baseline-vs-candidate comparison command.
- Workbench live/replay toggle and trace viewer.
- Broader guardrail scenario coverage.
- Multi-trial stability scoring once generalized live behavior is less noisy.
