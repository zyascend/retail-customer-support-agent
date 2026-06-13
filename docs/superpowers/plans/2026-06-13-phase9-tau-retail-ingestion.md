# Phase 9.1: Tau Retail Smoke Test Ingestion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接入 5-10 个 tau3 supported task 作为 smoke test，验证 task → EvalCase 转换 + 脚本式用户消息 + 宽松 reward evaluation 全链路。

**Architecture:** 新增 `app/eval/tau_loader.py` 负责 tau3 task 加载和 EvalCase 转换；修改 `cases.py` 添加 `tau_retail_smoke` subset；修改 `runner.py` 的 `classify_failure()` 增加 tau 宽松评估分支。不改 AgentRuntime / guard / tool 层。

**Tech Stack:** Python stdlib (json, pathlib), `app.config.AppConfig`, `app.eval.cases.EvalCase`, pytest.

---

## 文件结构

```
app/eval/
  tau_loader.py               ← 新增：tau3 task → EvalCase 转换器
  cases.py                    ← 修改：get_cases() 新增 tau_retail_smoke
  runner.py                   ← 修改：classify_failure() 新增 tau 宽松分支

tests/
  test_tau_loader.py           ← 新增：tau_loader 单元测试
```

---

### Task 1: Create tau_loader.py — tau3 task → EvalCase converter

**Files:**
- Create: `app/eval/tau_loader.py`
- Create: `tests/test_tau_loader.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tau_loader.py`:

```python
"""Tests for tau3 task loader and EvalCase converter."""

from pathlib import Path

from app.eval.tau_loader import (
    convert_task_to_eval_case,
    load_tau_tasks_from_dir,
    get_tau_smoke_cases,
    _build_user_message,
    _derive_db_assertions,
    _primary_capability_from_actions,
)

# Sample tau3 task matching the real format
SAMPLE_TASK = {
    "id": 0,
    "user_scenario": {
        "persona": None,
        "instructions": {
            "task_instructions": "You are detail-oriented.",
            "domain": "retail",
            "reason_for_call": (
                "You received your order #W2378156 and wish to exchange "
                "the mechanical keyboard for the same one but with clicky switches."
            ),
            "known_info": "You are Yusuf Rossi in zip code 19122.",
            "unknown_info": "You do not remember your email address.",
        },
    },
    "initial_state": None,
    "evaluation_criteria": {
        "actions": [
            {
                "action_id": "0_0",
                "name": "find_user_id_by_name_zip",
                "arguments": {"first_name": "Yusuf", "last_name": "Rossi", "zip": "19122"},
                "info": None,
            },
            {
                "action_id": "0_1",
                "name": "get_order_details",
                "arguments": {"order_id": "#W2378156"},
                "info": None,
            },
            {
                "action_id": "0_2",
                "name": "exchange_delivered_order_items",
                "arguments": {
                    "order_id": "#W2378156",
                    "item_ids": ["1151293680", "4983901480"],
                    "new_item_ids": ["7706410293", "7747408585"],
                    "payment_method_id": "credit_card_9513926",
                },
                "info": None,
            },
        ],
        "communicate_info": [],
        "nl_assertions": None,
        "reward_basis": ["DB", "NL_ASSERTION"],
    },
}

SAMPLE_TASK_NO_WRITE = {
    "id": 10,
    "user_scenario": {
        "persona": None,
        "instructions": {
            "task_instructions": "",
            "domain": "retail",
            "reason_for_call": "You want to check the status of order #W1234567.",
            "known_info": "Your email is test@example.com.",
            "unknown_info": "",
        },
    },
    "initial_state": None,
    "evaluation_criteria": {
        "actions": [
            {
                "action_id": "10_0",
                "name": "find_user_id_by_email",
                "arguments": {"email": "test@example.com"},
                "info": None,
            },
            {
                "action_id": "10_1",
                "name": "get_order_details",
                "arguments": {"order_id": "#W1234567"},
                "info": None,
            },
        ],
        "communicate_info": [],
        "nl_assertions": None,
        "reward_basis": ["DB"],
    },
}


class TestBuildUserMessage:
    def test_builds_message_from_all_fields(self):
        """_build_user_message concatenates reason + known + unknown info."""
        msg = _build_user_message(SAMPLE_TASK)
        assert "exchange" in msg.lower()
        assert "Yusuf Rossi" in msg
        assert "do not remember your email" in msg

    def test_handles_empty_unknown_info(self):
        """_build_user_message works when unknown_info is empty."""
        msg = _build_user_message(SAMPLE_TASK_NO_WRITE)
        assert "check the status" in msg.lower()
        assert "test@example.com" in msg


class TestDeriveDbAssertions:
    def test_exchange_derives_item_assertion(self):
        """_derive_db_assertions for exchange returns expected item ids."""
        result = _derive_db_assertions(SAMPLE_TASK)
        assert result is not None  # exchange IS a write

    def test_no_write_task_returns_empty(self):
        """_derive_db_assertions returns empty for read-only tasks."""
        result = _derive_db_assertions(SAMPLE_TASK_NO_WRITE)
        assert result == {}


class TestConvertTaskToEvalCase:
    def test_converts_write_task(self):
        """convert_task_to_eval_case produces valid EvalCase for write task."""
        case = convert_task_to_eval_case(SAMPLE_TASK, "tau_retail_smoke")
        assert case is not None
        assert case.case_id == "tau_0"
        assert case.subset == "tau_retail_smoke"
        assert len(case.messages) == 1
        assert case.messages[0]["role"] == "user"
        assert "exchange" in case.expected_tool_names
        assert "get_order_details" in case.expected_tool_names
        assert case.expected_intent in ("exchange", "exchange_items")
        assert case.max_turns == 5

    def test_converts_read_only_task(self):
        """convert_task_to_eval_case sets expected_no_write for read-only tasks."""
        case = convert_task_to_eval_case(SAMPLE_TASK_NO_WRITE, "tau_retail_smoke")
        assert case is not None
        assert case.case_id == "tau_10"
        assert case.expected_no_write is True
        assert "get_order_details" in case.expected_tool_names

    def test_respects_supported_filter(self):
        """convert_task_to_eval_case returns the case regardless of supported_ids (caller filters)."""
        case = convert_task_to_eval_case(SAMPLE_TASK, "tau_retail_smoke")
        assert case is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run python -m pytest tests/test_tau_loader.py -v
```
Expected: all FAIL with ImportError.

- [ ] **Step 3: Implement tau_loader.py**

Create `app/eval/tau_loader.py`:

```python
"""Tau3 retail task → EvalCase converter for Phase 9 ingestion.

Reads tau3 tasks.json and converts supported tasks into EvalCase objects
that the existing CuratedEvalRunner can execute.

Phase 9.1 (smoke test): script-based single-turn user message.
Phase 9.2 (full ingestion): template-based UserSimulator for multi-turn.
"""

from __future__ import annotations

import json
from dataclasses import field
from pathlib import Path
from typing import List, Optional

from app.config import AppConfig
from app.eval.cases import EvalCase

# Map tool names to intents (matching existing eval conventions)
TOOL_TO_INTENT: dict[str, str] = {
    "cancel_pending_order": "cancel_order",
    "return_delivered_order_items": "return_items",
    "exchange_delivered_order_items": "exchange_items",
    "modify_pending_order_address": "modify_order_address",
    "modify_pending_order_items": "modify_order_items",
    "modify_pending_order_payment": "modify_order_payment",
    "modify_user_address": "modify_user_address",
    "transfer_to_human_agents": "transfer",
}

# Write tools that trigger DB assertions
WRITE_TOOLS: set[str] = set(TOOL_TO_INTENT.keys())

# Smoke test task IDs: prioritize task_issues (4,5,7) + diverse capabilities
SMOKE_TASK_IDS: set[str] = {"3", "4", "5", "7", "16", "17", "22", "40"}


def load_tau_tasks_from_dir(retail_dir: Path) -> list[dict]:
    """Load all tau3 tasks from the retail domain directory."""
    tasks_path = retail_dir / "tasks.json"
    with open(tasks_path, encoding="utf-8") as f:
        return json.load(f)


def _build_user_message(task: dict) -> str:
    """Build a single user message from tau3 user_scenario instructions.

    Concatenates reason_for_call + known_info + unknown_info into one
    natural-language message that provies the agent with all information
    the user would eventually reveal during a multi-turn conversation.
    """
    instructions = task.get("user_scenario", {}).get("instructions", {})
    reason = instructions.get("reason_for_call", "")
    known = instructions.get("known_info", "")
    unknown = instructions.get("unknown_info", "")

    parts = []
    if reason:
        parts.append(reason.strip())
    if known:
        parts.append(known.strip())
    if unknown:
        parts.append(unknown.strip())
    return " ".join(parts)


def _derive_db_assertions(task: dict) -> dict:
    """Derive expected DB assertions from tau3 evaluation criteria actions.

    For write tools, extracts the key arguments that should result in
    DB state changes (e.g., new_item_ids for exchange, order_id for cancel).
    """
    actions = task.get("evaluation_criteria", {}).get("actions", [])
    assertions: dict = {}

    for action in actions:
        name = action.get("name", "")
        args = action.get("arguments", {})

        if name == "cancel_pending_order":
            assertions["order_id"] = args.get("order_id", "")
        elif name == "return_delivered_order_items":
            assertions["order_id"] = args.get("order_id", "")
            if "item_ids" in args:
                assertions["returned_item_ids"] = args["item_ids"]
        elif name == "exchange_delivered_order_items":
            assertions["order_id"] = args.get("order_id", "")
            if "new_item_ids" in args:
                assertions["new_item_ids"] = args["new_item_ids"]
        elif name in ("modify_pending_order_address",):
            assertions["order_id"] = args.get("order_id", "")
        elif name in ("modify_pending_order_items",):
            assertions["order_id"] = args.get("order_id", "")
            if "new_item_ids" in args:
                assertions["new_item_ids"] = args["new_item_ids"]
        elif name in ("modify_pending_order_payment",):
            assertions["order_id"] = args.get("order_id", "")
        elif name in ("modify_user_address",):
            pass  # user address change, no order-level assertion

    return assertions


def _primary_capability_from_actions(actions: list[dict]) -> str:
    """Determine the primary capability from tau3 action names."""
    for action in actions:
        name = action.get("name", "")
        if name in TOOL_TO_INTENT:
            return TOOL_TO_INTENT[name]
    return "lookup"


def _has_write_action(actions: list[dict]) -> bool:
    """Check if any action is a write operation."""
    return any(a.get("name", "") in WRITE_TOOLS for a in actions)


def convert_task_to_eval_case(task: dict, subset: str) -> Optional[EvalCase]:
    """Convert a single tau3 task to an EvalCase.

    Args:
        task: Raw tau3 task dict from tasks.json.
        subset: Eval subset name (e.g., "tau_retail_smoke").

    Returns:
        EvalCase if conversion succeeds, None if task should be skipped.
    """
    task_id = str(task["id"])
    actions = task.get("evaluation_criteria", {}).get("actions", [])

    # No actions → skip
    if not actions:
        return None

    action_names = [a.get("name", "") for a in actions]
    has_write = _has_write_action(actions)
    capability = _primary_capability_from_actions(actions)
    user_message = _build_user_message(task)
    db_assertions = _derive_db_assertions(task) if has_write else {}

    # Determine expected_intent: use the first write tool, or "lookup"
    expected_intent = capability if capability != "lookup" else "lookup"

    return EvalCase(
        case_id=f"tau_{task_id}",
        category=capability,
        messages=[{"role": "user", "content": user_message}],
        expected_user_id="",  # tau3 smoke: skip user_id check (loose eval)
        expected_intent=expected_intent,
        expected_tool_names=action_names,
        expected_tool_sequence=action_names,
        expected_no_write=not has_write,
        expected_db_assertions=db_assertions,
        max_turns=5,
        subset=subset,
        capability=capability,
        scenario_family="tau3",
    )


def get_tau_smoke_cases(config: AppConfig) -> list[EvalCase]:
    """Return 5-10 selected supported tau3 tasks as EvalCase list.

    Selection priority:
    1. Task 4, 5, 7 (known task_issues - verify our agent improves)
    2. Diverse write capabilities: cancel, exchange, modify_items, modify_address
    3. Mix of train and test splits
    """
    from app.analysis.tau_task_analyzer import (
        _resolve_tau3_retail_dir,
        load_tasks,
        load_splits,
        classify_task,
    )

    retail_dir = _resolve_tau3_retail_dir(config)
    tasks = load_tasks(retail_dir)
    splits = load_splits(retail_dir)

    cases: list[EvalCase] = []
    smoke_ids_used: set[str] = set()

    # First pass: include the designated smoke task IDs if they are supported
    for task in tasks:
        tid = str(task["id"])
        if tid in SMOKE_TASK_IDS:
            classification = classify_task(task, splits)
            if classification.status == "supported":
                case = convert_task_to_eval_case(task, "tau_retail_smoke")
                if case is not None:
                    cases.append(case)
                    smoke_ids_used.add(tid)

    # Second pass: if we have < 5 cases, fill from remaining supported tasks
    if len(cases) < 5:
        for task in tasks:
            tid = str(task["id"])
            if tid in smoke_ids_used:
                continue
            classification = classify_task(task, splits)
            if classification.status != "supported":
                continue
            case = convert_task_to_eval_case(task, "tau_retail_smoke")
            if case is not None:
                cases.append(case)
                smoke_ids_used.add(tid)
                if len(cases) >= 10:
                    break

    return cases
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run python -m pytest tests/test_tau_loader.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/eval/tau_loader.py tests/test_tau_loader.py
git commit -m "feat: Phase 9.1 tau_loader - tau3 task → EvalCase 转换"
```

---

### Task 2: Add tau_retail_smoke subset to cases.py

**Files:**
- Modify: `app/eval/cases.py` (add tau_retail_smoke branch in get_cases)

- [ ] **Step 1: Test that current get_cases rejects the new subset**

```bash
uv run python -c "from app.eval.cases import get_cases; get_cases('tau_retail_smoke')"
```
Expected: `ValueError: unsupported subset: tau_retail_smoke`

- [ ] **Step 2: Add tau_retail_smoke branch**

Edit `app/eval/cases.py`, in `get_cases()` (around line 955), add before the `raise ValueError`:

```python
    if subset == "tau_retail_smoke":
        from app.config import resolve_config
        from app.eval.tau_loader import get_tau_smoke_cases

        return get_tau_smoke_cases(resolve_config())
```

The full `get_cases()` should now be:

```python
def get_cases(subset: str) -> List[EvalCase]:
    if subset == "curated_mvp":
        return list(CURATED_MVP_CASES)
    if subset == "generalized_mvp":
        return list(GENERALIZED_MVP_CASES)
    if subset == "synthetic_seeded_v1":
        return list(SYNTHETIC_SEEDED_V1_CASES)
    if subset == "generalization":
        from app.synthetic.families import build_generalization_cases

        return build_generalization_cases()
    if subset == "generalization_exploratory":
        from app.synthetic.families import build_generalization_exploratory_cases

        return build_generalization_exploratory_cases()
    if subset == "tau_retail_smoke":
        from app.config import resolve_config
        from app.eval.tau_loader import get_tau_smoke_cases

        return get_tau_smoke_cases(resolve_config())
    raise ValueError("unsupported subset: " + subset)
```

- [ ] **Step 3: Verify get_cases returns cases**

```bash
uv run python -c "
from app.config import resolve_config
from app.eval.cases import get_cases
cases = get_cases('tau_retail_smoke')
print(f'Loaded {len(cases)} smoke test cases:')
for c in cases:
    print(f'  {c.case_id}: {c.category} (write={not c.expected_no_write})')
"
```
Expected: 5-10 cases listed with diverse capabilities.

- [ ] **Step 4: Verify existing subsets still work**

```bash
uv run python -c "
from app.eval.cases import get_cases
assert len(get_cases('curated_mvp')) == 11
assert len(get_cases('generalized_mvp')) == 30
print('Existing subsets OK')
"
```

- [ ] **Step 5: Commit**

```bash
git add app/eval/cases.py
git commit -m "feat: Phase 9.1 cases.py 新增 tau_retail_smoke subset"
```

---

### Task 3: Add loose evaluation for tau subsets in runner.py

**Files:**
- Modify: `app/eval/runner.py` (modify classify_failure for tau subsets)

- [ ] **Step 1: Understand the change needed**

The `classify_failure()` function in `runner.py` (line ~486) checks several conditions in order. For tau subsets, we want looser checks:
- Skip `expected_user_id` check (tau3 cases set it to "")
- Skip `expected_intent` check (tau3 intent may not match exactly)
- Skip `expected_tool_sequence` check (order not enforced)
- Skip `expected_confirmation_status` check (not set)
- Keep: tool name check (core tools), guard block check, mutation check, DB assertion check

- [ ] **Step 2: Write a test for tau loose evaluation**

Add to `tests/test_tau_loader.py`:

```python
"""Test tau subset loose evaluation rules."""
from app.eval.runner import classify_failure


class TestTauLooseEvaluation:
    def test_tau_subset_skips_user_id_check(self):
        """For tau subsets, auth mismatch does not trigger auth_failure."""
        result = classify_failure(
            case=_make_tau_case(expected_user_id=""),
            authenticated_user_id="some_other_user",
            final_intent="lookup",
            write_locks=[],
            actual_order_status=None,
            assistant_messages=["Here is your order status."],
            tool_names=["find_user_id_by_email", "get_order_details"],
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="",
            db_assertion_failures=None,
        )
        # Should NOT be auth_failure for tau subsets
        assert result != "auth_failure"

    def test_tau_subset_still_checks_tools(self):
        """For tau subsets, missing core tools still triggers wrong_tool."""
        result = classify_failure(
            case=_make_tau_case(expected_tool_names=["get_order_details"]),
            authenticated_user_id="",
            final_intent="lookup",
            write_locks=[],
            actual_order_status=None,
            assistant_messages=["Sorry, I cannot help."],
            tool_names=[],  # nothing called
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="",
            db_assertion_failures=None,
        )
        assert result == "wrong_tool"

    def test_tau_subset_still_checks_unexpected_mutation(self):
        """For tau subsets, no-write tasks with write locks trigger unexpected_mutation."""
        result = classify_failure(
            case=_make_tau_case(expected_no_write=True),
            authenticated_user_id="",
            final_intent="lookup",
            write_locks=["order:123:cancel"],  # unexpected write!
            actual_order_status=None,
            assistant_messages=["Done."],
            tool_names=["cancel_pending_order"],
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="",
            db_assertion_failures=None,
        )
        assert result == "unexpected_mutation"


def _make_tau_case(**overrides) -> EvalCase:
    """Helper to create a minimal tau EvalCase for testing."""
    from dataclasses import replace

    base = EvalCase(
        case_id="tau_test",
        category="lookup",
        messages=[{"role": "user", "content": "test"}],
        expected_user_id="",
        expected_intent="lookup",
        subset="tau_retail_smoke",
    )
    return replace(base, **overrides)
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run python -m pytest tests/test_tau_loader.py::TestTauLooseEvaluation -v
```
Expected: FAIL (current classify_failure produces auth_failure).

- [ ] **Step 4: Modify classify_failure for tau loose evaluation**

In `app/eval/runner.py`, modify `classify_failure()` to add a tau subset guard at the top:

```python
def classify_failure(
    case: EvalCase,
    authenticated_user_id: str,
    final_intent: str,
    write_locks: List[str],
    actual_order_status: Optional[str],
    assistant_messages: List[str],
    tool_names: List[str],
    guard_block_reasons: List[str],
    tool_errors: int,
    guard_blocks: int,
    pending_action: bool,
    llm_errors: int,
    confirmation_status: str,
    db_assertion_failures: Optional[List[str]] = None,
) -> Optional[str]:
    # Phase 9 tau subsets: loose evaluation (Phase 9.1 smoke test)
    is_tau = case.subset.startswith("tau_retail_") if case.subset else False

    if llm_errors:
        return "llm_json_failure"

    # Tau subsets skip user_id and intent strict checks
    if not is_tau:
        if authenticated_user_id != case.expected_user_id:
            return "auth_failure"
        if final_intent != case.expected_intent:
            return "wrong_intent"

    missing_tools = [
        tool_name
        for tool_name in case.expected_tool_names
        if tool_name not in tool_names
    ]
    if missing_tools:
        return "wrong_tool"
    if tool_errors:
        return "tool_exception"
    if case.expected_guard_block_reason:
        if case.expected_guard_block_reason not in guard_block_reasons:
            return "expected_guard_block_missing"
    elif guard_blocks:
        return "guard_blocked"

    # Tau subsets skip confirmation status check
    if not is_tau:
        if case.expected_confirmation_status:
            if confirmation_status != case.expected_confirmation_status:
                return "confirmation_status_mismatch"

    if pending_action:
        return "confirmation_failure"
    if case.expected_no_write and write_locks:
        return "unexpected_mutation"
    if case.expected_write_lock and case.expected_write_lock not in write_locks:
        return "mutation_missing"

    # Tau subsets skip order_status check (DB assertions cover this)
    if not is_tau:
        if case.expected_order_status and actual_order_status != case.expected_order_status:
            return "db_state_mismatch"

    if db_assertion_failures:
        return "db_assertion_mismatch"

    if not is_tau:
        if case.expected_assistant_contains:
            transcript = "\n".join(assistant_messages)
            if case.expected_assistant_contains not in transcript:
                return "response_mismatch"

    # Tau subsets skip tool_sequence check
    if not is_tau:
        if case.expected_tool_sequence:
            sequence_cursor = 0
            for tool_name in tool_names:
                if tool_name == case.expected_tool_sequence[sequence_cursor]:
                    sequence_cursor += 1
                    if sequence_cursor == len(case.expected_tool_sequence):
                        break
            if sequence_cursor < len(case.expected_tool_sequence):
                return "wrong_tool_sequence"
    return None
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run python -m pytest tests/test_tau_loader.py::TestTauLooseEvaluation -v
```
Expected: all PASS.

- [ ] **Step 6: Run existing eval tests to verify no regression**

```bash
uv run python -m pytest tests/test_eval_runner.py -v
```
Expected: all existing tests still PASS.

- [ ] **Step 7: Commit**

```bash
git add app/eval/runner.py tests/test_tau_loader.py
git commit -m "feat: Phase 9.1 classify_failure 新增 tau 宽松评估分支"
```

---

### Task 4: Run smoke test and verify report

- [ ] **Step 1: Run the tau_retail_smoke eval**

```bash
uv run phase2-eval --subset tau_retail_smoke --trials 1 --no-progress --json
```
Expected: eval completes, report JSON written to `artifacts/phase2/reports/`.

- [ ] **Step 2: Inspect the report**

```bash
uv run python -c "
import json, glob
reports = sorted(glob.glob('artifacts/phase2/reports/*.json'))
latest = reports[-1]
with open(latest) as f:
    report = json.load(f)
print(f'Subset: {report[\"subset\"]}')
print(f'Cases: {report[\"case_count\"]}')
print(f'Passed: {report[\"passed_count\"]}')
print(f'Pass rate: {report[\"pass_rate\"]}')
print(f'Dataset root: {report[\"dataset_root\"]}')
print()
for r in report['results']:
    print(f'  {r[\"case_id\"]}: passed={r[\"passed\"]}, label={r[\"failure_label\"]}, tools={len(r.get(\"tool_names\", []))} calls')
"
```

- [ ] **Step 3: Verify at least one write success and one no-write success**

Check that:
- At least one result has `passed=True` and `db_changed=True`
- At least one result has `passed=True` and `db_changed=False`
- No unexpected mutations

- [ ] **Step 4: Commit report artifacts reference**

```bash
git add -A
git commit -m "chore: Phase 9.1 tau_retail_smoke eval 运行结果"
```

---

### Task 5: Final validation

- [ ] **Step 1: Full test suite**

```bash
uv run python -m pytest tests/ -q
```
Expected: all tests pass (existing + new tau tests).

- [ ] **Step 2: Ruff lint**

```bash
uv run ruff check .
```
Expected: clean.

- [ ] **Step 3: Verify existing subsets still work**

```bash
uv run phase2-eval --subset curated_mvp --trials 1 --no-progress --json
uv run phase2-eval --subset generalized_mvp --trials 1 --no-progress --json
```
Expected: both pass (30/30 generalized_mvp).

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: Phase 9.1 最终验证 - full test suite + ruff clean"
```
