# Tau Wrong-Tool Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce tau `wrong_tool` failures by adding a reusable focus subset and a deterministic action-candidate retry path that pushes complex write requests toward the correct guarded write tool instead of premature human transfer.

**Architecture:** Add a narrow tau focus subset for fast feedback, then introduce an `ActionCandidate` detector that derives a target write tool from the user request and loaded context. `AgentLoop` keeps the existing LLM loop and `ToolGateway`/`WriteActionGuard` safety boundary, but when the LLM attempts `transfer_to_human_agents` before any write attempt, it returns a structured retry message naming the candidate write action and context to load/use.

**Tech Stack:** Python 3.11+, Pydantic compatibility layer, `unittest`/`pytest`, existing retail adapter runtime, existing eval runner.

---

## File Structure

- Modify `app/eval/tau_loader.py` to expose `get_tau_wrong_tool_focus_cases()` using the 19 tau IDs from `docs/optimize/way-to-fix-tau-wrong-tool-handoff.md`.
- Modify `app/eval/cases.py` to register `tau_retail_wrong_tool_focus` in `get_cases()`.
- Create `app/agent/action_candidates.py` for deterministic, generic write-action candidate detection. This file owns matching user intent to write tool names and selecting a best-known order/item hint from loaded context.
- Modify `app/agent/models.py` to add `ActionCandidate`, `SessionState.current_action_candidate`, and `TurnContext.action_candidate_invoked`.
- Modify `app/agent/llm_agent.py` to compute candidates at turn start, include candidate context in `_build_messages()`, and use candidates in `_block_premature_transfer()`.
- Modify `tests/test_tau_loader.py` for the focus subset dispatch and ID selection.
- Modify `tests/test_session_state.py` for candidate model persistence.
- Modify `tests/test_agent_core.py` for candidate detection and transfer retry behavior.

---

### Task 1: Add Tau Wrong-Tool Focus Subset

**Files:**
- Modify: `app/eval/tau_loader.py`
- Modify: `app/eval/cases.py:1882`
- Test: `tests/test_tau_loader.py`

- [ ] **Step 1: Write the failing focus-loader tests**

Add this test near the existing tau subset tests in `tests/test_tau_loader.py`:

```python
def test_get_tau_wrong_tool_focus_cases_filters_known_ids(monkeypatch):
    from app.eval import tau_loader as loader_mod

    tasks = [
        {
            "id": 45,
            "user_scenario": {"instructions": {"reason_for_call": "You want to cancel your order."}},
            "evaluation_criteria": {"actions": [{"name": "cancel_pending_order", "arguments": {"order_id": "#W1000001"}}]},
        },
        {
            "id": 71,
            "user_scenario": {"instructions": {"reason_for_call": "You want to return an item."}},
            "evaluation_criteria": {"actions": [{"name": "return_delivered_order_items", "arguments": {"order_id": "#W1000002", "item_ids": ["item_1"]}}]},
        },
        {
            "id": 999,
            "user_scenario": {"instructions": {"reason_for_call": "You want to cancel your order."}},
            "evaluation_criteria": {"actions": [{"name": "cancel_pending_order", "arguments": {"order_id": "#W1000003"}}]},
        },
    ]

    monkeypatch.setattr(loader_mod, "load_tasks", lambda retail_dir: tasks)
    monkeypatch.setattr(loader_mod, "_resolve_tau3_retail_dir", lambda config: "retail_dir")

    cases = loader_mod.get_tau_wrong_tool_focus_cases(object())

    assert [case.case_id for case in cases] == ["tau_71", "tau_45"]
    assert {case.subset for case in cases} == {"tau_retail_wrong_tool_focus"}
```

Add dispatch coverage near `test_get_cases_supports_tau_retail_all_subset`:

```python
def test_get_cases_supports_tau_wrong_tool_focus_subset(monkeypatch):
    from app.eval import cases as cases_mod
    from app.eval import tau_loader as loader_mod
    from app.eval.cases import EvalCase

    expected_cases = [
        EvalCase(
            case_id="tau_45",
            category="cancel_order",
            messages=[{"role": "user", "content": "cancel"}],
            expected_intent="cancel_order",
            expected_tool_names=["cancel_pending_order"],
            subset="tau_retail_wrong_tool_focus",
        )
    ]

    monkeypatch.setattr(loader_mod, "get_tau_wrong_tool_focus_cases", lambda config: expected_cases)

    assert cases_mod.get_cases("tau_retail_wrong_tool_focus") == expected_cases
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `uv run python -m pytest tests/test_tau_loader.py -q`

Expected: FAIL because `get_tau_wrong_tool_focus_cases` and `get_cases("tau_retail_wrong_tool_focus")` do not exist.

- [ ] **Step 3: Implement the focus loader**

Add this constant near `SMOKE_TASK_IDS` in `app/eval/tau_loader.py`:

```python
WRONG_TOOL_FOCUS_TASK_IDS: tuple[str, ...] = (
    "46", "36", "47", "72", "71", "45", "88", "84", "92", "91",
    "93", "94", "95", "97", "98", "107", "109", "110", "113",
)
```

Add this function after `get_tau_all_cases()`:

```python
def get_tau_wrong_tool_focus_cases(config: AppConfig) -> list[EvalCase]:
    """Return the fixed tau wrong_tool focus set from the 2026-06-26 triage."""
    from app.analysis.tau_task_analyzer import _resolve_tau3_retail_dir, load_tasks

    retail_dir = _resolve_tau3_retail_dir(config)
    tasks_by_id = {str(task["id"]): task for task in load_tasks(retail_dir)}

    cases: list[EvalCase] = []
    for task_id in WRONG_TOOL_FOCUS_TASK_IDS:
        task = tasks_by_id.get(task_id)
        if task is None:
            continue
        case = convert_task_to_eval_case(task, "tau_retail_wrong_tool_focus", max_turns=5)
        if case is not None:
            cases.append(case)
    return cases
```

Add this branch to `app/eval/cases.py` before the final `raise`:

```python
    if subset == "tau_retail_wrong_tool_focus":
        from app.config import resolve_config
        from app.eval.tau_loader import get_tau_wrong_tool_focus_cases

        return get_tau_wrong_tool_focus_cases(resolve_config())
```

- [ ] **Step 4: Run the tests to verify pass**

Run: `uv run python -m pytest tests/test_tau_loader.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/eval/tau_loader.py app/eval/cases.py tests/test_tau_loader.py
git commit -m "test: 新增 tau wrong_tool focus 子集"
```

---

### Task 2: Add Action Candidate Models

**Files:**
- Modify: `app/agent/models.py`
- Test: `tests/test_session_state.py`

- [ ] **Step 1: Write the failing model persistence test**

Append to `tests/test_session_state.py`:

```python
def test_session_state_stores_current_action_candidate():
    from app.agent.models import ActionCandidate, SessionState

    candidate = ActionCandidate(
        tool_name="cancel_pending_order",
        confidence="high",
        reason="User asked to cancel an order.",
        order_id="#W1000001",
        required_read_tools=["get_order_details"],
    )
    session = SessionState(session_id="s1", current_action_candidate=candidate)

    assert session.current_action_candidate.tool_name == "cancel_pending_order"
    assert session.current_action_candidate.order_id == "#W1000001"
    assert session.current_action_candidate.required_read_tools == ["get_order_details"]
```

- [ ] **Step 2: Run the test to verify failure**

Run: `uv run python -m pytest tests/test_session_state.py::test_session_state_stores_current_action_candidate -q`

Expected: FAIL because `ActionCandidate` is not defined.

- [ ] **Step 3: Add the models**

In `app/agent/models.py`, add after `PolicyDecision`:

```python
class ActionCandidate(BaseModel):
    tool_name: str
    confidence: Literal["low", "medium", "high"] = "medium"
    reason: str
    order_id: Optional[str] = None
    item_ids: List[str] = Field(default_factory=list)
    product_ids: List[str] = Field(default_factory=list)
    required_read_tools: List[str] = Field(default_factory=list)
```

Add to `SessionState` after `pending_action`:

```python
    current_action_candidate: Optional[ActionCandidate] = None
```

Add to `TurnContext` after `prompt_injection_signals`:

```python
    action_candidate_invoked: bool = False
```

- [ ] **Step 4: Run the test to verify pass**

Run: `uv run python -m pytest tests/test_session_state.py::test_session_state_stores_current_action_candidate -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/models.py tests/test_session_state.py
git commit -m "feat: 增加写操作候选模型"
```

---

### Task 3: Implement Generic Action Candidate Detection

**Files:**
- Create: `app/agent/action_candidates.py`
- Test: `tests/test_agent_core.py`

- [ ] **Step 1: Write failing candidate detection tests**

Add import near the top of `tests/test_agent_core.py`:

```python
from app.agent.action_candidates import detect_action_candidate
```

Append this test class before `TokenAwareTruncationTests`:

```python
class ActionCandidateDetectionTests(unittest.TestCase):
    def test_detects_cancel_candidate_with_explicit_order_id(self):
        session = SessionState(session_id="test", authenticated_user_id=PENDING_USER)

        candidate = detect_action_candidate(
            session,
            "Please cancel order #W5918442 because I ordered by mistake.",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.tool_name, "cancel_pending_order")
        self.assertEqual(candidate.order_id, "#W5918442")
        self.assertEqual(candidate.confidence, "high")
        self.assertIn("get_order_details", candidate.required_read_tools)

    def test_detects_return_candidate_from_loaded_delivered_order(self):
        session = SessionState(session_id="test", authenticated_user_id=DELIVERED_USER)
        session.loaded_context.orders[DELIVERED_ORDER] = {
            "order_id": DELIVERED_ORDER,
            "status": "delivered",
            "items": [{"item_id": DELIVERED_ITEM, "product_id": "prod_1", "price": 10.0}],
        }

        candidate = detect_action_candidate(session, "I want to return the cheaper item.")

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.tool_name, "return_delivered_order_items")
        self.assertEqual(candidate.order_id, DELIVERED_ORDER)
        self.assertEqual(candidate.item_ids, [DELIVERED_ITEM])

    def test_ignores_explicit_human_request(self):
        session = SessionState(session_id="test", authenticated_user_id=PENDING_USER)

        candidate = detect_action_candidate(session, "I need a human agent to help me.")

        self.assertIsNone(candidate)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run python -m pytest tests/test_agent_core.py::ActionCandidateDetectionTests -q`

Expected: FAIL because `app.agent.action_candidates` does not exist.

- [ ] **Step 3: Implement the detector**

Create `app/agent/action_candidates.py`:

```python
from __future__ import annotations

import re
from typing import Any

from app.agent.guard import _canonical_order_id
from app.agent.models import ActionCandidate, SessionState

_ORDER_ID_RE = re.compile(r"#?(?:W)?(\d{7,})", re.IGNORECASE)
_HUMAN_RE = re.compile(r"\b(?:human|agent|representative|person)\b", re.IGNORECASE)
_CANCEL_RE = re.compile(r"\bcancel\b", re.IGNORECASE)
_RETURN_RE = re.compile(r"\breturn\b", re.IGNORECASE)
_EXCHANGE_RE = re.compile(r"\bexchange\b", re.IGNORECASE)
_ADDRESS_RE = re.compile(r"\baddress\b", re.IGNORECASE)
_PAYMENT_RE = re.compile(r"\bpayment\b", re.IGNORECASE)
_SHIPPING_RE = re.compile(r"\b(?:shipping|delivery)\b", re.IGNORECASE)
_ITEM_CHANGE_RE = re.compile(r"\b(?:replace|switch|change|modify|update|remove|add)\b", re.IGNORECASE)


def detect_action_candidate(session: SessionState, user_content: str) -> ActionCandidate | None:
    if _HUMAN_RE.search(user_content) and not _has_write_signal(user_content):
        return None

    order_id = _extract_order_id(user_content) or _best_loaded_order_id(session)
    tool_name = _detect_tool_name(user_content)
    if tool_name is None:
        return None

    return ActionCandidate(
        tool_name=tool_name,
        confidence="high" if order_id else "medium",
        reason=_reason_for(tool_name),
        order_id=order_id,
        item_ids=_selected_item_ids(session, order_id, user_content),
        required_read_tools=_required_read_tools(tool_name, order_id),
    )


def _has_write_signal(text: str) -> bool:
    return any(pattern.search(text) for pattern in (_CANCEL_RE, _RETURN_RE, _EXCHANGE_RE, _ADDRESS_RE, _PAYMENT_RE, _SHIPPING_RE, _ITEM_CHANGE_RE))


def _detect_tool_name(text: str) -> str | None:
    if _CANCEL_RE.search(text):
        return "cancel_pending_order"
    if _RETURN_RE.search(text):
        return "return_delivered_order_items"
    if _EXCHANGE_RE.search(text):
        return "exchange_delivered_order_items"
    if _PAYMENT_RE.search(text):
        return "modify_pending_order_payment"
    if _SHIPPING_RE.search(text):
        return "modify_pending_order_shipping_method"
    if _ADDRESS_RE.search(text):
        return "modify_pending_order_address"
    if _ITEM_CHANGE_RE.search(text):
        return "modify_pending_order_items"
    return None


def _extract_order_id(text: str) -> str | None:
    match = _ORDER_ID_RE.search(text)
    if not match:
        return None
    return _canonical_order_id(match.group(0))


def _best_loaded_order_id(session: SessionState) -> str | None:
    if not session.loaded_context.orders:
        return None
    return next(reversed(session.loaded_context.orders.keys()))


def _selected_item_ids(session: SessionState, order_id: str | None, text: str) -> list[str]:
    if not order_id:
        return []
    order = session.loaded_context.orders.get(order_id) or {}
    items = order.get("items") or []
    if not isinstance(items, list):
        return []
    normalized = [_item_summary(item) for item in items]
    normalized = [item for item in normalized if item.get("item_id")]
    if not normalized:
        return []
    if re.search(r"\b(?:cheaper|cheapest|least expensive)\b", text, re.IGNORECASE):
        return [min(normalized, key=lambda item: item.get("price", 0))["item_id"]]
    if re.search(r"\b(?:expensive|priciest|costliest)\b", text, re.IGNORECASE):
        return [max(normalized, key=lambda item: item.get("price", 0))["item_id"]]
    if len(normalized) == 1:
        return [normalized[0]["item_id"]]
    return []


def _item_summary(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    item_id = item.get("item_id") or item.get("id")
    price = item.get("price") or item.get("unit_price") or 0
    return {"item_id": str(item_id) if item_id else "", "price": float(price or 0)}


def _required_read_tools(tool_name: str, order_id: str | None) -> list[str]:
    if tool_name == "modify_user_address":
        return ["get_user_details"]
    if order_id:
        return ["get_order_details"]
    return []


def _reason_for(tool_name: str) -> str:
    return {
        "cancel_pending_order": "User asked to cancel an order.",
        "return_delivered_order_items": "User asked to return delivered order items.",
        "exchange_delivered_order_items": "User asked to exchange delivered order items.",
        "modify_pending_order_address": "User asked to change an order address.",
        "modify_pending_order_items": "User asked to change order items.",
        "modify_pending_order_payment": "User asked to change payment.",
        "modify_pending_order_shipping_method": "User asked to change shipping.",
        "modify_user_address": "User asked to change account address.",
    }.get(tool_name, "User request matches a write action.")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run python -m pytest tests/test_agent_core.py::ActionCandidateDetectionTests -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/action_candidates.py tests/test_agent_core.py
git commit -m "feat: 检测复杂写操作候选"
```

---

### Task 4: Surface Candidate Context In AgentLoop

**Files:**
- Modify: `app/agent/llm_agent.py`
- Test: `tests/test_agent_core.py`

- [ ] **Step 1: Write failing AgentLoop context test**

Add this test to `GuardBlockCountingTests`:

```python
    def test_build_messages_includes_action_candidate_context(self):
        session = self._session(PENDING_USER, order_id=PENDING_ORDER)
        provider = MagicMock(spec=LLMProvider)
        provider.chat_with_tools.return_value = self._text_response("I can help with that.")
        loop = self._make_loop(provider)

        loop.run_turn(session, "Please cancel order #W5918442 because I no longer need it.")

        self.assertIsNotNone(session.current_action_candidate)
        self.assertEqual(session.current_action_candidate.tool_name, "cancel_pending_order")
        messages = loop._build_messages(session, "Please cancel order #W5918442 because I no longer need it.")
        candidate_messages = [message for message in messages if "Action Candidate" in message.get("content", "")]
        self.assertTrue(candidate_messages)
        self.assertIn("cancel_pending_order", candidate_messages[0]["content"])
```

- [ ] **Step 2: Run the test to verify failure**

Run: `uv run python -m pytest tests/test_agent_core.py::GuardBlockCountingTests::test_build_messages_includes_action_candidate_context -q`

Expected: FAIL because candidates are not computed or rendered.

- [ ] **Step 3: Compute candidate at turn start**

In `app/agent/llm_agent.py`, add import:

```python
from app.agent.action_candidates import detect_action_candidate
```

In `run_turn()`, immediately after `turn = TurnContext()` is created, add:

```python
        session.current_action_candidate = detect_action_candidate(session, user_content)
        if session.current_action_candidate is not None:
            turn.action_candidate_invoked = True
            turn.add_step(
                "action_candidate_detected",
                tool_name=session.current_action_candidate.tool_name,
                confidence=session.current_action_candidate.confidence,
                order_id=session.current_action_candidate.order_id,
            )
```

- [ ] **Step 4: Render candidate in `_build_messages()`**

Find `_build_messages()` in `app/agent/llm_agent.py`. After the current session-state assistant message is appended, add:

```python
        if session.current_action_candidate is not None:
            candidate = session.current_action_candidate
            candidate_lines = [
                "Action Candidate:",
                f"- tool_name: {candidate.tool_name}",
                f"- confidence: {candidate.confidence}",
                f"- reason: {candidate.reason}",
            ]
            if candidate.order_id:
                candidate_lines.append(f"- order_id: {candidate.order_id}")
            if candidate.item_ids:
                candidate_lines.append(f"- item_ids: {candidate.item_ids}")
            if candidate.required_read_tools:
                candidate_lines.append(f"- required_read_tools: {candidate.required_read_tools}")
            candidate_lines.append(
                "If this matches the user's request, use the required read tools first if needed, then call the candidate write tool so the guard can decide."
            )
            messages.append({"role": "assistant", "content": "\n".join(candidate_lines)})
```

- [ ] **Step 5: Run the test to verify pass**

Run: `uv run python -m pytest tests/test_agent_core.py::GuardBlockCountingTests::test_build_messages_includes_action_candidate_context -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/agent/llm_agent.py tests/test_agent_core.py
git commit -m "feat: 注入写操作候选上下文"
```

---

### Task 5: Use Candidate To Block Premature Transfer More Precisely

**Files:**
- Modify: `app/agent/llm_agent.py`
- Test: `tests/test_agent_core.py`

- [ ] **Step 1: Write failing premature-transfer tests**

Add these tests to `GuardBlockCountingTests`:

```python
    def test_action_candidate_blocks_transfer_before_write_attempt(self):
        session = self._session(PENDING_USER, order_id=PENDING_ORDER)
        provider = MagicMock(spec=LLMProvider)
        provider.chat_with_tools.side_effect = [
            self._single_tool_response("transfer_to_human_agents", summary="Need help."),
            self._single_tool_response(
                "cancel_pending_order",
                order_id=PENDING_ORDER,
                reason="no longer needed",
            ),
            self._text_response("I started the cancellation request."),
        ]

        loop = self._make_loop(provider)
        result = loop.run_turn(session, "Please cancel order #W5918442 because I no longer need it.")

        self.assertTrue(result.pending_action_set)
        self.assertEqual(session.tool_results[0].tool_name, "transfer_to_human_agents")
        self.assertEqual(session.tool_results[0].status, "blocked")
        self.assertEqual(session.tool_results[0].error, "premature_transfer_blocked")
        self.assertEqual(session.tool_results[0].block_context["matched_write_tool"], "cancel_pending_order")
        self.assertEqual(session.pending_action.action_name, "cancel_pending_order")

    def test_action_candidate_allows_transfer_after_write_attempt(self):
        session = self._session(PENDING_USER, order_id=PENDING_ORDER)
        session.tool_results.append(
            ToolCallRecord(
                tool_name="cancel_pending_order",
                arguments={"order_id": PENDING_ORDER, "reason": "no longer needed"},
                tool_kind="write",
                status="blocked",
                error="explicit_confirmation_required",
            )
        )
        provider = MagicMock(spec=LLMProvider)
        provider.chat_with_tools.side_effect = [
            self._single_tool_response("transfer_to_human_agents", summary="Need help."),
            self._text_response("I transferred you."),
        ]

        loop = self._make_loop(provider)
        loop.run_turn(session, "Please cancel order #W5918442 because I no longer need it.")

        self.assertEqual(session.tool_results[-1].tool_name, "transfer_to_human_agents")
        self.assertEqual(session.tool_results[-1].status, "success")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run python -m pytest tests/test_agent_core.py::GuardBlockCountingTests::test_action_candidate_blocks_transfer_before_write_attempt tests/test_agent_core.py::GuardBlockCountingTests::test_action_candidate_allows_transfer_after_write_attempt -q`

Expected: At least the first test fails because `_block_premature_transfer()` does not consistently use candidate context.

- [ ] **Step 3: Update `_block_premature_transfer()`**

Replace the matched-tool detection block in `_block_premature_transfer()` with:

```python
        candidate = session.current_action_candidate
        matched_tool: str | None = None
        if candidate is not None:
            matched_tool = candidate.tool_name
        else:
            for tool_name, pattern in self._WRITE_KEYWORD_PATTERNS:
                if pattern.search(user_content):
                    matched_tool = tool_name
                    break
        if matched_tool is None:
            return None
```

Use this `block_context` for both the `ToolCallRecord` and `ToolExecutionError`:

```python
        block_context = {
            "matched_write_tool": matched_tool,
            "candidate_order_id": candidate.order_id if candidate else None,
            "candidate_item_ids": candidate.item_ids if candidate else [],
        }
```

Set `message_for_llm` to:

```python
                f"Do not transfer yet. The user's request matches '{matched_tool}'. "
                "Use the required read tools first if context is missing, then call "
                f"{matched_tool} so the guard can evaluate it. "
                "Only transfer after the write tool is attempted and blocked, or if the user explicitly asks only for a human agent."
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run python -m pytest tests/test_agent_core.py::GuardBlockCountingTests::test_action_candidate_blocks_transfer_before_write_attempt tests/test_agent_core.py::GuardBlockCountingTests::test_action_candidate_allows_transfer_after_write_attempt -q`

Expected: PASS.

- [ ] **Step 5: Run explicit transfer-priority regression**

Run: `uv run python -m pytest tests/test_agent_core.py::GuardBlockCountingTests::test_human_transfer_preflight_takes_priority_over_same_turn_cancel -q`

Expected: PASS. Runtime preflight still honors explicit human-transfer priority before entering `AgentLoop`.

- [ ] **Step 6: Commit**

```bash
git add app/agent/llm_agent.py tests/test_agent_core.py
git commit -m "fix: 用写操作候选拦截过早转人工"
```

---

### Task 6: Validate Focus Subset And Guard Boundaries

**Files:**
- No production code unless tests reveal a defect in Tasks 1–5
- Optional report: `docs/optimize/tau-wrong-tool-orchestrator-results.md`

- [ ] **Step 1: Run targeted unit tests**

Run: `uv run python -m pytest tests/test_tau_loader.py tests/test_session_state.py tests/test_agent_core.py::ActionCandidateDetectionTests tests/test_agent_core.py::GuardBlockCountingTests -q`

Expected: PASS.

- [ ] **Step 2: Run focus live eval at low concurrency**

Run: `uv run phase2-eval --subset tau_retail_wrong_tool_focus --live --max-workers 3`

Expected: At least one case should move away from `wrong_tool`. If all 19 remain `wrong_tool`, inspect trace records for `action_candidate_detected` and `premature_transfer_blocked` before changing code.

- [ ] **Step 3: Run full tau all comparison**

Run: `uv run phase2-eval --subset tau_retail_all --live --max-workers 3`

Expected: Overall pass rate should not drop below the recent documented live range of 85/114–88/114 except for provider instability. `guard_blocked` and `tool_exception` should not increase because all writes still route through `ToolGateway`.

- [ ] **Step 4: Document eval outcome if live eval completes**

Create `docs/optimize/tau-wrong-tool-orchestrator-results.md` with actual run IDs and counts:

```markdown
# Tau Wrong-Tool Orchestrator Results — 2026-06-26

## Unit Tests

- `uv run python -m pytest tests/test_tau_loader.py tests/test_session_state.py tests/test_agent_core.py::ActionCandidateDetectionTests tests/test_agent_core.py::GuardBlockCountingTests -q`: PASS

## Live Eval

- `tau_retail_wrong_tool_focus`: eval-run-id, passed-count/19
- `tau_retail_all`: eval-run-id, passed-count/114

## Notes

- Candidate detector fired in traces for complex write requests.
- All write attempts still went through `ToolGateway` and `WriteActionGuard`.
```

- [ ] **Step 5: Commit validation report if created**

```bash
git add docs/optimize/tau-wrong-tool-orchestrator-results.md
git commit -m "docs: 记录 tau wrong_tool orchestrator 验证结果"
```

---

## Self-Review

- Spec coverage: The plan implements the focus subset, candidate context, precise premature-transfer retry, and validation loop recommended after reviewing `docs/optimize/way-to-fix-tau-wrong-tool-handoff.md`.
- Placeholder scan: No `TBD`, `TODO`, or unspecified implementation steps remain. The eval report template explicitly instructs replacing run IDs and counts after live eval.
- Type consistency: `ActionCandidate`, `SessionState.current_action_candidate`, and `TurnContext.action_candidate_invoked` are introduced before downstream tasks reference them.
- Safety boundary: No plan step bypasses `ToolGateway` or `WriteActionGuard`; the orchestrator only changes candidate context and retry guidance.
