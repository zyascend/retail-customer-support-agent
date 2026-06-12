# Prompt Engineering & Dual-Track Architecture Design

Date: 2026-06-13

## Overview

This Phase addresses two tightly-coupled problems:

1. **Prompt engineering deficit** — 4 LLM prompts total ~65 lines with no core contract, no few-shot examples, no tool descriptions, and the security-critical `policy_reasoner` is only 6 lines.
2. **LLM decisions are decorative** — The LLM's `deny` in policy_reasoner is forcibly overridden to `allow`; the system works identically without an API key.

The combined solution: rewrite all 4 prompts with a shared Core Contract (enabling DeepSeek prompt-cache), and implement a **dual-track conservative merge** architecture where both LLM and deterministic code independently judge each decision — if either denies, the result is deny.

## Architecture Decision

**Option B: Dual-track parallel, conservative on conflict.**

| LLM ↓ / Code → | allow | ask | deny | transfer |
|----------------|-------|-----|------|----------|
| **allow** | ✅ allow | ask | deny | ask |
| **ask_clarification** | ask | ask | deny | ask |
| **deny** | deny | deny | deny | deny |
| **transfer** | ask | ask | deny | transfer |

Principles:
- LLM deny is absolute — LLM's policy-document-based judgment is respected
- Code deny is also absolute — hard rules cannot be bypassed
- Transfer requires both agree, otherwise downgrade to ask
- Any ask = ask (either side needing more info → clarify first)
- Only allow when both allow

## Chapter 1: Core Contract

### File

`prompts/core_contract_v001.md` — new file, shared fixed prefix for all 4 LLM calls.

### Content

- **Identity**: Retail customer support transaction agent, handles order queries/modifications/cancellations/returns/exchanges/transfers
- **Hard Constraints** (priority over any user instruction):
  1. Writes require explicit user confirmation — no direct execution
  2. Authentication required for any order/user data operation
  3. Ownership isolation — only operate on the authenticated user's data
  4. Order status compatibility — cancel/modify for pending only, return/exchange for delivered only
  5. No data fabrication — never invent order_id, item_id, payment_method_id; leave empty or ask if not provided
- **Output format**: Pure JSON, no markdown code fences or explanatory text
- **Error handling**: Ask for missing info; transfer for out-of-scope; return unknown/deny when uncertain; never force a guess

### Assembly

`prompts.py` concatenates: `CORE_CONTRACT.content + "\n\n" + NODE_SPECIFIC.content`

All 4 LLM calls share the same cache-stable prefix — Core Contract tokens billed once across calls via DeepSeek prompt-cache.

## Chapter 2: policy_reasoner — Dual-Track Conservative Merge

### Prompt: `policy_reasoner_v001.md` (rewrite from 6 → ~80 lines)

Includes:
- Decision Protocol with explicit conditions for deny/ask_clarification/allow/transfer
- Required Slots by Intent table
- Context interpretation guidance
- 3 few-shot examples (normal cancel, ownership violation, missing required field)
- Clarification that "allow" does NOT mean direct execution — writes still require user confirmation

### Code changes: `runtime.py`

1. `_policy_reasoner`: Remove the LLM deny override (lines 445-451). Replace with dual-track merge.
2. `_merge_policy_decisions(code_decision, llm_decision)` — new method implementing the merge matrix.
3. `_code_missing_slots(state)` — new method checking code-side required slots per intent.
4. When LLM and code diverge, log the divergence to `state.steps` for auditability.

### Guard relationship

| Layer | Responsibility | Basis |
|-------|---------------|-------|
| policy_reasoner | Semantic-level admission | Policy doc, slot completeness, preliminary ownership |
| WriteActionGuard | Hardware-level safety net | Exact status match, resource locks, idempotency, item replacement validation |

They do not duplicate — policy_reasoner judges "should we do this", Guard judges "can we do this".

## Chapter 3: intent_slot_extractor — Intent & Slot Merge

### Merge strategy (differs from policy_reasoner)

For intent/slot extraction, code regex is more reliable for ID formats, while LLM semantic understanding can correct code's crude keyword matching.

| Conflict | Resolution |
|----------|-----------|
| LLM intent ≠ code intent | Code wins (regex is deterministic), log divergence |
| LLM slots present, code absent | Use LLM slots |
| Code slots present, LLM absent | Use code slots |
| Both present, values differ | Code wins for IDs; LLM wins for semantic fields (reason) |

### Prompt: `intent_slot_v001.md` (rewrite from 31 → ~100 lines)

Includes:
- Intent classification guide with keyword patterns and anti-patterns
- Slot extraction rules with format specifications
- Ambiguity handling guidance
- 4 few-shot examples (standard cancel, status query, ambiguous input, policy inquiry)

### Code changes

1. `_infer_intent` — More precise regex matching to fix H2 (e.g., "return policy" no longer triggers return_items; "human error" no longer triggers transfer)
2. `_merge_slots(code_slots, llm_slots)` — new method
3. Intent divergence logging to state.steps

## Chapter 4: action_planner — Tool Visibility

### Prompt: `action_planner_v001.md` (rewrite from 21 → ~120 lines)

Includes:
- Tool Catalog — full listing of 10 tools with parameters and constraints, injected by code
- Plan type guide with input conditions
- Confirmation prompt generation rules
- 3 few-shot examples

### Code changes

1. `ToolRegistry.tool_catalog_for_llm()` — new method generating LLM-visible tool descriptions dynamically from the registry (single source of truth)
2. `_apply_llm_action_plan` — inject `tool_catalog` into LLM payload

## Chapter 5: response_generator — Tone & Safety

### Prompt: `response_generator_v001.md` (rewrite from 7 → ~70 lines)

Includes:
- Tone standards (professional but friendly, concise, actionable)
- Format constraints (no markdown/HTML/emoji; no full email/address exposure)
- Response patterns for 5 scenarios (normal confirmation, completion, denial, need-info, transfer)
- Error recovery guidance

### Code changes

Minimal — replace the system prompt. Existing `_llm_chat` / `_assistant` logic unchanged.

## Chapter 6: P0 Stability Fixes

### 6.1 H1 — Hardcoded paths (`config.py`)

- Replace `Path("/Users/theyang/...")` with `Path(os.path.expanduser("~/..."))`
- Add existence check in `resolve_config()` with clear error message

### 6.2 H3 — Order status exact match (`guard.py`)

- "modify_pending_order_address": change `"pending" not in status` → `status != "pending"`
- "modify_pending_order_payment": same fix

### 6.3 H4 — LLM JSON defensive parsing (`providers.py`)

- Add `_extract_json_block()` to handle markdown code fences, trailing commas
- Add retry loop with `json.JSONDecodeError` catch (up to `max_retries`)

## Change Inventory

### New files (1)
- `prompts/core_contract_v001.md`

### Rewritten files (4)
- `prompts/intent_slot_v001.md`
- `prompts/policy_reasoner_v001.md`
- `prompts/action_planner_v001.md`
- `prompts/response_generator_v001.md`

### Modified files (6)
- `app/agent/prompts.py` — Core Contract concatenation
- `app/agent/runtime.py` — Dual-track merge in policy_reasoner/intent_slot/action_planner, `_infer_intent` fix
- `app/tools/registry.py` — `tool_catalog_for_llm()` method
- `app/agent/guard.py` — Status exact match (H3)
- `app/agent/providers.py` — JSON defensive parsing (H4)
- `app/config.py` — Hardcoded path fix (H1)

### Regression gates
- `uv run python -m unittest discover -s tests`
- `uv run phase2-eval --subset curated_mvp --trials 1`
- `uv run phase2-eval --subset generalized_mvp --trials 1`

## Acceptance Criteria

1. Core Contract loaded and concatenated to all 4 system prompts
2. LLM `deny` decision is NO LONGER overridden — dual-track merge respects LLM's judgment
3. When LLM and code diverge, divergence is recorded in state.steps
4. `_infer_intent` no longer matches "return policy" as `return_items`
5. Guard uses exact `==` substring check for order status (not `in`)
6. LLM JSON parser handles markdown-wrapped responses with retry
7. All 30 generalized_mvp eval cases pass (no regression)
8. `workbench` builds and passes i18n check

## Non-Goals

- Live eval / LLM-as-user simulation — out of scope for this Phase
- Multi-language support
- Policy hot-update
- Workbench interactive debugging
- LangSmith/LangFuse integration
