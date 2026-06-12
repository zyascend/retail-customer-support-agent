# Phase 5 Benchmark Generalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the retail support agent from the 11-case curated MVP into a roughly 30-case deterministic generalized MVP while filling the main missing transaction capabilities.

**Architecture:** Keep the current `AgentRuntime` and linear LangGraph shell stable while expanding deterministic intent, slot, planning, tool, and guard behavior. Add the generalized eval subset as the acceptance harness, then expose selected new cases in the existing workbench catalog without redesigning the UI.

**Tech Stack:** Python 3.12+, `unittest`, Pydantic compatibility layer, LangGraph shell, FastAPI workbench API, Vite + React workbench.

---

## Scope Check

This plan implements one coherent Phase 5 slice: benchmark generalization through capability completion. It touches eval definitions, local retail tools, guard checks, runtime planning, workbench case catalog, and verification. It deliberately excludes full tau task ingestion, LLM-backed eval as a gate, dashboard redesign, persistent storage, WebSockets, and a LangGraph conditional rewrite.

## File Structure

Modify backend files:

- `app/eval/cases.py`: add Phase 5 case metadata and `generalized_mvp` cases.
- `app/eval/runner.py`: evaluate richer DB assertions and stricter expected tool ordering where needed.
- `app/eval/metrics.py`: preserve current metrics while accepting richer result diagnostics.
- `app/tools/retail_adapter.py`: implement local fallback tools for item and payment modification; add helper lookup functions used by guard.
- `app/agent/guard.py`: add policy checks for item replacement, payment ownership, gift card balance, user address ownership, and duplicate locks.
- `app/agent/runtime.py`: add name plus zip authentication, new intents, slot extraction, planners, and stable guard-block responses.
- `app/workbench/cases.py`: expose `generalized_mvp` and add a few new demo cases.

Modify tests:

- `tests/test_eval_runner.py`: assert `generalized_mvp` shape, metadata, richer assertions, and final pass count.
- `tests/test_agent_core.py`: add focused tests for tools, guard, auth, and runtime planners.
- `tests/test_workbench_cases.py`: assert generalized catalog and new demo cases.

No frontend layout files should change unless a type mismatch appears during `npm run build`.

---

## Risk Table

| Risk | Impact | Mitigation |
|------|--------|------------|
| `modify_pending_order_payment` moved from `DEFERRED_WRITE_ACTIONS` activates payment paths prematurely | Untested payment mutation could corrupt DB or produce wrong results | Complete guard + tool implementation before runtime integration; run targeted guard tests first |
| `_validate_item_replacements` reused for exchange path | May change existing exchange guard behavior, breaking regression | Run `curated_mvp` eval after guard changes to catch regressions |
| `GUARD_USER_MESSAGES` incomplete coverage | Some guard reasons still leak machine-readable codes to users | Map covers all 20 return values from `_validate_policy`, `_validate_ownership`, `_validate_read_before_write`, and `_lock_conflict` |
| New `EvalCase` fields (`subset`, `capability`, `policy_area`, `expected_db_assertions`, `expected_tool_sequence`) added | Older serialization code may fail on unknown fields | Add fields to `EvalCase` dataclass with defaults; verify workbench `_serialize_case` includes them |
| `find_user_id_by_name_zip` not yet verified working end-to-end | Name+zip auth fails in runtime even after planner is added | Pre-flight Check 1 verifies the tool before any implementation starts |
| Chinese `check:i18n` fails on new case titles | CI/local build breaks | Task 7 Step 3 includes Chinese titles for every new case; verify with `npm run check:i18n` in Step 7 |

## Pre-Flight Checks

Before starting any Phase 5 task, verify that existing dependencies are in good shape:

- [ ] **Check 1: `find_user_id_by_name_zip` tool works**
  Run:
  ```bash
  uv run python -c "
  from app.config import resolve_config
  from app.tools.retail_adapter import RetailAdapter
  r = RetailAdapter(resolve_config()).create_runtime()
  uid = r.tools.find_user_id_by_name_zip(first_name='Sofia', last_name='Rossi', zip='78784')
  print('PASS:', uid)
  "
  ```
  Expected: prints user id for Sofia Rossi.

- [ ] **Check 2: `modify_user_address` tool exists and works**
  Run:
  ```bash
  uv run python -c "
  from app.config import resolve_config
  from app.tools.retail_adapter import RetailAdapter
  r = RetailAdapter(resolve_config()).create_runtime()
  result = r.tools.modify_user_address(user_id='sofia_rossi_8776', address1='12 Oak St', city='Austin', state='TX', country='USA', zip='78701')
  print('PASS:', result.get('default_address', {}).get('address1'))
  "
  ```

- [ ] **Check 3: `_get_payment_method` and `_get_variant` helpers exist**
  Run:
  ```bash
  uv run python -c "
  from app.config import resolve_config
  from app.tools.retail_adapter import RetailAdapter
  r = RetailAdapter(resolve_config()).create_runtime()
  pm = r.tools._get_payment_method('sofia_rossi_8776', 'credit_card_5051208')
  print('PASS pm:', pm['source'])
  v = r.tools._get_variant('66fd7e9e', '1586641416')
  print('PASS var:', v['available'])
  "
  ```

- [ ] **Check 4: All existing tests still pass**
  Run:
  ```bash
  uv run python -m unittest discover -s tests -v 2>&1 | tail -5
  ```
  Expected: `OK`.

- [ ] **Check 5: `curated_mvp` eval still passes**
  Run:
  ```bash
  uv run phase2-eval --subset curated_mvp --trials 1 --no-progress --json 2>&1 | python -c "import sys,json; d=json.load(sys.stdin); assert d['pass_rate']==1.0, f'pass_rate={d[\"pass_rate\"]}'; print('PASS:', d['passed_count'], '/', d['count'])"
  ```

If any pre-flight check fails, fix the underlying issue before starting Phase 5 implementation.

---

## Execution Guidance

The 8 tasks below are organized for clarity, but **Task 1 and Task 6** both modify eval files (`app/eval/cases.py`, `app/eval/runner.py`, `tests/test_eval_runner.py`), and **Task 4 and Task 5** both modify `app/agent/runtime.py` and `tests/test_agent_core.py`. Implementers should work these pairs as merged units to reduce file churn and test loops:

- **Merged unit A** (Task 1 + Task 6): eval contract plumbing → eval case definitions
- **Merged unit B** (Task 4 + Task 5): runtime authentication/planning → guard response mapping

The remaining tasks (2, 3, 7, 8) each have distinct file targets and can be executed individually.

### Task 1: Extend Eval Case Contract For Phase 5

**Files:**
- Modify: `app/eval/cases.py`
- Modify: `app/eval/runner.py`
- Test: `tests/test_eval_runner.py`

- [ ] **Step 1: Write failing tests for case metadata and generalized subset plumbing**

Add these tests to `tests/test_eval_runner.py` inside `CuratedEvalTests`:

Also change the imports near the top of `tests/test_eval_runner.py`:

```python
from app.eval.cases import EvalCase, get_cases
```

```python
    def test_generalized_subset_starts_as_curated_regression_copy(self):
        curated_cases = get_cases("curated_mvp")
        generalized_cases = get_cases("generalized_mvp")

        self.assertEqual(len(generalized_cases), len(curated_cases))
        self.assertEqual({case.subset for case in curated_cases}, {"curated_mvp"})
        self.assertEqual({case.subset for case in generalized_cases}, {"generalized_mvp"})
        self.assertEqual(
            [case.case_id for case in generalized_cases],
            [case.case_id for case in curated_cases],
        )
        self.assertIsNot(generalized_cases[0].messages, curated_cases[0].messages)
        self.assertEqual(generalized_cases[0].expected_db_assertions, {})
        self.assertEqual(generalized_cases[0].expected_tool_sequence, [])

    def test_expected_tool_sequence_detects_wrong_order(self):
        case = EvalCase(
            case_id="ordered_tools",
            category="test",
            messages=[],
            expected_user_id="user",
            expected_intent="lookup",
            expected_tool_names=["first_tool", "second_tool"],
            expected_tool_sequence=["first_tool", "second_tool"],
        )

        label = classify_failure(
            case=case,
            authenticated_user_id="user",
            final_intent="lookup",
            write_locks=[],
            actual_order_status=None,
            assistant_messages=[],
            tool_names=["second_tool", "first_tool"],
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="not_required",
        )

        self.assertEqual(label, "wrong_tool_sequence")
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
uv run python -m unittest tests.test_eval_runner.CuratedEvalTests.test_generalized_subset_starts_as_curated_regression_copy tests.test_eval_runner.CuratedEvalTests.test_expected_tool_sequence_detects_wrong_order -v
```

Expected: FAIL because `generalized_mvp` is unsupported, `EvalCase` lacks Phase 5 metadata fields, or `classify_failure` ignores expected tool sequence.

- [ ] **Step 3: Extend `EvalCase` with Phase 5 metadata**

Modify `app/eval/cases.py`:

```python
@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: str
    messages: List[Dict[str, str]]
    expected_user_id: str
    expected_intent: str
    order_id: Optional[str] = None
    expected_write_lock: Optional[str] = None
    expected_order_status: Optional[str] = None
    expected_confirmation_status: Optional[str] = None
    expected_guard_block_reason: Optional[str] = None
    expected_no_write: bool = False
    expected_tool_names: List[str] = field(default_factory=list)
    expected_assistant_contains: Optional[str] = None
    max_turns: int = 8
    subset: str = "curated_mvp"
    capability: Optional[str] = None
    policy_area: Optional[str] = None
    expected_db_assertions: Dict[str, object] = field(default_factory=dict)
    expected_tool_sequence: List[str] = field(default_factory=list)
```

- [ ] **Step 4: Add subset helpers without changing existing curated cases**

Add this helper near the case definitions in `app/eval/cases.py`:

```python
def _case_for_subset(case: EvalCase, subset: str) -> EvalCase:
    return EvalCase(
        case_id=case.case_id,
        category=case.category,
        messages=[dict(message) for message in case.messages],
        expected_user_id=case.expected_user_id,
        expected_intent=case.expected_intent,
        order_id=case.order_id,
        expected_write_lock=case.expected_write_lock,
        expected_order_status=case.expected_order_status,
        expected_confirmation_status=case.expected_confirmation_status,
        expected_guard_block_reason=case.expected_guard_block_reason,
        expected_no_write=case.expected_no_write,
        expected_tool_names=list(case.expected_tool_names),
        expected_assistant_contains=case.expected_assistant_contains,
        max_turns=case.max_turns,
        subset=subset,
        capability=case.capability,
        policy_area=case.policy_area,
        expected_db_assertions=dict(case.expected_db_assertions),
        expected_tool_sequence=list(case.expected_tool_sequence),
    )
```

- [ ] **Step 5: Add a temporary generalized list that preserves current regression cases**

Add this near the bottom of `app/eval/cases.py`:

```python
GENERALIZED_MVP_CASES: List[EvalCase] = [
    _case_for_subset(case, "generalized_mvp") for case in CURATED_MVP_CASES
]
```

Change `get_cases`:

```python
def get_cases(subset: str) -> List[EvalCase]:
    if subset == "curated_mvp":
        return list(CURATED_MVP_CASES)
    if subset == "generalized_mvp":
        return list(GENERALIZED_MVP_CASES)
    raise ValueError("unsupported subset: " + subset)
```

This keeps generalized eval available without requiring all Phase 5 cases in the first task.

- [ ] **Step 6: Teach failure classification about expected tool sequence**

In `app/eval/runner.py`, add this check after missing tool detection in `classify_failure`:

```python
    if case.expected_tool_sequence:
        sequence_cursor = 0
        for tool_name in tool_names:
            if tool_name == case.expected_tool_sequence[sequence_cursor]:
                sequence_cursor += 1
                if sequence_cursor == len(case.expected_tool_sequence):
                    break
        if sequence_cursor < len(case.expected_tool_sequence):
            return "wrong_tool_sequence"
```

- [ ] **Step 7: Run current eval tests**

Run:

```bash
uv run python -m unittest tests.test_eval_runner -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/eval/cases.py app/eval/runner.py tests/test_eval_runner.py
git commit -m "feat：扩展Phase5评测用例契约"
```

---

### Task 2: Complete Local Fallback Retail Write Tools

**Files:**
- Modify: `app/tools/retail_adapter.py`
- Test: `tests/test_agent_core.py`

- [ ] **Step 1: Write failing tests for local item and payment tools**

Add these tests to `RetailAdapterTests` in `tests/test_agent_core.py`:

```python
    def test_local_tools_modify_pending_order_items(self):
        config = resolve_config()
        tools = RetailAdapter(config)._create_local_runtime("policy").tools

        updated = tools.modify_pending_order_items(
            order_id=PENDING_ORDER,
            item_ids=["1586641416"],
            new_item_ids=["5925362855"],
        )

        self.assertEqual(updated["status"], "pending (item modified)")
        self.assertIn("5925362855", [item["item_id"] for item in updated["items"]])
        self.assertNotIn("1586641416", [item["item_id"] for item in updated["items"]])

    def test_local_tools_modify_pending_order_payment(self):
        config = resolve_config()
        tools = RetailAdapter(config)._create_local_runtime("policy").tools

        updated = tools.modify_pending_order_payment(
            order_id="#W8855135",
            payment_method_id="credit_card_8105988",
        )

        self.assertEqual(updated["status"], "pending")
        self.assertEqual(
            updated["payment_history"][-1]["payment_method_id"],
            "credit_card_8105988",
        )
        self.assertEqual(updated["payment_history"][-1]["transaction_type"], "payment")
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
uv run python -m unittest tests.test_agent_core.RetailAdapterTests.test_local_tools_modify_pending_order_items tests.test_agent_core.RetailAdapterTests.test_local_tools_modify_pending_order_payment -v
```

Expected: FAIL because the local fallback tools do not implement these methods.

- [ ] **Step 3: Add helper functions for order payment and variants**

In `app/tools/retail_adapter.py`, add these helpers near the existing public helper functions:

```python
def find_variant_in_db(db: Any, item_id: str) -> Optional[Dict[str, Any]]:
    data = to_plain_data(db)
    for product_id, product in data.get("products", {}).items():
        variant = product.get("variants", {}).get(item_id)
        if variant:
            payload = copy.deepcopy(variant)
            payload["product_id"] = product_id
            payload["product_name"] = product.get("name")
            return payload
    return None


def get_current_payment_method_id(order: Dict[str, Any]) -> Optional[str]:
    for entry in reversed(order.get("payment_history", [])):
        if entry.get("transaction_type") == "payment":
            return entry.get("payment_method_id")
    return None
```

- [ ] **Step 4: Implement `modify_pending_order_items` in `LocalRetailTools`**

Add this method after `modify_pending_order_address`:

```python
    def modify_pending_order_items(
        self, order_id: str, item_ids: list[str], new_item_ids: list[str]
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        if order["status"] != "pending":
            raise ValueError("Non-pending order cannot be modified")
        if len(item_ids) != len(new_item_ids):
            raise ValueError("The number of replacement items should match.")

        for old_item_id, new_item_id in zip(item_ids, new_item_ids):
            matching_index = next(
                (
                    index
                    for index, item in enumerate(order["items"])
                    if item["item_id"] == old_item_id
                ),
                None,
            )
            if matching_index is None:
                raise ValueError(f"Item {old_item_id} not found in order")

            old_item = order["items"][matching_index]
            new_variant = self._get_variant(old_item["product_id"], new_item_id)
            if not new_variant["available"]:
                raise ValueError(f"New item {new_item_id} not available")

            replacement = copy.deepcopy(old_item)
            replacement["item_id"] = new_item_id
            replacement["price"] = new_variant["price"]
            replacement["options"] = copy.deepcopy(new_variant["options"])
            order["items"][matching_index] = replacement

        order["status"] = "pending (item modified)"
        return copy.deepcopy(order)
```

- [ ] **Step 5: Implement `modify_pending_order_payment` in `LocalRetailTools`**

Add this method after `modify_pending_order_items`:

```python
    def modify_pending_order_payment(
        self, order_id: str, payment_method_id: str
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        if "pending" not in order["status"]:
            raise ValueError("Non-pending order cannot be modified")
        payment_method = self._get_payment_method(order["user_id"], payment_method_id)
        current_payment_method_id = get_current_payment_method_id(order)
        if payment_method_id == current_payment_method_id:
            raise ValueError("New payment method must be different")

        amount = sum(float(item.get("price", 0.0)) for item in order["items"])
        if payment_method.get("source") == "gift_card":
            if float(payment_method.get("balance", 0.0)) < amount:
                raise ValueError("Gift card balance is insufficient")

        order["payment_history"].append(
            {
                "transaction_type": "payment",
                "amount": round(amount, 2),
                "payment_method_id": payment_method_id,
            }
        )
        return copy.deepcopy(order)
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run python -m unittest tests.test_agent_core.RetailAdapterTests.test_local_tools_modify_pending_order_items tests.test_agent_core.RetailAdapterTests.test_local_tools_modify_pending_order_payment -v
```

Expected: PASS.

- [ ] **Step 7: Run registry classification test**

Run:

```bash
uv run python -m unittest tests.test_agent_core.RetailAdapterTests.test_registry_classifies_tools -v
```

Expected: PASS and `ToolRegistry.kind("modify_pending_order_items")` is write if the test is extended to assert it.

- [ ] **Step 8: Commit**

```bash
git add app/tools/retail_adapter.py tests/test_agent_core.py
git commit -m "feat：补齐本地零售写操作工具"
```

---

### Task 3: Strengthen Write Guard Policy Checks

**Files:**
- Modify: `app/agent/guard.py`
- Test: `tests/test_agent_core.py`

- [ ] **Step 1: Write failing guard tests**

Add these tests to `WriteGuardTests` in `tests/test_agent_core.py`:

```python
    def test_allows_valid_pending_item_modification(self):
        state = ConversationState(session_id="test", authenticated_user_id=PENDING_USER)
        state.loaded_context.orders[PENDING_ORDER] = {"order_id": PENDING_ORDER}

        result = self.guard.check(
            state=state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="modify_pending_order_items",
                arguments={
                    "order_id": PENDING_ORDER,
                    "item_ids": ["1586641416"],
                    "new_item_ids": ["5925362855"],
                },
            ),
            confirmed=True,
        )

        self.assertTrue(result.allowed)
        self.assertEqual(result.resource_lock, f"order:{PENDING_ORDER}:modify_items")

    def test_blocks_replacement_item_product_mismatch(self):
        state = ConversationState(session_id="test", authenticated_user_id=PENDING_USER)
        state.loaded_context.orders[PENDING_ORDER] = {"order_id": PENDING_ORDER}

        result = self.guard.check(
            state=state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="modify_pending_order_items",
                arguments={
                    "order_id": PENDING_ORDER,
                    "item_ids": ["1586641416"],
                    "new_item_ids": ["9612497925"],
                },
            ),
            confirmed=True,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "replacement_item_product_mismatch")

    def test_blocks_unowned_payment_method(self):
        state = ConversationState(session_id="test", authenticated_user_id=PENDING_USER)
        state.loaded_context.orders[PENDING_ORDER] = {"order_id": PENDING_ORDER}

        result = self.guard.check(
            state=state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="modify_pending_order_payment",
                arguments={
                    "order_id": PENDING_ORDER,
                    "payment_method_id": "gift_card_8168843",
                },
            ),
            confirmed=True,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "payment_method_not_owned")

    def test_blocks_insufficient_gift_card_balance(self):
        state = ConversationState(
            session_id="test", authenticated_user_id="raj_sanchez_2970"
        )
        state.loaded_context.orders["#W4566809"] = {"order_id": "#W4566809"}

        result = self.guard.check(
            state=state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="modify_pending_order_payment",
                arguments={
                    "order_id": "#W4566809",
                    "payment_method_id": "gift_card_2259499",
                },
            ),
            confirmed=True,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "gift_card_balance_insufficient")
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
uv run python -m unittest tests.test_agent_core.WriteGuardTests.test_allows_valid_pending_item_modification tests.test_agent_core.WriteGuardTests.test_blocks_replacement_item_product_mismatch tests.test_agent_core.WriteGuardTests.test_blocks_unowned_payment_method tests.test_agent_core.WriteGuardTests.test_blocks_insufficient_gift_card_balance -v
```

Expected: FAIL because guard does not yet implement all Phase 5 checks.

- [ ] **Step 3: Import new retail helpers**

Modify imports in `app/agent/guard.py`. The file already imports `get_order_from_db` and `get_user_from_db`. Add only the two new helpers (`find_variant_in_db`, `get_current_payment_method_id`):

```python
from app.tools.retail_adapter import (
    find_variant_in_db,
    get_current_payment_method_id,
    get_order_from_db,
    get_user_from_db,
)
```

- [ ] **Step 4: Activate `modify_pending_order_payment`**

In `app/agent/guard.py`, `modify_pending_order_payment` is currently in `DEFERRED_WRITE_ACTIONS` (blocked as `unsupported_in_mvp`). Move it to `WRITE_ACTIONS` and empty `DEFERRED_WRITE_ACTIONS`. `modify_pending_order_items` is already present — verify it is not missing:

```python
WRITE_ACTIONS = {
    "cancel_pending_order",
    "modify_pending_order_address",
    "modify_pending_order_items",        # already present — verify
    "modify_pending_order_payment",      # moved from DEFERRED
    "modify_user_address",
    "return_delivered_order_items",
    "exchange_delivered_order_items",
}
DEFERRED_WRITE_ACTIONS: set[str] = set()   # was {"modify_pending_order_payment"}
```

- [ ] **Step 5: Add item replacement policy helper**

Add this method to `WriteActionGuard`:

```python
    def _validate_item_replacements(
        self, db: Any, order: Dict[str, Any], args: Dict[str, Any]
    ) -> Optional[str]:
        item_ids = args.get("item_ids", [])
        new_item_ids = args.get("new_item_ids", [])
        if len(item_ids) != len(new_item_ids):
            return "replacement_item_count_mismatch"
        order_items = order.get("items", [])
        for old_item_id, new_item_id in zip(item_ids, new_item_ids):
            old_item = next(
                (item for item in order_items if item.get("item_id") == old_item_id),
                None,
            )
            if old_item is None:
                return "order_item_not_found"
            new_variant = find_variant_in_db(db, new_item_id)
            if new_variant is None:
                return "replacement_item_not_found"
            if new_variant.get("product_id") != old_item.get("product_id"):
                return "replacement_item_product_mismatch"
            if not new_variant.get("available"):
                return "replacement_item_unavailable"
        return None
```

- [ ] **Step 6: Add payment policy helper**

Add this method to `WriteActionGuard`:

```python
    def _validate_payment_change(
        self, db: Any, order: Dict[str, Any], args: Dict[str, Any]
    ) -> Optional[str]:
        user = get_user_from_db(db, order.get("user_id", ""))
        if not user:
            return "user_not_found"
        payment_method_id = args.get("payment_method_id")
        payment_method = user.get("payment_methods", {}).get(payment_method_id)
        if payment_method is None:
            return "payment_method_not_owned"
        current_payment_method_id = get_current_payment_method_id(order)
        if payment_method_id == current_payment_method_id:
            return "same_payment_method"
        if payment_method.get("source") == "gift_card":
            amount = sum(float(item.get("price", 0.0)) for item in order.get("items", []))
            if float(payment_method.get("balance", 0.0)) < amount:
                return "gift_card_balance_insufficient"
        return None
```

- [ ] **Step 7: Reuse item replacement helper for exchange**

In `_validate_policy`, the existing `exchange_delivered_order_items` branch should also call `_validate_item_replacements` after checking delivered status and count. This makes exchange reject cross-product and unavailable replacement items before the tool mutates anything:

```python
        if action.tool_name == "exchange_delivered_order_items":
            if not order or order.get("status") != "delivered":
                return "non_delivered_order_cannot_be_exchanged"
            if len(args.get("item_ids", [])) != len(args.get("new_item_ids", [])):
                return "exchange_item_count_mismatch"
            replacement_reason = self._validate_item_replacements(db, order, args)
            if replacement_reason:
                return replacement_reason
```

- [ ] **Step 8: Call helpers from `_validate_policy`**

In `_validate_policy`, add:

```python
        if action.tool_name == "modify_pending_order_items":
            if not order or order.get("status") != "pending":
                return "non_pending_order_cannot_be_modified"
            replacement_reason = self._validate_item_replacements(db, order, args)
            if replacement_reason:
                return replacement_reason
        if action.tool_name == "modify_pending_order_payment":
            if not order or "pending" not in order.get("status", ""):
                return "non_pending_order_cannot_be_modified"
            payment_reason = self._validate_payment_change(db, order, args)
            if payment_reason:
                return payment_reason
```

- [ ] **Step 9: Add payment lock to existing `_resource_lock` map**

`_resource_lock` already maps `cancel_pending_order`, `modify_pending_order_address`, and `modify_pending_order_items`. Add only the missing entry for payment:

```python
        category = {
            "cancel_pending_order": "cancel",
            "modify_pending_order_address": "modify_address",
            "modify_pending_order_items": "modify_items",       # already present
            "modify_pending_order_payment": "modify_payment",   # new
        }.get(action.tool_name, action.tool_name)
```

- [ ] **Step 10: Run focused and full agent core tests**

Run:

```bash
uv run python -m unittest tests.test_agent_core.WriteGuardTests -v
uv run python -m unittest tests.test_agent_core -v
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add app/agent/guard.py tests/test_agent_core.py
git commit -m "feat：强化交易写操作安全校验"
```

---

### Task 4: Add Runtime Authentication, Intents, Slots, And Planners

**Files:**
- Modify: `app/agent/runtime.py`
- Test: `tests/test_agent_core.py`

- [ ] **Step 1: Write failing runtime tests**

Add these tests to the runtime test class in `tests/test_agent_core.py` or create `AgentRuntimePhase5Tests` in the same file:

```python
class AgentRuntimePhase5Tests(unittest.TestCase):
    def _runtime(self):
        return AgentRuntime(resolve_config(), provider=DisabledLLMProvider())

    def test_authenticates_by_name_and_zip(self):
        runtime = self._runtime()
        state = ConversationState(session_id="test")

        response = runtime.handle_user_message(
            state,
            "My name is Sofia Rossi and my zip is 78784. What is order #W5918442?",
        )

        self.assertEqual(state.authenticated_user_id, PENDING_USER)
        self.assertEqual(state.auth_method, "name_zip")
        self.assertIn("pending", response)

    def test_plans_modify_pending_order_items(self):
        runtime = self._runtime()
        state = ConversationState(session_id="test")

        response = runtime.handle_user_message(
            state,
            (
                f"My email is {PENDING_EMAIL}. Change item 1586641416 in order "
                f"{PENDING_ORDER} to new item 5925362855."
            ),
        )

        self.assertIn("confirm", response.lower())
        self.assertIsNotNone(state.pending_action)
        self.assertEqual(state.pending_action.action_name, "modify_pending_order_items")

    def test_plans_modify_pending_order_payment(self):
        runtime = self._runtime()
        state = ConversationState(session_id="test")

        response = runtime.handle_user_message(
            state,
            (
                "My email is sofia.li7352@example.com. Change payment for order "
                "#W8855135 to credit_card_8105988."
            ),
        )

        self.assertIn("confirm", response.lower())
        self.assertEqual(state.current_intent, "modify_order_payment")
        self.assertEqual(state.pending_action.action_name, "modify_pending_order_payment")

    def test_plans_modify_user_default_address(self):
        runtime = self._runtime()
        state = ConversationState(session_id="test")

        response = runtime.handle_user_message(
            state,
            (
                f"My email is {PENDING_EMAIL}. Change my default address to "
                "12 Oak St, Unit 4, Austin, TX, USA, 78701."
            ),
        )

        self.assertIn("confirm", response.lower())
        self.assertEqual(state.current_intent, "modify_user_address")
        self.assertEqual(state.pending_action.action_name, "modify_user_address")
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
uv run python -m unittest tests.test_agent_core.AgentRuntimePhase5Tests -v
```

Expected: FAIL because runtime does not yet support these auth/intents/planners.

- [ ] **Step 3: Add name and zip regexes and supported intents**

Modify constants in `app/agent/runtime.py`:

```python
ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
NAME_ZIP_RE = re.compile(
    r"(?:my name is|i am|i'm)\s+([A-Za-z]+)\s+([A-Za-z]+).*?\bzip(?: code)? is\s+(\d{5}(?:-\d{4})?)",
    re.IGNORECASE,
)
SUPPORTED_INTENTS = {
    "lookup",
    "cancel_order",
    "modify_order_address",
    "modify_order_items",
    "modify_order_payment",
    "modify_user_address",
    "return_items",
    "exchange_items",
    "transfer",
    "unknown",
}
SUPPORTED_PENDING_ACTIONS = {
    "cancel_pending_order",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
    "exchange_delivered_order_items",
}
```

- [ ] **Step 4: Update identity resolver**

In `_identity_resolver`, after failing to find an email, add:

```python
        name_zip_match = NAME_ZIP_RE.search(content)
        if name_zip_match:
            first_name, last_name, zip_code = name_zip_match.groups()
            record = self.gateway.execute(
                state=state,
                tool_name="find_user_id_by_name_zip",
                arguments={
                    "first_name": first_name,
                    "last_name": last_name,
                    "zip": zip_code,
                },
            )
            if record.status != "success":
                self._assistant(state, "I could not verify that name and zip code.")
                return
            user_id = str(record.observation)
            state.authenticated_user_id = user_id
            state.auth_method = "name_zip"
            state.active_user_identity = {
                "first_name": first_name,
                "last_name": last_name,
                "zip": zip_code,
                "user_id": user_id,
            }
            user_record = self.gateway.execute(
                state=state,
                tool_name="get_user_details",
                arguments={"user_id": user_id},
            )
            if user_record.status == "success":
                state.loaded_context.users[user_id] = user_record.observation
            state.add_step("identity_resolver", status="authenticated", user_id=user_id)
            return
```

Then keep the existing assistant request for email or name plus zip.

- [ ] **Step 5: Extend deterministic intent inference**

In `_infer_intent`, add branches:

```python
        if "default address" in lowered or "my address" in lowered:
            return "modify_user_address"
        if "payment" in lowered and any(token in lowered for token in {"change", "modify", "update", "use"}):
            return "modify_order_payment"
        if "change item" in lowered or "modify item" in lowered or "replace item" in lowered:
            return "modify_order_items"
```

- [ ] **Step 6: Extend slot extraction**

In `_intent_and_slot_extractor`, after existing item extraction, add deterministic new-item parsing that handles item changes and exchanges:

```python
        replacement_match = re.search(
            r"(?:to new item|to item|with item|replace(?: it)? with)\s+(\d{8,})",
            lowered,
        )
        if replacement_match:
            state.slots["new_item_ids"] = [replacement_match.group(1)]
            if "item_ids" in state.slots:
                state.slots["item_ids"] = [
                    item_id
                    for item_id in state.slots["item_ids"]
                    if item_id not in state.slots["new_item_ids"]
                ]
```

Ensure default address messages reuse `_parse_address(content)` and set `state.slots["address"]`.

- [ ] **Step 7: Route new intents in `_action_planner`**

Add:

```python
        if intent == "modify_order_items":
            self._plan_modify_items(state)
            return
        if intent == "modify_order_payment":
            self._plan_modify_payment(state)
            return
        if intent == "modify_user_address":
            self._plan_user_address_change(state)
            return
```

- [ ] **Step 8: Add planner methods**

Add these methods near existing `_plan_*` methods:

```python
    def _plan_modify_items(self, state: ConversationState) -> None:
        required = ["order_id", "item_ids", "new_item_ids"]
        missing = [key for key in required if not state.slots.get(key)]
        if missing:
            self._assistant(
                state,
                "Please provide order id, current item id, and replacement item id.",
            )
            return
        self._set_pending(
            state,
            "modify_pending_order_items",
            {
                "order_id": state.slots["order_id"],
                "item_ids": state.slots["item_ids"],
                "new_item_ids": state.slots["new_item_ids"],
            },
            f"Modify items for order {state.slots['order_id']}. Please confirm yes or no.",
        )

    def _plan_modify_payment(self, state: ConversationState) -> None:
        required = ["order_id", "payment_method_id"]
        missing = [key for key in required if not state.slots.get(key)]
        if missing:
            self._assistant(
                state,
                "Please provide order id and the new payment method id.",
            )
            return
        self._set_pending(
            state,
            "modify_pending_order_payment",
            {
                "order_id": state.slots["order_id"],
                "payment_method_id": state.slots["payment_method_id"],
            },
            f"Modify payment for order {state.slots['order_id']}. Please confirm yes or no.",
        )

    def _plan_user_address_change(self, state: ConversationState) -> None:
        address = state.slots.get("address")
        if not address:
            self._assistant(
                state,
                "Please provide the new default address as: address to line1, line2, city, state, country, zip.",
            )
            return
        self._set_pending(
            state,
            "modify_user_address",
            {"user_id": state.authenticated_user_id, **address},
            "Modify your default address. Please confirm yes or no.",
        )
```

- [ ] **Step 9: Run focused and full agent core tests**

Run:

```bash
uv run python -m unittest tests.test_agent_core.AgentRuntimePhase5Tests -v
uv run python -m unittest tests.test_agent_core -v
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add app/agent/runtime.py tests/test_agent_core.py
git commit -m "feat：补齐客服运行时交易意图"
```

---

### Task 5: Add User-Facing Guard Block Responses

**Files:**
- Modify: `app/agent/runtime.py`
- Test: `tests/test_agent_core.py`

- [ ] **Step 1: Write failing test for readable guard response**

Add this test to `AgentRuntimePhase5Tests`:

```python
    def test_guard_block_response_is_user_readable(self):
        runtime = self._runtime()
        state = ConversationState(session_id="test")

        runtime.handle_user_message(
            state,
            (
                f"My email is {PENDING_EMAIL}. Change item 1586641416 in order "
                f"{PENDING_ORDER} to new item 9612497925."
            ),
        )
        response = runtime.handle_user_message(state, "yes")

        self.assertIn("same product", response.lower())
        self.assertNotIn("replacement_item_product_mismatch", response)
```

- [ ] **Step 2: Run focused test and verify failure**

Run:

```bash
uv run python -m unittest tests.test_agent_core.AgentRuntimePhase5Tests.test_guard_block_response_is_user_readable -v
```

Expected: FAIL because the raw guard reason is returned.

- [ ] **Step 3: Add guard reason mapping with dedicated method**

In `app/agent/runtime.py`, add a module-level constant and a helper method. The constant maps every guard block reason to a user-readable message. The method provides the lookup with a safe fallback that never leaks machine-readable codes:

```python
GUARD_USER_MESSAGES = {
    "replacement_item_product_mismatch": "I can only replace an item with another available option from the same product.",
    "replacement_item_unavailable": "That replacement item is not available.",
    "replacement_item_count_mismatch": "The number of replacement items must match the number of items being replaced.",
    "replacement_item_not_found": "That replacement item could not be found in the catalog.",
    "order_item_not_found": "The item you want to replace is not in that order.",
    "payment_method_not_owned": "I can only use payment methods saved on your account.",
    "gift_card_balance_insufficient": "That gift card does not have enough balance for this order.",
    "same_payment_method": "The new payment method must be different from the current one.",
    "non_pending_order_cannot_be_modified": "I can only modify orders that are still pending.",
    "non_pending_order_cannot_be_cancelled": "I can only cancel orders that are still pending.",
    "non_delivered_order_cannot_be_returned": "I can only create returns for delivered orders.",
    "non_delivered_order_cannot_be_exchanged": "I can only create exchanges for delivered orders.",
    "exchange_item_count_mismatch": "The number of new items must match the number of items being exchanged.",
    "ownership_violation": "I cannot access or modify orders for another account.",
    "read_before_write_required": "I need to review the order details before making changes. Please ask me to look up the order first.",
    "authentication_required": "Please verify your identity before making changes.",
    "user_not_found": "I could not verify your account. Please provide different credentials.",
    "invalid_cancel_reason": "Please provide a valid cancellation reason: no longer needed or ordered by mistake.",
    "duplicate_write_lock": "A similar change is already in progress for this order.",
    "order_already_cancelled_or_locked": "This order has already been cancelled.",
    "order_items_already_modified": "The items in this order have already been modified.",
    "item_already_returned_or_exchanged": "One or more of these items has already been returned or exchanged.",
}


def _map_guard_error_to_user_message(error: str) -> str:
    """Return a user-readable message for a guard block reason."""
    return GUARD_USER_MESSAGES.get(
        str(error),
        "I could not complete that update. Please try again or contact support.",
    )
```

- [ ] **Step 4: Use mapping in `_conversation_gate`**

In `_conversation_gate`, replace the raw error passthrough with the `_map_guard_error_to_user_message` helper. The current code uses `record.error` directly; change it to:

```python
                    self._assistant(
                        state,
                        _map_guard_error_to_user_message(str(record.error)),
                    )
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run python -m unittest tests.test_agent_core.AgentRuntimePhase5Tests.test_guard_block_response_is_user_readable -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/agent/runtime.py tests/test_agent_core.py
git commit -m "feat：优化写操作拦截提示"
```

---

### Task 6: Build The Generalized MVP Eval Subset

**Files:**
- Modify: `app/eval/cases.py`
- Modify: `app/eval/runner.py`
- Test: `tests/test_eval_runner.py`

- [ ] **Step 1: Add failing eval runner test for generalized subset**

Add this test to `CuratedEvalTests`:

```python
    def test_generalized_eval_runner_passes_phase5_subset(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            summary = CuratedEvalRunner(
                config=config,
                artifact_dir=Path(tmp),
            ).run(subset="generalized_mvp", trials=1)

        self.assertGreaterEqual(summary.case_count, 30)
        self.assertEqual(summary.passed_count, summary.case_count)
        self.assertEqual(summary.metrics["pass_1"], 1.0)
        self.assertEqual(summary.metrics["pass_k"], 1.0)
        self.assertEqual(summary.metrics["mutation_error_rate"], 0.0)
        self.assertEqual(summary.metrics["tool_error_rate"], 0.0)
```

- [ ] **Step 2: Run the generalized eval test and verify failure**

Run:

```bash
uv run python -m unittest tests.test_eval_runner.CuratedEvalTests.test_generalized_eval_runner_passes_phase5_subset -v
```

Expected: FAIL because generalized cases are not complete or do not pass.

- [ ] **Step 3: Add Phase 5 success cases**

In `app/eval/cases.py`, add `PHASE5_NEW_CASES` with these success cases:

```python
PHASE5_NEW_CASES: List[EvalCase] = [
    EvalCase(
        case_id="auth_name_zip_lookup_order",
        category="auth",
        messages=[
            {
                "role": "user",
                "content": (
                    "My name is Sofia Rossi and my zip is 78784. "
                    "What is the status of order #W5918442?"
                ),
            }
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="lookup",
        order_id="#W5918442",
        expected_tool_names=["find_user_id_by_name_zip", "get_order_details"],
        expected_assistant_contains="pending",
        subset="generalized_mvp",
        capability="auth_name_zip",
        policy_area="authentication",
    ),
    EvalCase(
        case_id="modify_pending_order_items_success",
        category="modify_items",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Change item "
                    "1586641416 in order #W5918442 to new item 5925362855."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="modify_order_items",
        order_id="#W5918442",
        expected_write_lock="order:#W5918442:modify_items",
        expected_order_status="pending (item modified)",
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_pending_order_items"],
        subset="generalized_mvp",
        capability="modify_items",
        policy_area="inventory",
    ),
    EvalCase(
        case_id="modify_pending_order_payment_success",
        category="modify_payment",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.li7352@example.com. Change payment for "
                    "order #W8855135 to credit_card_8105988."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_li_9219",
        expected_intent="modify_order_payment",
        order_id="#W8855135",
        expected_write_lock="order:#W8855135:modify_payment",
        expected_order_status="pending",
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_pending_order_payment"],
        subset="generalized_mvp",
        capability="modify_payment",
        policy_area="payment_method",
    ),
    EvalCase(
        case_id="modify_user_default_address_success",
        category="modify_user_address",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Change my default "
                    "address to 12 Oak St, Unit 4, Austin, TX, USA, 78701."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="modify_user_address",
        expected_write_lock="user:sofia_rossi_8776:modify_address",
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_user_address"],
        subset="generalized_mvp",
        capability="modify_user_address",
        policy_area="ownership",
    ),
]
```

- [ ] **Step 4: Add Phase 5 guard and no-write cases**

Add these exact guard and no-write cases to `PHASE5_NEW_CASES`:

```python
    EvalCase(
        case_id="block_item_product_mismatch",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Change item "
                    "1586641416 in order #W5918442 to new item 9612497925."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="modify_order_items",
        order_id="#W5918442",
        expected_order_status="pending",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="replacement_item_product_mismatch",
        expected_no_write=True,
        expected_tool_names=["modify_pending_order_items"],
        subset="generalized_mvp",
        capability="modify_items",
        policy_area="inventory",
    ),
    EvalCase(
        case_id="block_item_unavailable",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Change item "
                    "6117189161 in order #W5918442 to new item 4859937227."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="modify_order_items",
        order_id="#W5918442",
        expected_order_status="pending",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="replacement_item_unavailable",
        expected_no_write=True,
        expected_tool_names=["modify_pending_order_items"],
        subset="generalized_mvp",
        capability="modify_items",
        policy_area="inventory",
    ),
    EvalCase(
        case_id="block_payment_not_owned",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Change payment for "
                    "order #W5918442 to gift_card_8168843."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="modify_order_payment",
        order_id="#W5918442",
        expected_order_status="pending",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="payment_method_not_owned",
        expected_no_write=True,
        expected_tool_names=["modify_pending_order_payment"],
        subset="generalized_mvp",
        capability="modify_payment",
        policy_area="payment_method",
    ),
    EvalCase(
        case_id="block_payment_insufficient_gift_card",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is raj.sanchez2046@example.com. Change payment for "
                    "order #W4566809 to gift_card_2259499."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="raj_sanchez_2970",
        expected_intent="modify_order_payment",
        order_id="#W4566809",
        expected_order_status="pending",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="gift_card_balance_insufficient",
        expected_no_write=True,
        expected_tool_names=["modify_pending_order_payment"],
        subset="generalized_mvp",
        capability="modify_payment",
        policy_area="payment_method",
    ),
```

Add these remaining Phase 5 cases to the same `PHASE5_NEW_CASES` list:

- `multi_item_return_success`
  - category: `return`
  - messages: Ava requests return of items `6777246137` and `4900661478` from `#W4817420` to `gift_card_8168843`, then confirms.
  - expected user: `ava_moore_2033`
  - expected intent: `return_items`
  - expected order status: `return requested`
  - expected write lock: `item:4900661478,6777246137:return`
  - capability: `multi_item_return`
  - policy area: `return_items`

- `multi_item_exchange_success`
  - category: `exchange`
  - messages: Ava requests exchange of `6777246137` to `4579334072` and `6700049080` to `5925362855` from `#W4817420` using `gift_card_8168843`, then confirms.
  - expected user: `ava_moore_2033`
  - expected intent: `exchange_items`
  - expected order status: `exchange requested`
  - expected write lock: `item:6700049080,6777246137:exchange`
  - capability: `multi_item_exchange`
  - policy area: `exchange_items`

- `deny_modify_payment_confirmation`
  - category: `confirmation`
  - messages: Sofia Li requests payment change on `#W8855135` to `credit_card_8105988`, then says `no`.
  - expected user: `sofia_li_9219`
  - expected intent: `modify_order_payment`
  - expected order status: `pending`
  - expected confirmation status: `denied`
  - expected no write: `True`
  - capability: `modify_payment`
  - policy area: `confirmation`

- `changed_modify_items_confirmation`
  - category: `confirmation`
  - messages: Sofia Rossi requests item change on `#W5918442`, then says `No, use item 7523669277 instead.`
  - expected user: `sofia_rossi_8776`
  - expected intent: `modify_order_items`
  - expected order status: `pending`
  - expected confirmation status: `changed`
  - expected no write: `True`
  - capability: `modify_items`
  - policy area: `confirmation`

- `block_modify_items_non_pending_order`
  - category: `guard`
  - messages: James Li requests changing item `6469567736` in processed order `#W2611340` to item `6777246137`, then confirms.
  - expected user: `james_li_5688`
  - expected intent: `modify_order_items`
  - expected order status: `processed`
  - expected guard block reason: `non_pending_order_cannot_be_modified`
  - expected no write: `True`
  - capability: `modify_items`
  - policy area: `order_status`

- `block_same_payment_method`
  - category: `guard`
  - messages: Sofia Rossi requests changing payment for `#W5918442` to current payment `credit_card_5051208`, then confirms.
  - expected user: `sofia_rossi_8776`
  - expected intent: `modify_order_payment`
  - expected order status: `pending`
  - expected guard block reason: `same_payment_method`
  - expected no write: `True`
  - capability: `modify_payment`
  - policy area: `payment_method`

- `transfer_unsupported_discount_request`
  - category: `transfer`
  - messages: Sofia Rossi authenticates and asks for a goodwill discount on an order.
  - expected user: `sofia_rossi_8776`
  - expected intent: `transfer`
  - expected tool names: `["transfer_to_human_agents"]`
  - expected assistant contains: `YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.`
  - capability: `unsupported_request`
  - policy area: `transfer`

- `block_exchange_product_mismatch`
  - category: `guard`
  - messages: Ava requests exchanging item `6777246137` from `#W4817420` to cross-product item `9612497925` using `gift_card_8168843`, then confirms.
  - expected user: `ava_moore_2033`
  - expected intent: `exchange_items`
  - expected order status: `delivered`
  - expected guard block reason: `replacement_item_product_mismatch`
  - expected no write: `True`
  - capability: `multi_item_exchange`
  - policy area: `inventory`

- `deny_modify_user_default_address_confirmation`
  - category: `confirmation`
  - messages: Sofia Rossi requests default address change, then says `no`.
  - expected user: `sofia_rossi_8776`
  - expected intent: `modify_user_address`
  - expected confirmation status: `denied`
  - expected no write: `True`
  - capability: `modify_user_address`
  - policy area: `confirmation`

- `block_modify_payment_processed_order`
  - category: `guard`
  - messages: James Li requests changing payment for processed order `#W2611340` to `gift_card_1725971`, then confirms.
  - expected user: `james_li_5688`
  - expected intent: `modify_order_payment`
  - expected order status: `processed`
  - expected guard block reason: `non_pending_order_cannot_be_modified`
  - expected no write: `True`
  - capability: `modify_payment`
  - policy area: `order_status`

- `block_exchange_unavailable_replacement`
  - category: `guard`
  - messages: Ava requests exchanging item `6700049080` from `#W4817420` to unavailable item `4859937227` using `gift_card_8168843`, then confirms.
  - expected user: `ava_moore_2033`
  - expected intent: `exchange_items`
  - expected order status: `delivered`
  - expected guard block reason: `replacement_item_unavailable`
  - expected no write: `True`
  - capability: `multi_item_exchange`
  - policy area: `inventory`

Together with the 11 curated regression cases, these Phase 5 additions bring
`generalized_mvp` to 30 cases.

- [ ] **Step 5: Build generalized subset from curated plus new cases**

Set:

```python
GENERALIZED_MVP_CASES: List[EvalCase] = [
    *[_case_for_subset(case, "generalized_mvp") for case in CURATED_MVP_CASES],
    *PHASE5_NEW_CASES,
]
```

- [ ] **Step 6: Run generalized eval**

Run:

```bash
uv run phase2-eval --subset generalized_mvp --trials 1 --no-progress --json
```

Expected: summary JSON with `pass_rate` equal `1.0` and `case_count` at least `30`.

- [ ] **Step 7: Run eval tests**

Run:

```bash
uv run python -m unittest tests.test_eval_runner -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/eval/cases.py app/eval/runner.py tests/test_eval_runner.py
git commit -m "feat：新增泛化评测用例集"
```

---

### Task 7: Update Workbench Case Catalog

**Files:**
- Modify: `app/workbench/cases.py`
- Test: `tests/test_workbench_cases.py`

- [ ] **Step 1: Write failing workbench catalog tests**

Add these tests to `tests/test_workbench_cases.py`:

```python
    def test_generalized_catalog_can_be_serialized(self):
        catalog = build_case_catalog("generalized_mvp")

        self.assertEqual(catalog["subset"], "generalized_mvp")
        self.assertGreaterEqual(len(catalog["all_cases"]), 30)
        case_ids = {case["case_id"] for case in catalog["all_cases"]}
        self.assertIn("modify_pending_order_items_success", case_ids)
        self.assertIn("modify_pending_order_payment_success", case_ids)
        self.assertIn("auth_name_zip_lookup_order", case_ids)

    def test_demo_shortlist_includes_phase5_cases_when_available(self):
        catalog = build_case_catalog("generalized_mvp")
        demo_ids = [case["case_id"] for case in catalog["demo_cases"]]

        self.assertIn("auth_name_zip_lookup_order", demo_ids)
        self.assertIn("modify_pending_order_items_success", demo_ids)
        self.assertIn("modify_pending_order_payment_success", demo_ids)
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
uv run python -m unittest tests.test_workbench_cases -v
```

Expected: FAIL because the demo shortlist and titles do not know Phase 5 cases.

- [ ] **Step 3: Add Phase 5 demo ids and titles**

In `app/workbench/cases.py`, add:

```python
PHASE5_DEMO_CASE_IDS = [
    "auth_name_zip_lookup_order",
    "modify_pending_order_items_success",
    "modify_pending_order_payment_success",
    "block_item_product_mismatch",
    "block_payment_insufficient_gift_card",
]
```

Extend `CASE_TITLES` with Chinese labels for all new Phase 5 cases:

```python
    # Phase 5 new success cases
    "auth_name_zip_lookup_order": "姓名加邮编认证查询订单",
    "modify_pending_order_items_success": "修改待处理订单商品",
    "modify_pending_order_payment_success": "修改待处理订单支付方式",
    "modify_user_default_address_success": "修改用户默认地址",
    # Phase 5 guard block cases
    "block_item_product_mismatch": "阻止跨商品替换",
    "block_item_unavailable": "阻止替换缺货商品",
    "block_payment_not_owned": "阻止使用他人支付方式",
    "block_payment_insufficient_gift_card": "阻止余额不足礼品卡支付",
    "block_same_payment_method": "阻止重复支付方式",
    "block_modify_items_non_pending_order": "阻止修改非待处理订单商品",
    "block_modify_payment_processed_order": "阻止修改已处理订单支付",
    "block_exchange_product_mismatch": "阻止跨商品换货",
    "block_exchange_unavailable_replacement": "阻止换货缺货商品",
    # Phase 5 confirmation / no-write cases
    "block_modify_items_changed_confirmation": "变更确认放弃修改商品",
    "deny_modify_user_default_address_confirmation": "拒绝修改默认地址",
    # Phase 5 transfer cases
    "transfer_unsupported_discount_request": "转接不支持折扣请求",
```

- [ ] **Step 4: Select demo ids by subset**

Modify `build_case_catalog`:

```python
def build_case_catalog(subset: str = "curated_mvp") -> Dict[str, Any]:
    cases = get_cases(subset)
    serialized = [_serialize_case(case) for case in cases]
    by_id = {case["case_id"]: case for case in serialized}
    demo_ids = PHASE5_DEMO_CASE_IDS if subset == "generalized_mvp" else DEMO_CASE_IDS
    demo_cases = [by_id[case_id] for case_id in demo_ids if case_id in by_id]
    return {
        "subset": subset,
        "demo_case_ids": list(demo_ids),
        "demo_cases": demo_cases,
        "all_cases": serialized,
    }
```

- [ ] **Step 5: Include Phase 5 metadata in serialized case**

Extend `_serialize_case`:

```python
        "subset": case.subset,
        "capability": case.capability,
        "policy_area": case.policy_area,
        "expected_db_assertions": dict(case.expected_db_assertions),
        "expected_tool_sequence": list(case.expected_tool_sequence),
```

- [ ] **Step 6: Run workbench tests**

Run:

```bash
uv run python -m unittest tests.test_workbench_cases -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/workbench/cases.py tests/test_workbench_cases.py
git commit -m "feat：更新工作台泛化案例目录"
```

---

### Task 8: Final Verification And Documentation Touches

**Files:**
- Modify: `README.md`
- Modify: `docs/phase5-capability-matrix.md`

- [ ] **Step 1: Update README Phase 5 notes**

Add a short Phase 5 section after Phase 4 in `README.md`:

```markdown
## Phase 5：Benchmark Generalization + Capability Completion

Phase 5 expands the deterministic eval surface from `curated_mvp` to
`generalized_mvp` and fills the main missing retail transaction capabilities:
name + zip authentication, pending order item modification, payment modification,
default address modification, and stronger multi-item return/exchange guards.

Run the generalized deterministic eval:

```bash
uv run phase2-eval --subset generalized_mvp --trials 1 --no-progress --json
```

The Phase 5 design and capability matrix live in:

```text
docs/superpowers/specs/2026-06-12-phase5-benchmark-generalization-design.md
docs/phase5-capability-matrix.md
```
```

- [ ] **Step 2: Update capability matrix with implemented case ids**

In `docs/phase5-capability-matrix.md`, add a short `Implemented Cases` section listing the final `generalized_mvp` case ids grouped by capability.

- [ ] **Step 3: Run full Python test suite**

Run:

```bash
uv run python -m unittest discover -s tests
```

Expected: `OK`.

- [ ] **Step 4: Run curated eval**

Run:

```bash
uv run phase2-eval --subset curated_mvp --trials 1 --no-progress --json
```

Expected: JSON summary with `"pass_rate": 1.0`, `"passed_count": 11`, and `"mutation_error_rate": 0.0`.

- [ ] **Step 5: Run generalized eval**

Run:

```bash
uv run phase2-eval --subset generalized_mvp --trials 1 --no-progress --json
```

Expected: JSON summary with `"pass_rate": 1.0`, `"case_count"` at least `30`, and `"mutation_error_rate": 0.0`.

- [ ] **Step 5a: Add programmatic case count assertion test**

Add this test to `tests/test_eval_runner.py` to enforce the minimum case count:

```python
    def test_generalized_mvp_has_minimum_case_count(self):
        cases = get_cases("generalized_mvp")
        self.assertGreaterEqual(
            len(cases), 30,
            f"generalized_mvp has {len(cases)} cases, expected at least 30"
        )
        subsets = {case.subset for case in cases}
        self.assertEqual(subsets, {"generalized_mvp"})
```

Run:
```bash
uv run python -m unittest tests.test_eval_runner.CuratedEvalTests.test_generalized_mvp_has_minimum_case_count -v
```
Expected: PASS.

- [ ] **Step 6: Run frontend build**

Run:

```bash
cd workbench && npm run build
```

Expected: Vite build succeeds.

- [ ] **Step 7: Run Chinese UI check**

Run:

```bash
cd workbench && npm run check:i18n
```

Expected: exit 0.

- [ ] **Step 8: Commit final docs**

```bash
git add README.md docs/phase5-capability-matrix.md
git commit -m "feat：完善Phase5验收文档"
```

---

## Execution Notes

- Use `uv run python ...` for Python tests because the project requires Python 3.12+ and dependencies from the uv environment.
- Use Chinese full-width colon commit messages for every commit, for example `feat：补齐本地零售写操作工具`.
- Keep `curated_mvp` passing after every task.
- Do not change trace schema version unless a task explicitly adds a breaking artifact contract.
- Do not redesign the workbench UI in Phase 5.

## Final Acceptance Checklist

- [ ] `uv run python -m unittest discover -s tests` passes.
- [ ] `uv run phase2-eval --subset curated_mvp --trials 1 --no-progress --json` reports 11/11 passing.
- [ ] `uv run phase2-eval --subset generalized_mvp --trials 1 --no-progress --json` reports at least 30/30 passing.
- [ ] `cd workbench && npm run build` passes.
- [ ] `cd workbench && npm run check:i18n` passes.
- [ ] `docs/phase5-capability-matrix.md` lists implemented generalized cases.
- [ ] Every Phase 5 commit uses `feat：中文描述` format.
