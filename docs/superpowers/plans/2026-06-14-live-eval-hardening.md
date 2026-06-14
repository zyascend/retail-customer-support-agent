# Live Eval Hardening Implementation Plan

> For agentic workers: execute this plan step by step. Do not skip tests. Do not reintroduce production deterministic fallback. Treat live generalized failures as data first, then patch only the smallest surface that the triage evidence supports.

Date: 2026-06-14
Spec: `docs/superpowers/specs/2026-06-14-live-eval-hardening-design.md`

## Objective

Build the first `generalized_mvp` live-eval hardening loop:

- Capture a real live baseline.
- Add a failure triage helper.
- Extract tool-observation formatting into a tested contract module.
- Use the baseline to make one targeted hardening pass.
- Verify that `curated_mvp` live stays green and `generalized_mvp` live is better understood, and ideally improved.

## Phase 1: Capture Baseline Before Code Changes

### Task 1.1: Confirm clean branch state

Run:

```bash
git status --short --branch
```

Expected:

- Working tree is clean except for intentional plan/spec files if this plan is being executed from the planning branch.

### Task 1.2: Run generalized live baseline

Run:

```bash
uv run phase2-eval --subset generalized_mvp --trials 1 --live
```

Record:

- Exit status.
- Pass/fail count.
- Report path from command output.
- Any obvious failing case ids.

Do not patch runtime behavior before this baseline exists.

## Phase 2: Add Failure Triage Helper

### Task 2.1: Inspect current report schema

Read:

- `app/eval/runner.py`
- One recent report under `artifacts/phase2/reports/`

Confirm field names for:

- Case id.
- Subset.
- Trial index.
- Pass/fail status.
- Failure label.
- Tool call metrics.
- Guard metrics.
- DB assertion failures.
- Trace path or trace id.
- Final response.

### Task 2.2: Add triage module

Create `app/eval/live_triage.py` with:

- `classify_failure(result: Mapping[str, Any]) -> str`
- `summarize_failure(result: Mapping[str, Any]) -> dict[str, Any]`
- `summarize_report(report: Mapping[str, Any]) -> dict[str, Any]`
- `format_markdown(summary: Mapping[str, Any]) -> str`

Initial classification order:

1. `tool_protocol` when protocol violation count is greater than zero.
2. `tool_error` when failed tool call or tool error count is greater than zero.
3. `guard_behavior` when guardrail block/refusal metrics explain the failure.
4. `tool_selection` when required or forbidden tool mismatches are present.
5. `response_oracle` when tools and DB assertions look correct but response assertions fail.
6. `runtime_error` when the result contains an exception or is missing normal result structure.
7. `unknown_live_behavior` otherwise.

Keep this module pure and independent from live model calls.

### Task 2.3: Add CLI entry point

Add a module entry point so this works:

```bash
uv run python -m app.eval.live_triage artifacts/phase2/reports/<report>.json
```

Expected output:

- Markdown summary by default.
- Case ids and primary bucket for each failed result.
- Report-level pass/fail totals when available.

### Task 2.4: Add triage tests

Create `tests/test_live_eval_triage.py`.

Test cases:

- Protocol violation classifies as `tool_protocol`.
- Failed tool call classifies as `tool_error`.
- Required tool mismatch classifies as `tool_selection`.
- Guard block/refusal classifies as `guard_behavior`.
- Response-only assertion mismatch classifies as `response_oracle`.
- Unknown failure classifies as `unknown_live_behavior`.
- Markdown formatting includes report path, failed case id, bucket, and suggested next action.

Run:

```bash
uv run python -m pytest tests/test_live_eval_triage.py -q
```

## Phase 3: Extract Observation Contract

### Task 3.1: Locate current observation formatting

Read:

- `app/agent/llm_agent.py`
- Existing tests around `AgentLoop` tool observations.

Identify the current `_format_tool_observation` implementation and its constants.

### Task 3.2: Add observation formatting module

Create `app/agent/tool_observations.py` with:

- `TOOL_OBSERVATION_LIMIT`
- `PRIORITY_OBSERVATION_KEYS`
- `format_tool_observation(observation: Any, limit: int = TOOL_OBSERVATION_LIMIT) -> str`

Behavior:

- Dict observations should serialize to compact JSON.
- Priority top-level keys should appear before non-priority keys.
- Non-dict observations should still become a safe string.
- Output should be truncated at the configured limit.

### Task 3.3: Wire AgentLoop to the module

Update `app/agent/llm_agent.py`:

- Import `format_tool_observation`.
- Remove the local formatting constants and method.
- Call the imported function where tool results are appended to the LLM conversation.

### Task 3.4: Add observation contract tests

Add focused tests to `tests/test_llm_agent.py` or create `tests/test_tool_observations.py`.

Required tests:

- Order status is visible in formatted observations.
- Priority fields precede bulky payload fields.
- Oversized observations preserve priority fields before truncation.
- Non-dict observations produce a deterministic string.

Run:

```bash
uv run python -m pytest tests/test_tool_observations.py tests/test_llm_agent.py::TestAgentLoopReadTools::test_order_status_is_visible_in_tool_observation -q
```

If the focused test class or test name has changed, use `rg "order_status_is_visible|tool_observation" tests` to locate the equivalent test.

## Phase 4: Triage Baseline and Patch One Failure Class

### Task 4.1: Generate triage summary from baseline

Run:

```bash
uv run python -m app.eval.live_triage artifacts/phase2/reports/<baseline-report>.json
```

Save or paste the summary into implementation notes.

### Task 4.2: Pick one primary failure class

Choose the highest-impact failure class using this order:

1. `tool_protocol`
2. `tool_error`
3. `observation_contract`
4. `tool_selection`
5. `guard_behavior`
6. `prompt_instruction`
7. `response_oracle`
8. `unknown_live_behavior`

If multiple classes are tied, choose the class affecting the most cases.

### Task 4.3: Add regression coverage before patching

Add a deterministic test that captures the selected class:

- For observation failures, add a direct formatter test.
- For tool-selection or prompt/schema failures, add a scripted or fake-provider `AgentLoop` test that asserts the intended tool call path.
- For guard behavior failures, add a guard-focused unit test.
- For oracle failures, add an eval-runner/oracle test using a synthetic result.

Run the new focused test and confirm it fails before the patch when practical.

### Task 4.4: Patch the smallest supported surface

Allowed patch surfaces:

- `app/agent/tool_observations.py`
- Agent system prompt or prompt assembly.
- Tool description or argument description in `app/tools/registry.py`.
- Eval oracle logic.
- Guard behavior when policy handling is inconsistent.

Do not:

- Special-case eval case ids.
- Add offline-demo fallback to production runtime.
- Patch more than one unrelated failure class in the same pass.

### Task 4.5: Re-run focused tests

Run:

```bash
uv run python -m pytest tests/test_live_eval_triage.py -q
uv run python -m pytest tests/test_tool_observations.py -q
```

Also run any focused test added for the selected failure class.

## Phase 5: Full Verification

### Task 5.1: Run unit and lint verification

Run:

```bash
uv run python -m pytest tests/ -q
uv run ruff check .
```

Expected:

- All tests pass.
- Ruff reports no issues.

### Task 5.2: Re-run curated live smoke

Run:

```bash
uv run phase2-eval --subset curated_mvp --trials 1 --live
```

Expected:

- `curated_mvp` remains green.
- If it fails due to transient provider behavior, re-run once and compare trace/report details before patching.

### Task 5.3: Re-run generalized live candidate

Run:

```bash
uv run phase2-eval --subset generalized_mvp --trials 1 --live
```

Record:

- Candidate report path.
- Pass/fail count.
- Whether the selected failure class improved.
- Any new failure classes.

### Task 5.4: Produce candidate triage summary

Run:

```bash
uv run python -m app.eval.live_triage artifacts/phase2/reports/<candidate-report>.json
```

Compare against baseline:

- Same case ids still failing.
- Fixed case ids.
- New failing case ids.
- Bucket movement.

## Phase 6: Documentation and PR Notes

### Task 6.1: Update documentation only if behavior changed

If the implementation changes user-facing commands, report format, or eval workflow, update the relevant docs:

- `README.md`
- `CLAUDE.md`
- `docs/portfolio/architecture.md`
- Existing eval docs if present.

Do not update docs for purely internal refactors unless the developer workflow changes.

### Task 6.2: Prepare PR summary

Include:

- Baseline generalized live report path and pass/fail count.
- Candidate generalized live report path and pass/fail count.
- Curated live report path and pass/fail count.
- Failure bucket fixed or clarified.
- Unit/lint verification commands and results.
- Remaining live-eval risks.

## Completion Criteria

This plan is complete when:

- Triage helper exists and is tested.
- Observation contract module exists and is tested.
- At least one live-derived failure class has regression coverage and a targeted patch, unless the generalized baseline is already green.
- `curated_mvp` live passes.
- `generalized_mvp` live has a baseline and candidate report.
- Full tests and lint pass.

## Recommended Execution Mode

Use inline execution for the first pass because live baseline output determines which failure class to patch. After the first triage summary exists, independent follow-up buckets can be split across subagents.
