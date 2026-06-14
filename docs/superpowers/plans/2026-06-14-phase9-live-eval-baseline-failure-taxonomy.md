# Phase 9 Live Eval Baseline And Failure Taxonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make live eval results baselineable, comparable, and triageable so every failed live case has an actionable root cause.

**Architecture:** Keep production runtime unchanged. Extend eval-only surfaces: case subsets, report metadata, comparison artifacts, and live triage output. Existing `CuratedEvalRunner`, `build_report_artifact()`, and `app/eval/live_triage.py` remain the integration points.

**Tech Stack:** Python 3.11, pytest, ruff, existing eval runner/report artifacts, DeepSeek live provider via `--live`.

---

### Task 1: Pin Live Baseline Subsets

**Files:**
- Modify: `app/eval/cases.py`
- Modify: `tests/test_eval_runner.py`

- [x] **Step 1: Write failing subset contract tests**

Add these tests to `tests/test_eval_runner.py`:

```python
def test_live_smoke_core_subset_pins_representative_cases(self):
    cases = get_cases("live_smoke_core")
    self.assertEqual(
        [case.case_id for case in cases],
        [
            "lookup_pending_order",
            "cancel_pending_order",
            "return_delivered_order_item",
            "exchange_delivered_order_item",
            "deny_cancel_confirmation",
            "block_wrong_user_order_access",
        ],
    )
    self.assertTrue(all(case.subset == "live_smoke_core" for case in cases))


def test_live_guard_smoke_subset_pins_guard_cases(self):
    cases = get_cases("live_guard_smoke")
    self.assertEqual(
        [case.case_id for case in cases],
        [
            "block_cancel_processed_order",
            "block_return_pending_order",
            "block_wrong_user_order_access",
        ],
    )
    self.assertTrue(all(case.category == "guard" for case in cases))
    self.assertTrue(all(case.expected_no_write for case in cases))
```

- [x] **Step 2: Verify tests fail**

Run: `uv run python -m pytest tests/test_eval_runner.py::CuratedEvalTests::test_live_smoke_core_subset_pins_representative_cases tests/test_eval_runner.py::CuratedEvalTests::test_live_guard_smoke_subset_pins_guard_cases -q`

Expected: FAIL with unknown subset or different case ids.

- [x] **Step 3: Implement pinned subsets**

Add this helper near the curated case definitions in `app/eval/cases.py`:

```python
LIVE_SMOKE_CORE_CASE_IDS = (
    "lookup_pending_order",
    "cancel_pending_order",
    "return_delivered_order_item",
    "exchange_delivered_order_item",
    "deny_cancel_confirmation",
    "block_wrong_user_order_access",
)

LIVE_GUARD_SMOKE_CASE_IDS = (
    "block_cancel_processed_order",
    "block_return_pending_order",
    "block_wrong_user_order_access",
)


def _clone_case_for_subset(case: EvalCase, subset: str) -> EvalCase:
    return EvalCase(
        **{
            **case.__dict__,
            "required_tools": set(case.required_tools),
            "forbidden_tools": set(case.forbidden_tools),
            "subset": subset,
        }
    )


def _curated_cases_by_id(case_ids: tuple[str, ...], *, subset: str) -> list[EvalCase]:
    by_id = {case.case_id: case for case in CURATED_MVP_CASES}
    return [_clone_case_for_subset(by_id[case_id], subset) for case_id in case_ids]
```

Then add branches inside `get_cases()`:

```python
if subset == "live_smoke_core":
    return _curated_cases_by_id(LIVE_SMOKE_CORE_CASE_IDS, subset=subset)
if subset == "live_guard_smoke":
    return _curated_cases_by_id(LIVE_GUARD_SMOKE_CASE_IDS, subset=subset)
```

- [x] **Step 4: Verify subset tests pass**

Run: `uv run python -m pytest tests/test_eval_runner.py::CuratedEvalTests::test_live_smoke_core_subset_pins_representative_cases tests/test_eval_runner.py::CuratedEvalTests::test_live_guard_smoke_subset_pins_guard_cases -q`

Expected: PASS.

### Task 2: Add Baseline Metadata To Eval Reports

**Files:**
- Create: `app/eval/baseline.py`
- Modify: `app/eval/runner.py`
- Modify: `app/eval/metrics.py`
- Modify: `tests/test_eval_runner.py`

- [x] **Step 1: Write failing report metadata test**

Add this test to `tests/test_eval_runner.py`:

```python
def test_eval_report_contains_phase9_baseline_metadata(self):
    with tempfile.TemporaryDirectory() as tmp:
        config = resolve_config(artifact_dir=tmp)
        summary = CuratedEvalRunner(
            config=config,
            artifact_dir=Path(tmp),
        ).run(subset="live_guard_smoke", trials=1)
        report = json.loads(
            Path(summary.report_artifact_path).read_text(encoding="utf-8")
        )

    metadata = report["baseline_metadata"]
    self.assertEqual(metadata["eval_backend"], "scripted_offline_demo")
    self.assertEqual(metadata["subset"], "live_guard_smoke")
    self.assertIn("model", metadata)
    self.assertIn("provider", metadata)
    self.assertRegex(metadata["prompt_hash"], r"^[0-9a-f]{64}$")
    self.assertRegex(metadata["tool_schema_hash"], r"^[0-9a-f]{64}$")
    self.assertRegex(metadata["action_specs_hash"], r"^[0-9a-f]{64}$")
    self.assertIn("total_token_usage", report["metrics"])
    self.assertIn("average_llm_loop_iterations", report["metrics"])
    self.assertIn("llm_loop_iterations", report["results"][0])
    self.assertIn("llm_token_usage", report["results"][0])
```

- [x] **Step 2: Verify test fails**

Run: `uv run python -m pytest tests/test_eval_runner.py::CuratedEvalTests::test_eval_report_contains_phase9_baseline_metadata -q`

Expected: FAIL because `baseline_metadata` is absent.

- [x] **Step 3: Implement metadata builder**

Create `app/eval/baseline.py`:

```python
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.agent.action_specs import WRITE_ACTION_REGISTRY
from app.agent.prompts import prompt_metadata
from app.config import AppConfig
from app.ops.serialization import stable_hash
from app.tools.registry import ToolRegistry
from app.tools.retail_adapter import RetailAdapter


def build_baseline_metadata(
    *,
    config: AppConfig,
    subset: str,
    eval_backend: str,
    live: bool,
    require_llm: bool,
) -> dict[str, Any]:
    prompt_info = prompt_metadata()
    registry = ToolRegistry(RetailAdapter(config).create_runtime().tools)
    provider = "deepseek" if live or require_llm else "offline_demo_harness"
    return {
        "subset": subset,
        "eval_backend": eval_backend,
        "model": config.default_agent_model,
        "provider": provider,
        "prompt_hash": stable_hash(prompt_info),
        "tool_schema_hash": stable_hash(registry.tool_schemas_for_llm()),
        "action_specs_hash": stable_hash(
            [asdict(spec) for spec in WRITE_ACTION_REGISTRY]
        ),
    }
```

Extend `EvalRunSummary` in `app/eval/runner.py`:

```python
baseline_metadata: Dict[str, Any] = field(default_factory=dict)
```

When building the summary, compute `eval_backend = self._eval_backend()` once and pass:

```python
baseline_metadata=build_baseline_metadata(
    config=self.config,
    subset=subset,
    eval_backend=eval_backend,
    live=self.live,
    require_llm=self.require_llm,
),
eval_backend=eval_backend,
```

In `app/eval/metrics.py`, add to `build_report_artifact()`:

```python
"baseline_metadata": summary.baseline_metadata,
```

Also extend `compute_metrics()` so report-level metrics expose the existing per-case LLM fields:

```python
token_totals: Dict[str, int] = {}
for result in result_list:
    for key, value in (result.llm_token_usage or {}).items():
        if isinstance(value, int):
            token_totals[key] = token_totals.get(key, 0) + value
loop_iterations = [result.llm_loop_iterations for result in result_list]
...
"total_token_usage": token_totals,
"average_llm_loop_iterations": (
    round(sum(loop_iterations) / total, 3) if total else 0.0
),
```

Keep the existing field names `llm_token_usage`, `llm_loop_iterations`, `tool_call_count`, and `guard_blocks` for backwards compatibility. The Phase 9 docs can explain these are the concrete code fields for the higher-level `token_usage` and `guard_block_count` concepts.

- [x] **Step 4: Verify metadata test passes**

Run: `uv run python -m pytest tests/test_eval_runner.py::CuratedEvalTests::test_eval_report_contains_phase9_baseline_metadata -q`

Expected: PASS.

### Task 3: Add Actionable Root Cause Taxonomy

**Files:**
- Modify: `app/eval/live_triage.py`
- Modify: `tests/test_live_eval_triage.py`

- [x] **Step 1: Write failing taxonomy tests**

Create or extend `tests/test_live_eval_triage.py`:

```python
from app.eval.live_triage import infer_root_cause, summarize_failure


def test_infer_root_cause_maps_tool_selection_to_prompt_gap() -> None:
    result = {
        "case_id": "cancel_pending_order",
        "passed": False,
        "failure_label": "wrong_tool",
        "tool_call_count": 2,
        "successful_tool_calls": 2,
    }

    assert infer_root_cause(result) == "prompt_gap"


def test_summarize_failure_includes_actionable_root_cause() -> None:
    failure = summarize_failure(
        {
            "case_id": "block_wrong_user_order_access",
            "passed": False,
            "failure_label": "expected_guard_block_missing",
            "actual_guard_block_reasons": [],
            "tool_call_count": 1,
        }
    )

    assert failure["root_cause"] == "guard_policy_gap"
    assert "suggested_next_action" in failure
```

- [x] **Step 2: Verify tests fail**

Run: `uv run python -m pytest tests/test_live_eval_triage.py -q`

Expected: FAIL because `infer_root_cause()` and `root_cause` are absent.

- [x] **Step 3: Implement root cause mapping**

In `app/eval/live_triage.py`, add constants:

```python
RUNTIME_BUG = "runtime_bug"
TOOL_SCHEMA_GAP = "tool_schema_gap"
PROMPT_GAP = "prompt_gap"
MODEL_REASONING_GAP = "model_reasoning_gap"
GUARD_POLICY_GAP = "guard_policy_gap"
DATA_FIXTURE_GAP = "data_fixture_gap"
PROVIDER_ERROR = "provider_error"
EXPECTED_BEHAVIOR_UNCLEAR = "expected_behavior_unclear"
```

Add:

```python
def infer_root_cause(result: Mapping[str, Any]) -> str:
    if result.get("provider_error") or result.get("runtime_error"):
        return PROVIDER_ERROR
    label = str(result.get("failure_label") or "")
    if label in {"tool_exception"}:
        return RUNTIME_BUG
    if label in {"wrong_tool", "required_tool_missing", "forbidden_tool_called", "wrong_tool_sequence"}:
        return PROMPT_GAP
    if label in {"llm_json_failure"}:
        return TOOL_SCHEMA_GAP
    if label in {"expected_guard_block_missing", "guard_blocked", "confirmation_status_mismatch", "confirmation_failure"}:
        return GUARD_POLICY_GAP
    if label in {"db_state_mismatch", "db_assertion_mismatch", "unexpected_mutation", "mutation_missing"}:
        return DATA_FIXTURE_GAP
    if label in {"response_mismatch"}:
        return MODEL_REASONING_GAP
    return EXPECTED_BEHAVIOR_UNCLEAR
```

Then include this in `summarize_failure()`:

```python
"root_cause": infer_root_cause(result),
```

And render it in `format_markdown()`:

```python
f"- Root cause: `{failure.get('root_cause')}`",
```

- [x] **Step 4: Verify taxonomy tests pass**

Run: `uv run python -m pytest tests/test_live_eval_triage.py -q`

Expected: PASS.

### Task 4: Generate Triage Bundles From Failed Live Reports

**Files:**
- Create: `app/eval/triage_bundle.py`
- Modify: `app/eval/live_triage.py`
- Modify: `tests/test_live_eval_triage.py`

- [x] **Step 1: Write failing bundle test**

Add this test to `tests/test_live_eval_triage.py`:

```python
import json

from app.eval.triage_bundle import build_triage_bundle


def test_build_triage_bundle_extracts_trace_context(tmp_path) -> None:
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(
            {
                "messages": [
                    {"role": "user", "content": "Cancel order #W123."},
                    {"role": "assistant", "content": "Please confirm."},
                ],
                "metadata": {"llm_responses": [{"finish_reason": "tool_calls"}]},
                "tool_calls": [
                    {
                        "tool_name": "cancel_pending_order",
                        "status": "blocked",
                        "error": "ownership_violation",
                        "block_context": {"resource_type": "order", "resource_id": "#W123"},
                    }
                ],
                "db_assertions": {"order_status": {"expected": "pending", "actual": "cancelled"}},
            }
        ),
        encoding="utf-8",
    )
    result = {
        "case_id": "block_wrong_user_order_access",
        "failure_label": "expected_guard_block_missing",
        "trace_artifact_path": str(trace_path),
        "expected_actual_diff": {"order_status": {"expected": "pending", "actual": "cancelled"}},
    }

    bundle = build_triage_bundle(result)

    assert bundle["case_id"] == "block_wrong_user_order_access"
    assert bundle["user_messages"] == ["Cancel order #W123."]
    assert bundle["tool_calls"][0]["block_context"]["resource_id"] == "#W123"
    assert bundle["db_assertion_diff"]["order_status"]["actual"] == "cancelled"
```

- [x] **Step 2: Verify test fails**

Run: `uv run python -m pytest tests/test_live_eval_triage.py::test_build_triage_bundle_extracts_trace_context -q`

Expected: FAIL because `app.eval.triage_bundle` does not exist.

- [x] **Step 3: Implement bundle extraction**

Create `app/eval/triage_bundle.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def build_triage_bundle(result: Mapping[str, Any]) -> dict[str, Any]:
    trace_path = result.get("trace_artifact_path")
    trace = _read_trace(trace_path) if trace_path else {}
    return {
        "case_id": result.get("case_id"),
        "failure_label": result.get("failure_label"),
        "trace_artifact_path": trace_path,
        "user_messages": [
            message.get("content", "")
            for message in trace.get("messages", [])
            if message.get("role") == "user"
        ],
        "assistant_messages": [
            message.get("content", "")
            for message in trace.get("messages", [])
            if message.get("role") == "assistant"
        ],
        "llm_responses": trace.get("metadata", {}).get("llm_responses", []),
        "tool_calls": [
            {
                "tool_name": call.get("tool_name"),
                "status": call.get("status"),
                "error": call.get("error"),
                "block_context": call.get("block_context", {}),
                "observation": call.get("observation"),
            }
            for call in trace.get("tool_calls", [])
        ],
        "guard_context": [
            call.get("block_context", {})
            for call in trace.get("tool_calls", [])
            if call.get("block_context")
        ],
        "db_assertion_diff": result.get("expected_actual_diff", {}),
    }


def _read_trace(trace_path: object) -> dict[str, Any]:
    path = Path(str(trace_path))
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    return payload if isinstance(payload, dict) else {}
```

In `app/eval/live_triage.py`, import and add to `summarize_failure()`:

```python
from app.eval.triage_bundle import build_triage_bundle

...
"triage_bundle": build_triage_bundle(result),
```

- [x] **Step 4: Verify bundle tests pass**

Run: `uv run python -m pytest tests/test_live_eval_triage.py -q`

Expected: PASS.

### Task 5: Document Baseline Commands And Phase Review

**Files:**
- Modify: `docs/long-term-optimization-path.md`
- Modify: `docs/portfolio-architecture.md`
- Modify: `README.md`

- [x] **Step 1: Update docs**

Add a Phase 9 Review section to `docs/long-term-optimization-path.md` after the Phase 9 plan text:

```markdown
## Phase 9 Review

### 目标

- 固定 live eval baseline subsets。
- 让 live eval report 说明 model/provider/prompt/tool/action-spec identity。
- 让失败 case 输出 actionable root cause 和 triage bundle。

### 完成内容

- 新增 `live_smoke_core` 和 `live_guard_smoke` subsets。
- eval report 新增 `baseline_metadata`，包含 model、provider、prompt hash、tool schema hash、action specs hash 和 eval backend。
- live triage 新增 root cause taxonomy 与 trace-derived triage bundle。

### 架构边界检查

- production runtime 未新增 case-specific parser。
- live eval 仍是 manual/release smoke，不进入普通 CI gate。
- scripted/offline eval 与 live eval 在 report 中明确分层。

### 验证证据

- `uv run ruff check .`
- `uv run python -m pytest -q`
- `uv run python -m app.cli.eval --subset curated_mvp --trials 1 --max-workers 1 --no-progress`
- `uv run python -m app.cli.eval --subset live_smoke_core --trials 1 --max-workers 1 --no-progress --live`
- `uv run python -m app.cli.eval --subset live_guard_smoke --trials 1 --max-workers 1 --no-progress --live`

### 后续风险

- Phase 10 才优化 prompt/tool schema；Phase 9 只负责观测和归因。
```

In `README.md`, add manual commands:

```bash
uv run python -m app.cli.eval --subset live_smoke_core --trials 1 --max-workers 1 --no-progress --live
uv run python -m app.eval.live_triage artifacts/phase2/reports/<eval-run-id>.json
```

- [x] **Step 2: Run docs grep**

Run: `rg -n "live_smoke_core|live_guard_smoke|baseline_metadata|root cause|triage bundle" docs README.md`

Expected: output includes the new Phase 9 docs and README command.

### Task 6: Final Verification

**Files:**
- No additional edits unless verification finds issues.

- [ ] **Step 1: Run targeted tests**

Run:

```bash
uv run python -m pytest tests/test_eval_runner.py tests/test_live_eval_triage.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full verification**

Run:

```bash
uv run ruff check .
uv run python -m pytest -q
uv run python -m app.cli.eval --subset curated_mvp --trials 1 --max-workers 1 --no-progress
uv run python -m app.cli.eval --subset curated_mvp --trials 1 --max-workers 1 --no-progress --live
uv run python -m app.cli.eval --subset live_smoke_core --trials 1 --max-workers 1 --no-progress --live
uv run python -m app.cli.eval --subset live_guard_smoke --trials 1 --max-workers 1 --no-progress --live
```

Expected: ruff clean, pytest PASS, curated scripted/live PASS, and both live baseline subsets produce reports. If a live subset fails because the model behavior changed, run `uv run python -m app.eval.live_triage <report-path>` and record the root cause instead of changing production runtime.
