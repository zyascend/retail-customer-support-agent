# Phase 8 Structured Guard Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every guard block carry structured, replayable context from `WriteActionGuard` through gateway records, LLM tool observations, traces, and Workbench output.

**Architecture:** Extend the existing guard/gateway/record chain instead of introducing a parallel error model. `WriteActionGuardResult.block_context` is the source of truth; `ToolGateway` copies it into `ToolCallRecord.block_context` and blocked observations; `AgentLoop` uses it when creating guard-block tool messages for the LLM.

**Tech Stack:** Python 3.11, pytest, pydantic-compatible models, existing `WriteActionGuard`, `ToolGateway`, `AgentLoop`, trace, replay, and Workbench snapshot modules.

---

### Task 1: Guard Produces Structured Block Context

**Files:**
- Modify: `app/agent/guard.py`
- Modify: `tests/test_agent_core.py`

- [x] **Step 1: Write failing guard tests**

Add tests that assert `WriteActionGuardResult.block_context` exists and contains minimal context for:
- `authentication_required`
- `ownership_violation`
- `read_before_write_required`
- `explicit_confirmation_required`
- one policy block, such as `non_pending_order_cannot_be_cancelled`
- one lock conflict, such as `duplicate_write_lock`

- [x] **Step 2: Verify tests fail**

Run: `uv run python -m pytest tests/test_agent_core.py -q`
Expected: FAIL because `block_context` does not exist yet.

- [x] **Step 3: Implement minimal context generation**

Add `block_context: Dict[str, Any] = field(default_factory=dict)` to `WriteActionGuardResult`. Extend `_blocked()` to accept `context`. Build context at the point where the guard has the needed data, avoiding full sensitive payloads.

- [x] **Step 4: Verify guard tests pass**

Run: `uv run python -m pytest tests/test_agent_core.py -q`
Expected: PASS.

### Task 2: Gateway Records And Observations Preserve Context

**Files:**
- Modify: `app/agent/models.py`
- Modify: `app/tools/gateway.py`
- Modify: `tests/test_tool_observations.py`
- Modify: `tests/test_workbench_snapshot.py`

- [x] **Step 1: Write failing gateway/serialization tests**

Assert blocked `ToolCallRecord` has `block_context`, and `record.observation` is a dict with:
- `status: "blocked"`
- `block_reason`
- `block_context`
- `message_for_llm`

- [x] **Step 2: Verify tests fail**

Run: `uv run python -m pytest tests/test_tool_observations.py tests/test_workbench_snapshot.py -q`
Expected: FAIL because records do not expose structured context.

- [x] **Step 3: Implement record propagation**

Add `block_context: Dict[str, Any] = Field(default_factory=dict)` to `ToolCallRecord`. In `ToolGateway.execute()`, populate it for blocked writes and set `observation` to a compact structured guard block observation. Include context in the `write_action_guard` step detail.

- [x] **Step 4: Verify tests pass**

Run: `uv run python -m pytest tests/test_tool_observations.py tests/test_workbench_snapshot.py -q`
Expected: PASS.

### Task 3: AgentLoop Sends JSON Guard Observations To LLM

**Files:**
- Modify: `app/agent/models.py`
- Modify: `app/agent/llm_agent.py`
- Modify: `tests/test_llm_agent.py`

- [x] **Step 1: Write failing AgentLoop test**

Add a test that triggers a non-confirmation policy block and inspects the tool message received by the scripted provider. The JSON should include `error_type: "guard_blocked"` and a `block_context` object, not only a string reason.

- [x] **Step 2: Verify test fails**

Run: `uv run python -m pytest tests/test_llm_agent.py -q`
Expected: FAIL because tool observations only include string `message_for_llm`.

- [x] **Step 3: Implement LLM observation helper**

Add `block_context: Dict[str, Any] = Field(default_factory=dict)` to `ToolExecutionError`. Create a small helper in `AgentLoop` to build guard-block `ToolExecutionError` from `ToolCallRecord`, and use it in normal tool execution and premature-refusal correction.

- [x] **Step 4: Verify AgentLoop tests pass**

Run: `uv run python -m pytest tests/test_llm_agent.py -q`
Expected: PASS.

### Task 4: Trace, Replay, Docs, And Acceptance

**Files:**
- Modify: trace/replay tests as needed
- Modify: `docs/long-term-optimization-path.md`
- Modify: `docs/portfolio-architecture.md`

- [x] **Step 1: Add trace/replay assertions**

Assert serialized traces and replay fixtures preserve `block_context` in blocked `tool_calls`.

- [x] **Step 2: Update docs**

Add Phase 8 Review to `docs/long-term-optimization-path.md` and explain that block context is intentionally minimal and redaction-safe.

- [x] **Step 3: Run targeted verification**

Run:

```bash
uv run python -m pytest tests/test_agent_core.py tests/test_tool_observations.py tests/test_workbench_snapshot.py tests/test_llm_agent.py tests/test_trace_replay_harness.py -q
uv run ruff check .
```

Expected: PASS.

- [x] **Step 4: Run full verification**

Run:

```bash
uv run python -m pytest -q
uv run python -m app.cli.eval --subset curated_mvp --trials 1 --max-workers 1 --no-progress
uv run python -m app.cli.eval --subset curated_mvp --trials 1 --max-workers 1 --no-progress --live
```

Expected: PASS and curated scripted/live eval remains 11/11.
