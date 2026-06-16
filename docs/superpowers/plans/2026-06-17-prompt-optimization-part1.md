# Prompt Optimization Part 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the retail agent system prompt to reduce redundant rules, add explicit stop conditions, and then add high-value complex few-shot examples without changing runtime or guard behavior.

**Architecture:** Keep the single-file prompt architecture centered on `prompts/llm_agent_system_v001.md`, but rewrite its internal sections into `Core Contract`, `Write Requests`, `Heuristics`, `Stop Conditions`, and `Examples`. Add lightweight regression tests that inspect the loaded prompt/template content so prompt-contract regressions are caught before live eval.

**Tech Stack:** Python, pytest, markdown prompt template, existing prompt loader in `app/agent/prompts.py`

---

## File Structure

- `prompts/llm_agent_system_v001.md` — the only runtime system prompt template; receives the full Phase A and Phase B edits
- `tests/test_agent_core.py` — add prompt-level regression tests near existing agent prompt / catalog coverage
- `docs/superpowers/specs/2026-06-17-prompt-optimization-part1-design.md` — approved design spec to reference while implementing
- `docs/superpowers/plans/2026-06-17-prompt-optimization-part1.md` — this implementation plan

### Task 1: Add Prompt Regression Tests For Contract Sections

**Files:**
- Modify: `tests/test_agent_core.py`
- Reference: `app/agent/prompts.py:42`
- Reference: `prompts/llm_agent_system_v001.md`

- [ ] **Step 1: Read the existing prompt-related tests in `tests/test_agent_core.py`**

Look for the existing prompt/catalog assertions so the new tests match local style and fixture patterns.

Run:
```bash
rg -n "catalog_for_prompt|prompt_metadata|llm_agent_system|PromptSpec" tests/test_agent_core.py app/agent/prompts.py
```

Expected: at least one hit around `test_catalog_for_prompt_includes_all_actions` and the prompt loader in `app/agent/prompts.py`.

- [ ] **Step 2: Write a failing test that requires explicit stop conditions in the active prompt**

Add a test that imports `AGENT_SYSTEM_PROMPT` and asserts the prompt content contains the `Stop Conditions` section and the three stop triggers.

```python
from app.agent.prompts import AGENT_SYSTEM_PROMPT


def test_agent_system_prompt_contains_stop_conditions_contract() -> None:
    content = AGENT_SYSTEM_PROMPT.content

    assert "## Stop Conditions" in content
    assert "all user-requested actions and questions are complete" in content
    assert "a guard block prevents progress and no useful alternative remains" in content
    assert "available tools cannot make further progress after reasonable retries" in content
```

- [ ] **Step 3: Run the new stop-condition test to verify it fails before prompt edits**

Run:
```bash
uv run python -m pytest tests/test_agent_core.py::test_agent_system_prompt_contains_stop_conditions_contract -q
```

Expected: FAIL because the current prompt does not yet define `## Stop Conditions`.

- [ ] **Step 4: Write a failing test that requires the new sectioned prompt structure**

Add a second regression test that asserts the prompt contains the new section headers and the write-through-guard contract, but no legacy `## Rules` / `## Workflow` pairing.

```python
def test_agent_system_prompt_uses_sectioned_contract_structure() -> None:
    content = AGENT_SYSTEM_PROMPT.content

    assert "## Core Contract" in content
    assert "## Write Requests" in content
    assert "## Heuristics" in content
    assert "## Stop Conditions" in content
    assert "must call the write tool and let the guard decide" in content
    assert "## Workflow" not in content
```

- [ ] **Step 5: Run the section-structure test to verify it fails before prompt edits**

Run:
```bash
uv run python -m pytest tests/test_agent_core.py::test_agent_system_prompt_uses_sectioned_contract_structure -q
```

Expected: FAIL because the current prompt still uses `## Rules` and `## Workflow`.

### Task 2: Implement Phase A Prompt Rewrite (`1.1 + 1.3`)

**Files:**
- Modify: `prompts/llm_agent_system_v001.md`
- Test: `tests/test_agent_core.py`
- Reference: `docs/superpowers/specs/2026-06-17-prompt-optimization-part1-design.md:1`

- [ ] **Step 1: Replace the `## Rules` block with a compressed `## Core Contract` section**

Edit `prompts/llm_agent_system_v001.md` so the top-level behavioral rules are reduced to roughly 8–10 items covering:

```text
- No data fabrication
- Read before write
- Always state order status when relevant
- Write through guard
- Handle guard blocks concisely
- Recover from tool errors when possible
- Complete multipart requests
- Use tools and calculate for money answers
- Do not retry successful writes
```

Keep the wording concise and imperative; do not keep duplicate copies of the same write-through-guard rule elsewhere in the file.

- [ ] **Step 2: Replace the legacy `CRITICAL` + `Workflow` sections with a compact `## Write Requests` section**

Edit `prompts/llm_agent_system_v001.md` so this new section says, in plain language:

```text
For any write request:
1. Read the relevant order or user facts first.
2. Then call the matching write tool immediately.
3. Even if you expect the operation to fail, still call the write tool.
4. If the guard asks for confirmation, ask the user to confirm.
5. If the guard blocks, explain the reason and offer a useful alternative if one exists.
```

Also keep one short `WRONG` / `RIGHT` example showing ownership mismatch but still calling the write tool.

- [ ] **Step 3: Add the new `## Heuristics` and `## Stop Conditions` sections**

Insert both sections into `prompts/llm_agent_system_v001.md`.

Use wording equivalent to:

```text
## Heuristics
- Use loaded recent orders before asking for IDs.
- Use the single known payment method when exactly one usable method exists.
- Combine same-order item changes into one write call.
- Match replacement variants exactly.
- Use only order item_ids from get_order_details for returns and exchanges.
- Avoid exhaustive fallback loops when a direct supported action exists.

## Stop Conditions
Stop and provide a final response when:
(a) all user-requested actions and questions are complete, or
(b) a guard block prevents progress and no useful alternative remains, or
(c) available tools cannot make further progress after reasonable retries.
```

- [ ] **Step 4: Preserve only the minimal Phase A example set**

Keep or rewrite example coverage so the prompt still includes these five anchor patterns:

```text
1. Order status lookup
2. Single write success
3. Single write guard block
4. Ownership violation but still call write tool
5. Transfer to human
```

Remove redundant examples that only restate the same guard contract without adding a new planning pattern.

- [ ] **Step 5: Run the two prompt regression tests to verify Phase A passes**

Run:
```bash
uv run python -m pytest \
  tests/test_agent_core.py::test_agent_system_prompt_contains_stop_conditions_contract \
  tests/test_agent_core.py::test_agent_system_prompt_uses_sectioned_contract_structure -q
```

Expected: PASS.

### Task 3: Add Phase B Complex Few-Shot Examples (`1.2`)

**Files:**
- Modify: `prompts/llm_agent_system_v001.md`
- Test: `tests/test_agent_core.py`
- Reference: `docs/superpowers/specs/2026-06-17-prompt-optimization-part1-design.md:1`

- [ ] **Step 1: Write a failing prompt regression test for complex continuation examples**

Add a third test that asserts the prompt contains three complex example themes: return + refund total, exchange + price difference, and successful write + remaining subtask completion.

```python
def test_agent_system_prompt_contains_complex_continuation_examples() -> None:
    content = AGENT_SYSTEM_PROMPT.content

    assert "total refund" in content
    assert "price difference" in content
    assert "continue with the remaining part of the original request" in content
```

- [ ] **Step 2: Run the complex-example test to verify it fails before adding Phase B examples**

Run:
```bash
uv run python -m pytest tests/test_agent_core.py::test_agent_system_prompt_contains_complex_continuation_examples -q
```

Expected: FAIL because the prompt does not yet contain all three complex continuation cues.

- [ ] **Step 3: Add a return + refund-total few-shot example**

Edit `prompts/llm_agent_system_v001.md` to add an example with this behavior:

```text
User asks to return one or more delivered items and also asks how much money they will get back.
→ call get_order_details
→ call return_delivered_order_items
→ after success, use tool observations and calculate to total only the returned item prices
→ final response includes both the successful return action and the refund amount
```

Make the example explicit that the agent should not stop after the write succeeds.

- [ ] **Step 4: Add an exchange + price-difference / gift-card-balance few-shot example**

Edit `prompts/llm_agent_system_v001.md` to add an example with this behavior:

```text
User asks to exchange an item and asks for the price difference or resulting gift card balance.
→ call get_order_details
→ call get_product_details if needed
→ call exchange_delivered_order_items
→ after success, compute the old-item minus new-item difference
→ final response includes both the exchange result and the money answer
```

Use wording that reinforces exact replacement matching and post-write continuation.

- [ ] **Step 5: Add a multi-part continuation example after a successful write**

Edit `prompts/llm_agent_system_v001.md` to add an example like:

```text
User asks to cancel the pending order and also asks a second question, such as the most expensive item or amount affected.
→ call get_order_details
→ call cancel_pending_order
→ after success, continue answering the remaining part of the original request
→ only then provide the final response
```

The example must explicitly teach “do not summarize early.”

- [ ] **Step 6: Run the complex-example regression test to verify Phase B passes**

Run:
```bash
uv run python -m pytest tests/test_agent_core.py::test_agent_system_prompt_contains_complex_continuation_examples -q
```

Expected: PASS.

### Task 4: Run Focused Validation And Review Prompt Diffs

**Files:**
- Modify: `prompts/llm_agent_system_v001.md`
- Modify: `tests/test_agent_core.py`
- Reference: `app/agent/prompts.py:47`

- [ ] **Step 1: Run the targeted prompt regression test set together**

Run:
```bash
uv run python -m pytest \
  tests/test_agent_core.py::test_agent_system_prompt_contains_stop_conditions_contract \
  tests/test_agent_core.py::test_agent_system_prompt_uses_sectioned_contract_structure \
  tests/test_agent_core.py::test_agent_system_prompt_contains_complex_continuation_examples -q
```

Expected: `3 passed`.

- [ ] **Step 2: Run the adjacent agent-core test that already covers prompt catalog assembly**

Run:
```bash
uv run python -m pytest tests/test_agent_core.py::test_catalog_for_prompt_includes_all_actions -q
```

Expected: PASS, showing the prompt rewrite did not break adjacent prompt/catalog assumptions.

- [ ] **Step 3: Inspect the prompt hash change through a lightweight metadata assertion if needed**

If there is an existing metadata-oriented test pattern nearby, add or update a small assertion so the active prompt still exposes stable metadata fields:

```python
from app.agent.prompts import prompt_metadata


def test_prompt_metadata_exposes_active_system_prompt_fields() -> None:
    metadata = prompt_metadata()
    system_prompt = metadata["llm_agent_system"]

    assert system_prompt["prompt_id"] == "llm_agent_system_v001"
    assert system_prompt["path"] == "prompts/llm_agent_system_v001.md"
    assert len(system_prompt["sha256"]) == 64
```

Then run:
```bash
uv run python -m pytest tests/test_agent_core.py::test_prompt_metadata_exposes_active_system_prompt_fields -q
```

Expected: PASS.

- [ ] **Step 4: Run one small eval subset to validate planner behavior after the prompt-only change**

Run:
```bash
uv run phase2-eval --subset generalized_mvp --live --max-workers 50
```

Expected: pass rate remains at or near the existing baseline shown in `HANDOFF.md`, with no obvious regression in write-through-guard behavior.

- [ ] **Step 5: Commit the prompt optimization work**

```bash
git add prompts/llm_agent_system_v001.md tests/test_agent_core.py docs/superpowers/specs/2026-06-17-prompt-optimization-part1-design.md docs/superpowers/plans/2026-06-17-prompt-optimization-part1.md
git commit -m "feat: 优化 agent system prompt 结构与 few-shot"
```

## Self-Review Checklist

- Spec coverage:
  - `1.1` rule compression is implemented in Task 2
  - `1.3` stop conditions are implemented in Task 2 and tested in Tasks 1/4
  - `1.2` complex few-shot is implemented in Task 3 and tested in Tasks 3/4
- Placeholder scan:
  - No `TODO` / `TBD` / “similar to previous task” shortcuts remain
- Type consistency:
  - Test names consistently reference `AGENT_SYSTEM_PROMPT`, `prompt_metadata`, and prompt section names used in the spec

## Notes For Execution

- Do not split `1.2` into a separate feature branch or separate design artifact; it is Phase B of the same prompt optimization theme.
- If the exact phrasing in the regression tests feels too brittle, keep the tests checking stable section headers and distinctive phrases rather than entire paragraphs.
- If the eval subset is noisy, still report the exact outcome rather than weakening the prompt regression tests.
