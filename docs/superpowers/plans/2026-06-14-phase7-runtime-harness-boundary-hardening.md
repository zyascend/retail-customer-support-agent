# Phase 7 Runtime Harness Boundary Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split offline demo rule parsing out of the production runtime surface and make eval/workbench/report boundaries explicit.

**Architecture:** `AgentRuntime` remains the production orchestration layer for pre-flight checks, provider selection, `AgentLoop`, and trace writing. Demo-only parsing and deterministic tool execution move into `app/agent/offline_demo.py` behind `OfflineDemoHarness.handle(session, content)`. Eval reports distinguish `scripted_offline_demo`, `scripted_tool_loop`, `live`, and `replay`; Workbench keeps `offline_demo`/`llm` modes while placing legacy business fields under `compat`.

**Tech Stack:** Python 3.11, pytest, ruff, FastAPI Workbench API, existing `SessionState`, `ToolGateway`, `AgentRuntime`, and eval report dataclasses.

---

### Task 1: Extract Offline Demo Harness

**Files:**
- Create: `app/agent/offline_demo.py`
- Modify: `app/agent/runtime.py`
- Test: `tests/test_runtime_phase4.py`

- [ ] **Step 1: Write the failing boundary test**

Add this test to `tests/test_runtime_phase4.py`:

```python
def test_offline_demo_parser_lives_outside_agent_runtime() -> None:
    assert not hasattr(AgentRuntime, "_offline_demo_intent")
    assert not hasattr(AgentRuntime, "_det_call")
    assert not hasattr(AgentRuntime, "_parse_address")

    from app.agent.offline_demo import OfflineDemoHarness

    assert hasattr(OfflineDemoHarness, "handle")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/test_runtime_phase4.py::TestRuntimeSafeFallback::test_offline_demo_parser_lives_outside_agent_runtime -q`
Expected: FAIL because `AgentRuntime` still has `_offline_demo_intent`, `_det_call`, and `_parse_address`.

- [ ] **Step 3: Move demo-only logic into the harness**

Create `app/agent/offline_demo.py` with `OfflineDemoHarness`, moving the regex constants, `handle()`, `_det_call()`, and `_parse_address()` from `AgentRuntime`. The constructor accepts `gateway` and `retail_runtime`. Preserve existing assistant messages, pending confirmation behavior, auto-loading, guard behavior, and `offline_demo_intent` steps.

- [ ] **Step 4: Wire runtime to the harness**

In `app/agent/runtime.py`, import `OfflineDemoHarness`, instantiate it after `self.gateway`, replace `self._offline_demo_intent(session, content)` with `self._offline_demo_harness.handle(session, content)`, and delete the moved methods/constants. Keep no-provider non-demo behavior unchanged.

- [ ] **Step 5: Run focused runtime tests**

Run: `uv run python -m pytest tests/test_runtime_phase4.py -q`
Expected: all tests in the file pass.

### Task 2: Rename Eval Backend Semantics

**Files:**
- Modify: `app/eval/runner.py`
- Modify: `tests/test_eval_runner.py`

- [ ] **Step 1: Write failing eval backend tests**

Update existing expectations in `tests/test_eval_runner.py` so non-live/non-replay runs expect `scripted_offline_demo`, replay expects `replay`, and live expects `live`. Add a direct unit test:

```python
def test_eval_backend_names_scripted_offline_demo_for_ci_harness(self):
    with tempfile.TemporaryDirectory() as tmp:
        config = resolve_config(artifact_dir=tmp)
        runner = CuratedEvalRunner(config=config, artifact_dir=Path(tmp))

        self.assertEqual(runner._eval_backend(), "scripted_offline_demo")
```

- [ ] **Step 2: Run the focused eval tests to verify failure**

Run: `uv run python -m pytest tests/test_eval_runner.py -q`
Expected: FAIL on backend string expectations because the code still returns `scripted`.

- [ ] **Step 3: Implement backend names**

Change `EvalCaseResult.eval_backend` and `EvalRunSummary.eval_backend` defaults to `scripted_offline_demo`. Change `_eval_backend()` to return:

```python
if self._is_replay_mode():
    return "replay"
if self.live:
    return "live"
if self.require_llm:
    return "scripted_tool_loop"
return "scripted_offline_demo"
```

Use `self._eval_backend()` when setting each normal `EvalCaseResult.eval_backend`.

- [ ] **Step 4: Run eval runner tests**

Run: `uv run python -m pytest tests/test_eval_runner.py -q`
Expected: pass.

### Task 3: Move Workbench Legacy Fields To Compat

**Files:**
- Modify: `app/workbench/snapshot.py`
- Modify: `app/ops/tracing.py`
- Modify: `workbench/src/types.ts`
- Modify: `workbench/src/components/BusinessState.tsx`
- Modify: Workbench tests that assert `business.current_intent` or top-level `policy_decision`

- [ ] **Step 1: Write failing compat tests**

Update `tests/test_workbench_snapshot.py` so `SNAPSHOT_KEYS` contains `compat` instead of `policy_decision`, and assert:

```python
self.assertNotIn("current_intent", snapshot["business"])
self.assertNotIn("slots", snapshot["business"])
self.assertEqual(snapshot["compat"]["current_intent"], "unknown")
self.assertEqual(snapshot["compat"]["slots"], {})
self.assertIsNone(snapshot["compat"]["policy_decision"])
```

Update trace assertions to expect `trace["final_state"]["compat"]["current_intent"]`.

- [ ] **Step 2: Run Workbench snapshot/session/API tests to verify failure**

Run: `uv run python -m pytest tests/test_workbench_snapshot.py tests/test_workbench_session.py tests/test_workbench_api.py -q`
Expected: FAIL because compat is not emitted yet.

- [ ] **Step 3: Implement compat output**

In `app/workbench/snapshot.py`, remove `current_intent` and `slots` from `business`, remove top-level `policy_decision`, and add:

```python
"compat": {
    "current_intent": "unknown",
    "slots": {},
    "policy_decision": None,
},
```

In `app/ops/tracing.py`, change `final_state_summary()` to put the same three legacy values under `compat`.

- [ ] **Step 4: Update frontend types and UI reads**

In `workbench/src/types.ts`, remove `business.current_intent`, `business.slots`, and top-level `policy_decision`; add `compat.current_intent`, `compat.slots`, and `compat.policy_decision`.

In `workbench/src/components/BusinessState.tsx`, read intent and slots from the passed snapshot compat data if the component receives it; if the component only receives `business`, hide those legacy fields instead of showing production business state.

- [ ] **Step 5: Run Workbench tests**

Run: `uv run python -m pytest tests/test_workbench_snapshot.py tests/test_workbench_session.py tests/test_workbench_api.py tests/test_workbench_cases.py -q`
Expected: pass.

### Task 4: Documentation, Phase Review, And Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/portfolio-architecture.md`
- Modify: `docs/long-term-optimization-path.md`

- [ ] **Step 1: Update documentation wording**

Ensure README and portfolio docs say scripted/offline demo is `scripted_offline_demo`, not a live LLM capability measurement. Add a Phase 7 Review section to `docs/long-term-optimization-path.md` covering goals, changes, architecture boundary, safety, eval/trace evidence, and follow-up debt.

- [ ] **Step 2: Run targeted verification**

Run:

```bash
uv run python -m pytest tests/test_runtime_phase4.py tests/test_eval_runner.py tests/test_workbench_snapshot.py tests/test_workbench_session.py tests/test_workbench_api.py -q
uv run ruff check .
```

Expected: both commands pass.

- [ ] **Step 3: Run full acceptance verification**

Run:

```bash
uv run python -m pytest -q
uv run python -m app.cli.eval --subset curated_mvp --trials 1 --max-workers 1 --no-progress
```

Expected: pytest passes and curated scripted eval reports 11/11 passed with `eval_backend=scripted_offline_demo`.

- [ ] **Step 4: Review diff and summarize**

Run: `git diff --stat && git diff -- app/agent/runtime.py app/agent/offline_demo.py app/eval/runner.py app/workbench/snapshot.py app/ops/tracing.py`
Expected: runtime is smaller, offline demo logic is isolated, and legacy fields are only emitted under `compat`.
