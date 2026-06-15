# Phase 10 Prompt Tool Schema Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Optimize LLM-visible prompt, tool schema, and state summary contracts so live eval relies less on runtime safety nets while preserving guarded writes.

**Architecture:** Keep production runtime boundaries unchanged. Extend eval-visible contracts by enriching `ToolRegistry` descriptions/schema, `ContextBuilder` summaries, and Phase 9 metrics with fallback counters. All changes remain derived from registry/action specs/session state instead of case-specific intent routing.

**Tech Stack:** Python 3.11, pytest, ruff, existing `AgentLoop`, `ToolRegistry`, `ContextBuilder`, and curated/live eval reports.

---

### Task 1: Add Fallback Counters To Turn And Eval Metrics

**Files:**
- Modify: `app/agent/models.py`
- Modify: `app/agent/llm_agent.py`
- Modify: `app/eval/runner.py`
- Modify: `app/eval/metrics.py`
- Modify: `tests/test_llm_agent.py`
- Modify: `tests/test_eval_runner.py`

- [x] **Step 1: Write failing turn counter test**

Add this test to `tests/test_llm_agent.py`:

```python
def test_auto_load_counter_is_recorded_when_guard_requires_prior_read() -> None:
    from app.agent.llm_agent import AgentLoop
    from app.agent.models import ToolCallRequest

    provider = ScriptedToolCallingProvider(
        responses=[
            ToolCallResponse(
                tool_calls=[
                    ToolCallRequest(
                        id="call_cancel",
                        tool_name="cancel_pending_order",
                        arguments={
                            "order_id": "#W5918442",
                            "reason": "no longer needed",
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            ToolCallResponse(
                assistant_content="I can help with that.",
                finish_reason="stop",
            ),
        ]
    )
    loop = AgentLoop(
        provider=provider,
        gateway=_gateway(),
        registry=_registry(),
        context_builder=_context_builder(),
    )

    result = loop.run_turn(_session(authenticated_user_id="sofia_rossi_8776"), "Cancel #W5918442.")

    assert result.turn.auto_load_count == 1
    assert any(step.node == "auto_load_order" for step in result.turn.steps)
```

- [x] **Step 2: Verify test fails**

Run:

```bash
uv run python -m pytest tests/test_llm_agent.py::test_auto_load_counter_is_recorded_when_guard_requires_prior_read -q
```

Expected: FAIL because `TurnContext` has no `auto_load_count`.

- [x] **Step 3: Implement turn counters**

Add these fields to `TurnContext` in `app/agent/models.py`:

```python
auto_load_count: int = 0
premature_refusal_corrected_count: int = 0
```

In `AgentLoop.run_turn()`, increment the premature refusal counter where `premature_refusal_corrected` is added:

```python
turn.premature_refusal_corrected_count += 1
```

In `_auto_load_missing_context()`, increment `turn.auto_load_count` immediately after a successful order or user auto-load:

```python
turn.auto_load_count += 1
```

- [x] **Step 4: Verify turn counter test passes**

Run:

```bash
uv run python -m pytest tests/test_llm_agent.py::test_auto_load_counter_is_recorded_when_guard_requires_prior_read -q
```

Expected: PASS.

- [x] **Step 5: Write failing eval aggregate metric test**

Extend the `_result()` helper in `tests/test_eval_runner.py` with:

```python
auto_load_count: int = 0,
premature_refusal_corrected_count: int = 0,
```

and pass these fields to `EvalCaseResult`.

Add this test:

```python
def test_metrics_aggregate_runtime_fallback_counters(self):
    metrics = compute_metrics(
        [
            _result("case_a", 0, auto_load_count=2, premature_refusal_corrected_count=1),
            _result("case_b", 0, auto_load_count=1, premature_refusal_corrected_count=0),
        ]
    )

    self.assertEqual(metrics["auto_load_count"], 3)
    self.assertEqual(metrics["premature_refusal_corrected_count"], 1)
```

- [x] **Step 6: Verify metric test fails**

Run:

```bash
uv run python -m pytest tests/test_eval_runner.py::CuratedEvalTests::test_metrics_aggregate_runtime_fallback_counters -q
```

Expected: FAIL because metrics do not include fallback counters.

- [x] **Step 7: Implement eval fields and metric aggregation**

Add fields to `EvalCaseResult` in `app/eval/runner.py`:

```python
auto_load_count: int = 0
premature_refusal_corrected_count: int = 0
```

When building LLM case results, set:

```python
auto_load_count=sum(turn.auto_load_count for turn in turn_contexts)
premature_refusal_corrected_count=sum(
    turn.premature_refusal_corrected_count for turn in turn_contexts
)
```

Add protocol attributes and aggregate totals in `app/eval/metrics.py`:

```python
auto_load_count = sum(result.auto_load_count for result in result_list)
premature_refusal_corrected_count = sum(
    result.premature_refusal_corrected_count for result in result_list
)
```

Return both values in the metrics dictionary.

- [x] **Step 8: Verify metric test passes**

Run:

```bash
uv run python -m pytest tests/test_eval_runner.py::CuratedEvalTests::test_metrics_aggregate_runtime_fallback_counters -q
```

Expected: PASS.

### Task 2: Strengthen Tool Descriptions As Selection Contracts

**Files:**
- Modify: `app/tools/registry.py`
- Modify: `tests/test_tool_schema.py`

- [x] **Step 1: Write failing tool description tests**

Add these tests to `tests/test_tool_schema.py`:

```python
def test_write_tool_descriptions_include_selection_contract() -> None:
    registry = _registry()
    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "cancel_pending_order"
    )
    description = schema["function"]["description"]

    assert "When to use:" in description
    assert "When not to use:" in description
    assert "Required prior reads:" in description
    assert "Guard blocks:" in description


def test_read_tool_description_tells_model_not_to_mutate() -> None:
    registry = _registry()
    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "get_order_details"
    )

    assert "Read-only" in schema["function"]["description"]
    assert "Do not use for writes" in schema["function"]["description"]
```

- [x] **Step 2: Verify description tests fail**

Run:

```bash
uv run python -m pytest tests/test_tool_schema.py::test_write_tool_descriptions_include_selection_contract tests/test_tool_schema.py::test_read_tool_description_tells_model_not_to_mutate -q
```

Expected: FAIL because descriptions are prose-only.

- [x] **Step 3: Implement structured selection descriptions**

Refactor `_tool_description_for_llm()` in `app/tools/registry.py` so every description includes a base sentence plus structured clauses. For write tools, include when-to-use, when-not-to-use, required prior reads, and guard-block guidance. For read tools, include read-only guidance and when to use.

- [x] **Step 4: Verify description tests pass**

Run:

```bash
uv run python -m pytest tests/test_tool_schema.py::test_write_tool_descriptions_include_selection_contract tests/test_tool_schema.py::test_read_tool_description_tells_model_not_to_mutate -q
```

Expected: PASS.

### Task 3: Strengthen Parameter Schema Constraints

**Files:**
- Modify: `app/tools/registry.py`
- Modify: `tests/test_tool_schema.py`

- [x] **Step 1: Write failing schema constraint tests**

Add these tests to `tests/test_tool_schema.py`:

```python
def test_payment_method_schema_uses_pattern() -> None:
    registry = _registry()
    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "return_delivered_order_items"
    )
    payment = schema["function"]["parameters"]["properties"]["payment_method_id"]

    assert payment["pattern"] == "^(credit_card|gift_card|paypal)_\\d+$"


def test_order_and_item_ids_use_patterns() -> None:
    registry = _registry()
    cancel = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "cancel_pending_order"
    )
    exchange = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "exchange_delivered_order_items"
    )

    assert cancel["function"]["parameters"]["properties"]["order_id"]["pattern"] == "^#W\\d+$"
    assert exchange["function"]["parameters"]["properties"]["item_ids"]["items"]["pattern"] == "^\\d+$"
    assert exchange["function"]["parameters"]["properties"]["new_item_ids"]["items"]["pattern"] == "^\\d+$"
```

- [x] **Step 2: Verify schema tests fail**

Run:

```bash
uv run python -m pytest tests/test_tool_schema.py::test_payment_method_schema_uses_pattern tests/test_tool_schema.py::test_order_and_item_ids_use_patterns -q
```

Expected: FAIL because patterns are absent.

- [x] **Step 3: Implement schema constraints**

Update `_property_schema()` in `app/tools/registry.py`:

```python
if arg_name == "order_id":
    result = {"type": "string", "pattern": "^#W\\d+$"}
elif arg_name in {"item_ids", "new_item_ids"}:
    result = {"type": "array", "items": {"type": "string", "pattern": "^\\d+$"}}
elif arg_name == "payment_method_id":
    result = {"type": "string", "pattern": "^(credit_card|gift_card|paypal)_\\d+$"}
else:
    result = {"type": "string"}
```

Keep existing descriptions and enums.

- [x] **Step 4: Verify schema tests pass**

Run:

```bash
uv run python -m pytest tests/test_tool_schema.py::test_payment_method_schema_uses_pattern tests/test_tool_schema.py::test_order_and_item_ids_use_patterns -q
```

Expected: PASS.

### Task 4: Enrich State Summary With Recent Runtime Signals

**Files:**
- Modify: `app/agent/context_builder.py`
- Modify: `tests/test_agent_core.py`

- [x] **Step 1: Write failing state summary test**

Add this test to `tests/test_agent_core.py`:

```python
def test_context_builder_includes_recent_tool_error_and_guard_block(self):
    state = SessionState(session_id="s1", authenticated_user_id="user_1")
    state.tool_results.append(
        ToolCallRecord(
            tool_name="cancel_pending_order",
            arguments={"order_id": "#W1", "reason": "no longer needed"},
            tool_kind="write",
            status="blocked",
            error="ownership_violation",
            block_context={"order_id": "#W1"},
        )
    )
    state.tool_results.append(
        ToolCallRecord(
            tool_name="get_order_details",
            arguments={"order_id": "#W404"},
            tool_kind="read",
            status="error",
            error="order_not_found",
        )
    )

    summary = ContextBuilder(policy_text="").build(state)

    self.assertIn("Recent guard block: cancel_pending_order ownership_violation", summary)
    self.assertIn("Recent tool error: get_order_details order_not_found", summary)
```

- [x] **Step 2: Verify state summary test fails**

Run:

```bash
uv run python -m pytest tests/test_agent_core.py::ContextBuilderTests::test_context_builder_includes_recent_tool_error_and_guard_block -q
```

Expected: FAIL because the summary omits recent runtime signals.

- [x] **Step 3: Implement runtime signal summary**

In `ContextBuilder.build()`, inspect recent `session.tool_results` in reverse order. Add at most one recent guard block and one recent tool error:

```python
if recent_guard_block:
    parts.append(f"Recent guard block: {tool_name} {error}")
if recent_tool_error:
    parts.append(f"Recent tool error: {tool_name} {error}")
```

- [x] **Step 4: Verify state summary test passes**

Run:

```bash
uv run python -m pytest tests/test_agent_core.py::ContextBuilderTests::test_context_builder_includes_recent_tool_error_and_guard_block -q
```

Expected: PASS.

### Task 5: Document Phase 10 Review And Run Verification

**Files:**
- Modify: `docs/long-term-optimization-path.md`
- Modify: `README.md`
- Modify: `docs/portfolio-architecture.md`

- [x] **Step 1: Update docs**

Document Phase 10 outputs:

- tool descriptions now expose when-to-use / when-not-to-use / required-prior-read / guard-block guidance.
- schemas now include stronger ID/payment patterns while staying registry-derived.
- state summaries include recent guard/tool errors.
- eval reports include `auto_load_count` and `premature_refusal_corrected_count`.

- [x] **Step 2: Run targeted tests**

Run:

```bash
uv run python -m pytest tests/test_tool_schema.py tests/test_llm_agent.py tests/test_eval_runner.py tests/test_agent_core.py -q
```

Expected: PASS.

- [x] **Step 3: Run static check**

Run:

```bash
uv run ruff check .
```

Expected: PASS.

- [x] **Step 4: Run full tests**

Run:

```bash
uv run python -m pytest -q
```

Expected: PASS.

- [x] **Step 5: Run eval validation**

Run:

```bash
uv run python -m app.cli.eval --subset curated_mvp --trials 1 --max-workers 1 --no-progress
uv run python -m app.cli.eval --subset curated_mvp --trials 1 --max-workers 1 --no-progress --live
uv run python -m app.cli.eval --subset live_smoke_core --trials 1 --max-workers 1 --no-progress --live
uv run python -m app.cli.eval --subset live_guard_smoke --trials 1 --max-workers 1 --no-progress --live
```

Expected: all commands exit 0. Record pass count and token usage from the generated reports.
