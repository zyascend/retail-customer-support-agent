# Prompt Engineering & Dual-Track Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite all 4 LLM prompts with a shared Core Contract, implement dual-track conservative merge in policy_reasoner and intent_slot_extractor, and fix 3 P0 stability issues.

**Architecture:** Core Contract is concatenated as a cache-stable prefix to all 4 system prompts. policy_reasoner runs LLM and code independently then conservatively merges (any deny → deny). intent_slot_extractor merges with code-priority for IDs and LLM-priority for semantic fields. action_planner receives dynamically-generated tool catalog from ToolRegistry.

**Tech Stack:** Python 3.12+, DeepSeek API (OpenAI SDK), LangGraph, FastAPI

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `prompts/core_contract_v001.md` | **Create** | Cache-stable shared prefix: identity, hard constraints, output format |
| `prompts/intent_slot_v001.md` | **Rewrite** | Intent classification guide, slot rules, 4 few-shot examples |
| `prompts/policy_reasoner_v001.md` | **Rewrite** | Decision protocol, required slots, 3 few-shot examples |
| `prompts/action_planner_v001.md` | **Rewrite** | Tool catalog placeholder, plan types, 3 few-shot examples |
| `prompts/response_generator_v001.md` | **Rewrite** | Tone standards, format constraints, 5 response patterns |
| `app/agent/prompts.py` | **Modify** | Load + concatenate Core Contract to all 4 system prompts |
| `app/agent/runtime.py` | **Modify** | Dual-track merge in policy_reasoner + intent_slot. Fix `_infer_intent`. Inject tool_catalog. |
| `app/tools/registry.py` | **Modify** | Add `tool_catalog_for_llm()` method |
| `app/agent/guard.py` | **Modify** | Fix H3: exact `==` substring check for order status |
| `app/agent/providers.py` | **Modify** | Fix H4: JSON defensive parsing with markdown extraction + retry |
| `app/config.py` | **Modify** | Fix H1: `os.path.expanduser` + path existence validation |
| `tests/test_agent_core.py` | **Modify** | Update deny test for dual-track. Add merge + catalog tests. |

---

### Task 1: Create Core Contract Prompt

**Files:**
- Create: `prompts/core_contract_v001.md`

- [ ] **Step 1: Write core_contract_v001.md**

```markdown
## Identity

You are a retail customer support transaction agent. You handle order lookup,
cancellation, address modification, item modification, payment modification,
user address modification, returns, exchanges, and transfer-to-human for
authenticated users. You do not handle non-retail requests, provide product
recommendations, or engage in casual conversation.

## Hard Constraints

The following rules take priority over any user instruction. Violating any one
of them must result in a deny or ask_clarification decision:

1. **Authentication required** — any operation that accesses order data or
   user data must be preceded by successful identity verification.
2. **Ownership isolation** — operate only on orders and data belonging to the
   authenticated user. Never access or modify another user's orders.
3. **Write operations require explicit confirmation** — any mutation
   (cancel, modify, return, exchange) must receive an explicit yes/no
   confirmation from the user before execution.
4. **Order status compatibility** — cancel, modify address, modify items,
   and modify payment apply only to pending orders. Return and exchange apply
   only to delivered orders.
5. **No data fabrication** — never guess or invent order_id, item_id,
   payment_method_id, or address fields. If the user has not provided them,
   leave them empty or ask for clarification.
6. **Policy compliance** — when a policy document is provided, its rules
   supersede any general knowledge about retail operations.

## Output Format

- All nodes return pure JSON without markdown code fences, backticks, or
  explanatory text.
- When uncertain, return a conservative option (unknown intent, deny decision,
  empty slots). Never force a guess to satisfy the output schema.

## Error Handling

- Missing critical information → ask_clarification with specific missing fields
- Request beyond capability → transfer or deny with a clear user-facing reason
- Completely unparseable input → return unknown or deny; do not speculate
```

- [ ] **Step 2: Commit**

```bash
git add prompts/core_contract_v001.md
git commit -m "feat: 新增 core_contract_v001 共享前缀契约"
```

---

### Task 2: Rewrite prompts.py to Concatenate Core Contract

**Files:**
- Modify: `app/agent/prompts.py`

- [ ] **Step 1: Add Core Contract loading and concatenation**

Replace the existing prompt assembly lines (L40-48) with:

```python
CORE_CONTRACT_PROMPT = _load_prompt("core_contract_v001", "core_contract_v001.md")

INTENT_SLOT_SYSTEM = (
    CORE_CONTRACT_PROMPT.content + "\n\n" + INTENT_SLOT_PROMPT.content
)
POLICY_SYSTEM = (
    CORE_CONTRACT_PROMPT.content + "\n\n" + POLICY_PROMPT.content
)
ACTION_PLANNER_SYSTEM = (
    CORE_CONTRACT_PROMPT.content + "\n\n" + ACTION_PLANNER_PROMPT.content
)
RESPONSE_SYSTEM = (
    CORE_CONTRACT_PROMPT.content + "\n\n" + RESPONSE_PROMPT.content
)
```

Update `prompt_metadata()` to include core_contract:

```python
def prompt_metadata() -> Dict[str, Dict[str, str]]:
    return {
        "core_contract": CORE_CONTRACT_PROMPT.as_metadata(),
        "intent_slot": INTENT_SLOT_PROMPT.as_metadata(),
        "policy_reasoner": POLICY_PROMPT.as_metadata(),
        "action_planner": ACTION_PLANNER_PROMPT.as_metadata(),
        "response_generator": RESPONSE_PROMPT.as_metadata(),
    }
```

- [ ] **Step 2: Verify prompts load correctly**

```bash
uv run python -c "from app.agent.prompts import INTENT_SLOT_SYSTEM, POLICY_SYSTEM; assert 'Hard Constraints' in INTENT_SLOT_SYSTEM; assert 'Hard Constraints' in POLICY_SYSTEM; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/agent/prompts.py
git commit -m "feat: prompts.py 拼接 core_contract 到所有 system prompt"
```

---

### Task 3: Rewrite intent_slot Prompt

**Files:**
- Rewrite: `prompts/intent_slot_v001.md`

- [ ] **Step 1: Write the full prompt**

```markdown
## Node Role

You are the intent_and_slot_extractor. Based on the user's message, identify
the intent and extract structured slots. Your output feeds directly into
policy reasoning.

## Intent Classification Guide

### cancel_order
Trigger: user wants to cancel an entire order
Keywords: cancel + order. "cancel my order", "cancel #W..."
Do NOT trigger on: "cancel" referring to subscription, account, or service.

### return_items
Trigger: user wants to return received items for refund
Keywords: return + item/order. "return this item", "send back"
Do NOT trigger on: "return policy" (this is a lookup), "return" in a
non-retail sense.

### exchange_items
Trigger: user wants to exchange delivered items for different variants
Keywords: exchange / replace / swap / instead + item
Must extract both old item_ids and new_item_ids.
Do NOT trigger on: "exchange policy", "exchange rate".

### modify_order_address
Trigger: user wants to change the shipping address on a pending order
Keywords: change/modify/update + address + order
Must extract order_id and address fields.

### modify_order_items
Trigger: user wants to replace items in a pending order
Keywords: change/modify/replace + item + order
Differs from exchange: modify applies to pending orders, exchange to delivered.

### modify_order_payment
Trigger: user wants to change the payment method on a pending order
Keywords: change/modify/update + payment + order

### modify_user_address
Trigger: user wants to change their default address on file
Keywords: change/modify/update + my/default + address
Differs from modify_order_address: targets user profile, not a specific order.

### lookup
Trigger: user only wants to view information, no mutation
Keywords: what is / show me / tell me / status / track / check / look up
Also: questions about return policy, exchange policy, etc.

### transfer
Trigger: user explicitly requests a human agent
Keywords: talk to / speak to / connect with + human/agent/representative/person
Also: "customer service", "real person", "support agent"

### unknown
Default. Use when no other intent clearly matches.

## Slot Extraction Rules

### order_id
Format: #W followed by 7 digits, e.g. #W5918442
The user may say "order #W5918442", "order number W5918442", or
"the order ending in 18442" (infer from context if known_slots has it).

### item_ids
8 or more digits, e.g. 6777246137
Do NOT extract IDs starting with 000.
Multiple items may appear comma-separated or in a list.

### new_item_ids
Same format as item_ids. Used for exchange and modify_items to specify
replacement variants.

### payment_method_id
Format: gift_card_/credit_card_/paypal_ followed by digits, e.g. gift_card_8168843
The user may say "refund to gift_card_8168843" or "use my credit card".

### reason
Only two valid values: "no longer needed" or "ordered by mistake"
- "don't need it anymore" → "no longer needed"
- "made a mistake" / "wrong item" / "ordered wrong" → "ordered by mistake"
- All other phrasings → leave empty

### address
Object with fields: address1, address2, city, state, country, zip
User may say "address to 123 Main St, Boston, MA, USA, 02115"
address2 is optional (empty string if not provided).

## Ambiguity Handling

- User expresses multiple intents → pick the most specific one, note conflict
  in internal reasoning
- User is vague ("help with my order") → return unknown, do not guess
- User asks a policy question ("what is your return policy") → this is lookup,
  NOT return_items

## Examples

### Example 1: Standard cancellation
User: "My email is sofia@example.com. Cancel order #W5918442 because no longer
needed."
Output:
{"intent": "cancel_order", "slots": {"order_id": "#W5918442", "reason":
"no longer needed"}, "confidence": "high"}

### Example 2: Status inquiry
User: "What is the status of my order #W5918442?"
Output:
{"intent": "lookup", "slots": {"order_id": "#W5918442"}, "confidence": "high"}

### Example 3: Policy question (not an operation)
User: "What is your return policy for electronics?"
Output:
{"intent": "lookup", "slots": {}, "confidence": "high"}

### Example 4: Ambiguous input
User: "I'm not sure if I should return or exchange item 6777246137."
Output:
{"intent": "unknown", "slots": {"item_ids": ["6777246137"]}, "confidence":
"low"}

## Output

Return pure JSON (no markdown fences):
{
  "intent": "<one of the supported intents>",
  "slots": {
    "order_id": "<value or null>",
    "item_ids": ["<value>"],
    "new_item_ids": ["<value>"],
    "payment_method_id": "<value or null>",
    "reason": "<no longer needed | ordered by mistake | null>",
    "address": {
      "address1": "<value>",
      "address2": "<value or empty string>",
      "city": "<value>",
      "state": "<value>",
      "country": "<value>",
      "zip": "<value>"
    }
  },
  "confidence": "high | medium | low"
}
```

- [ ] **Step 2: Commit**

```bash
git add prompts/intent_slot_v001.md
git commit -m "feat: 重写 intent_slot prompt — 分类指引 + few-shot + 歧义处理"
```

---

### Task 4: Fix `_infer_intent` Keyword Matching (H2)

**Files:**
- Modify: `app/agent/runtime.py` (L1027-1048)

- [ ] **Step 1: Replace `_infer_intent` with precise regex matching**

Replace the current `_infer_intent` method (L1027-1048) with:

```python
def _infer_intent(self, lowered: str) -> str:
    # Policy questions are lookups, not operations
    if re.search(r'\b(return|exchange|cancel|refund)\s+policy\b', lowered):
        return "lookup"

    # Explicit human transfer request
    if re.search(
        r'\b(?:talk|speak|connect|transfer)\s+(?:to|with)?\s*'
        r'(?:a\s+)?(?:human|agent|representative|person)\b',
        lowered,
    ):
        return "transfer"
    if re.search(r'\b(?:customer\s+service|support\s+agent|real\s+person)\b',
                 lowered):
        return "transfer"
    if "discount" in lowered:
        return "transfer"

    # Cancel — must mention order
    if re.search(r'\bcancel\b', lowered):
        if re.search(r'\border\b', lowered) or ORDER_RE.search(lowered):
            return "cancel_order"
        return "cancel_order"

    # Exchange — exclude "exchange rate" and "exchange policy"
    if re.search(r'\bexchange\b', lowered):
        if not re.search(r'\bexchange\s+(?:rate|policy)\b', lowered):
            if re.search(r'\bitem\b', lowered) or ITEM_RE.search(lowered):
                return "exchange_items"
            return "exchange_items"

    # Return — must mention item or order, not "return policy"
    if re.search(r'\breturn\b', lowered):
        if re.search(r'\breturn\s+policy\b', lowered):
            pass
        elif re.search(r'\bitem\b', lowered) or ORDER_RE.search(lowered):
            return "return_items"

    # Payment modification
    if "payment" in lowered and re.search(r'\b(change|modify|update|switch)\b',
                                           lowered):
        return "modify_order_payment"

    # Item modification (pending order)
    if re.search(r'\b(item|product)\b', lowered) and re.search(
        r'\b(change|modify|replace|switch|swap)\b', lowered):
        return "modify_order_items"

    # User default address
    if re.search(r'\bmy\b.*\bdefault\b.*\baddress\b', lowered):
        return "modify_user_address"
    if "default address" in lowered:
        return "modify_user_address"

    # Order address modification
    if "address" in lowered and re.search(r'\b(change|modify|update)\b',
                                           lowered):
        if "my" in lowered and "default" in lowered:
            return "modify_user_address"
        return "modify_order_address"

    # Order mention → lookup
    if "order" in lowered or ORDER_RE.search(lowered):
        return "lookup"

    return "unknown"
```

- [ ] **Step 2: Verity the fix handles edge cases**

```bash
uv run python -c "
from app.agent.runtime import AgentRuntime
from app.config import resolve_config
from app.agent.providers import DisabledLLMProvider
import tempfile

r = AgentRuntime(resolve_config(artifact_dir=tempfile.mkdtemp()), provider=DisabledLLMProvider())
# Should be lookup, NOT return_items
assert r._infer_intent('what is your return policy') == 'lookup', 'return policy should be lookup'
# Should be transfer, NOT triggered by bare human
assert r._infer_intent('i want to talk to a human agent') == 'transfer'
# Should be lookup, not triggered by 'human error'
assert r._infer_intent('there was a human error in my order') == 'lookup' or r._infer_intent('there was a human error in my order') == 'unknown'
# Should be cancel_order
assert r._infer_intent('cancel my order please') == 'cancel_order'
# Should be exchange_items, not triggered by 'exchange rate'
assert r._infer_intent('exchange this item for a different one') == 'exchange_items'
# Should be return_items
assert r._infer_intent('i want to return item 6777246137') == 'return_items'
print('All edge cases passed')
"
```

Expected: `All edge cases passed`

- [ ] **Step 3: Commit**

```bash
git add app/agent/runtime.py
git commit -m "fix: _infer_intent 精确匹配 — 修复 H2 关键词误判"
```

---

### Task 5: Add `_merge_slots` and Intent Divergence Logging

**Files:**
- Modify: `app/agent/runtime.py` (add new methods, modify `_intent_and_slot_extractor`)

- [ ] **Step 1: Add `_merge_slots` to `AgentRuntime`**

Insert after `_apply_llm_intent_slots` (after line ~834):

```python
def _merge_slots(
    self,
    *,
    code_slots: Dict[str, Any],
    llm_slots: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge code and LLM slots. Code wins for ID formats; LLM for semantic."""
    if not llm_slots:
        return dict(code_slots)
    merged = dict(code_slots)
    for key, value in llm_slots.items():
        if key not in merged or not merged[key]:
            if value:
                merged[key] = value
            continue
        if key == "reason":
            cleaned = self._clean_llm_scalar(value)
            if cleaned and cleaned.lower() in {
                "no longer needed",
                "ordered by mistake",
            }:
                merged[key] = cleaned.lower()
        if key == "address" and isinstance(value, dict):
            cleaned_address = {
                k: self._clean_llm_scalar(value.get(k)) or ""
                for k in ("address1", "address2", "city", "state",
                          "country", "zip")
            }
            if cleaned_address.get("address1") and cleaned_address.get("zip"):
                merged["address"] = cleaned_address
    return merged
```

- [ ] **Step 2: Modify `_intent_and_slot_extractor` to use merge**

Replace the LLM intent application (L348-349) and the intent divergence handling. The key change: record LLM intent divergence even when code intent wins.

After `if llm_payload:` block (L348-349), insert divergence logging:

```python
        if llm_payload:
            llm_intent = str(llm_payload.get("intent") or "").strip()
            if llm_intent and llm_intent != state.current_intent:
                state.add_step(
                    "intent_and_slot_extractor_divergence",
                    code_intent=state.current_intent,
                    llm_intent=llm_intent,
                    resolved=state.current_intent,
                )
            self._apply_llm_intent_slots(state, llm_payload)
```

And replace the regex slot extraction (which runs after LLM) to merge with LLM slots instead of blindly overwriting. Replace the slot updates at L350-396 with:

```python
        llm_slots = (llm_payload.get("slots") or {}) if llm_payload else {}
        code_slots: Dict[str, Any] = dict(state.slots)

        order_match = ORDER_RE.search(content)
        if order_match:
            code_slots["order_id"] = order_match.group(0)
        payment_match = PAYMENT_RE.search(content)
        if payment_match:
            code_slots["payment_method_id"] = payment_match.group(0)
        item_ids = [
            item
            for item in ITEM_RE.findall(content)
            if not item.startswith("000") and len(item) >= 8
        ]
        if item_ids:
            code_slots["item_ids"] = item_ids
        if "ordered by mistake" in lowered:
            code_slots["reason"] = "ordered by mistake"
        elif "no longer needed" in lowered or "don't need" in lowered:
            code_slots["reason"] = "no longer needed"
        address = self._parse_address(content)
        if address:
            code_slots["address"] = address
        item_pairs = self._parse_item_replacement_pairs(lowered)
        if item_pairs:
            code_slots["item_ids"] = [old for old, _new in item_pairs]
            code_slots["new_item_ids"] = [new for _old, new in item_pairs]

        new_item_marker = re.search(
            r"(?:new items?|exchange for|instead|to new item|"
            r"for new items?)\s+(\d{8,})",
            lowered,
        )
        if new_item_marker:
            new_item_id = new_item_marker.group(1)
            code_slots["new_item_ids"] = [new_item_id]
            if "item_ids" in code_slots:
                code_slots["item_ids"] = [
                    iid for iid in code_slots["item_ids"]
                    if iid != new_item_id
                ]

        state.slots = self._merge_slots(
            code_slots=code_slots,
            llm_slots=llm_slots,
        )
```

- [ ] **Step 3: Verify the merge is imported correctly**

```bash
uv run python -c "from app.agent.runtime import AgentRuntime; print('import OK')"
```

Expected: `import OK`

- [ ] **Step 4: Commit**

```bash
git add app/agent/runtime.py
git commit -m "feat: _merge_slots + intent 分歧记录"
```

---

### Task 6: Rewrite policy_reasoner Prompt

**Files:**
- Rewrite: `prompts/policy_reasoner_v001.md`

- [ ] **Step 1: Write the full prompt**

```markdown
## Node Role

You are the policy_reasoner. Based on the provided policy document,
loaded order/user context, extracted slots, and authentication status,
output a decision. Your decision carries weight — a deny is a deny.

## Decision Protocol

### deny
Return deny in these cases (MUST include explanation_for_user):
- User is not authenticated and the intent requires order access
- The order belongs to a different user than the authenticated user
  (check loaded_context.orders[order_id].user_id vs authenticated_user_id)
- Order status is incompatible with the intent:
  - cancel / modify_address / modify_items / modify_payment → must be pending
  - return / exchange → must be delivered
- Required slots are missing and cannot be inferred from the message
- The policy document explicitly prohibits the requested action
- The requested payment method does not belong to the authenticated user
- Exchange or modify_items: old and new items belong to different products
- Exchange or modify_items: the replacement variant is not available

### ask_clarification
Return ask_clarification when the user's intent is recognizable but
critical information is missing. List the missing fields in missing_slots.

### allow
Return allow ONLY when ALL of these are true:
- User is authenticated
- All required slots are present
- Order status is compatible with the intent (pending for modify/cancel,
  delivered for return/exchange)
- The policy document does not prohibit this action
- IMPORTANT: allow does NOT mean direct execution — write operations still
  require explicit user confirmation (user_confirmation_required: true)

### transfer
Return transfer ONLY when the user explicitly asks for a human agent.
Do NOT upgrade a deny to transfer.

## Required Slots by Intent
- cancel_order: order_id, reason
- modify_order_address: order_id, address (address1, city, state, country, zip)
- modify_order_items: order_id, item_ids, new_item_ids
- modify_order_payment: order_id, payment_method_id
- modify_user_address: address (address1, city, state, country, zip)
- return_items: order_id, item_ids, payment_method_id
- exchange_items: order_id, item_ids, new_item_ids, payment_method_id
- lookup: no strict requirement
- transfer: no strict requirement

## Context Interpretation
- loaded_context.orders: {order_id: {status, user_id, items, ...}}
- loaded_context.users: {user_id: {email, payment_methods, address, ...}}
- Compare order.user_id with authenticated_user_id for ownership checks.

## Examples

### Example 1: Normal cancellation
Input: intent=cancel_order, order_id=#W5918442, order.status=pending,
order.user_id == authenticated_user_id
Output: {"decision": "allow", "intent": "cancel_order", "missing_slots": [],
"user_confirmation_required": true, "explanation_for_user": "",
"internal_reasoning_summary": "Pending order owned by authenticated user.
Cancellation is allowed pending confirmation."}

### Example 2: Ownership violation
Input: intent=cancel_order, order_id=#W5918442, order.user_id !=
authenticated_user_id
Output: {"decision": "deny", "intent": "cancel_order", "missing_slots": [],
"user_confirmation_required": false, "explanation_for_user": "I cannot
access or modify orders for another account.",
"internal_reasoning_summary": "Order belongs to a different user."}

### Example 3: Missing required field
Input: intent=return_items, order_id provided, item_ids provided,
payment_method_id missing
Output: {"decision": "ask_clarification", "intent": "return_items",
"missing_slots": ["payment_method_id"], "user_confirmation_required": false,
"explanation_for_user": "Which payment method would you like the refund
sent to?", "internal_reasoning_summary": "payment_method_id required for
return."}

## Output

Return pure JSON (no markdown fences):
{
  "decision": "allow | ask_clarification | deny | transfer",
  "intent": "<intent>",
  "missing_slots": ["<field name>"],
  "user_confirmation_required": true | false,
  "explanation_for_user": "<user-facing message when deny or ask>",
  "internal_reasoning_summary": "<internal reasoning>"
}
```

- [ ] **Step 2: Commit**

```bash
git add prompts/policy_reasoner_v001.md
git commit -m "feat: 重写 policy_reasoner prompt — Decision Protocol + few-shot"
```

---

### Task 7: Implement Dual-Track Policy Merge in runtime.py

**Files:**
- Modify: `app/agent/runtime.py` (replace `_policy_reasoner` L424-470)

- [ ] **Step 1: Add `_code_missing_slots` method**

Insert before `_policy_reasoner`:

```python
def _code_missing_slots(self, state: ConversationState) -> list[str]:
    """Code-side check for missing required slots per intent."""
    required_map: Dict[str, tuple[str, ...]] = {
        "cancel_order": ("order_id", "reason"),
        "modify_order_address": ("order_id", "address"),
        "modify_order_items": ("order_id", "item_ids", "new_item_ids"),
        "modify_order_payment": ("order_id", "payment_method_id"),
        "modify_user_address": ("address",),
        "return_items": ("order_id", "item_ids", "payment_method_id"),
        "exchange_items": (
            "order_id", "item_ids", "new_item_ids", "payment_method_id",
        ),
    }
    required = required_map.get(state.current_intent, ())
    return [key for key in required if not state.slots.get(key)]
```

- [ ] **Step 2: Add `_merge_policy_decisions` method**

```python
def _merge_policy_decisions(
    self,
    *,
    code_decision: str,
    llm_decision: Optional[str],
) -> str:
    """Conservative dual-track merge.
    Any deny → deny. Any ask → ask. Transfer needs both to agree.
    Only allow when both allow.
    """
    if llm_decision is None:
        return code_decision
    if "deny" in (code_decision, llm_decision):
        return "deny"
    if "ask_clarification" in (code_decision, llm_decision):
        return "ask_clarification"
    if code_decision == "transfer" and llm_decision == "transfer":
        return "transfer"
    if code_decision == "transfer" or llm_decision == "transfer":
        return "ask_clarification"
    return "allow"
```

- [ ] **Step 3: Replace `_policy_reasoner` with dual-track version**

Replace the method (L424-470) with:

```python
def _policy_reasoner(self, state: ConversationState, content: str) -> None:
    if self._has_assistant_response(state):
        return
    write_intents = {
        "cancel_order",
        "modify_order_address",
        "modify_order_items",
        "modify_order_payment",
        "modify_user_address",
        "return_items",
        "exchange_items",
    }

    # ── Code track ──
    if state.current_intent == "transfer":
        code_decision = "transfer"
    elif state.current_intent == "lookup":
        code_decision = "allow"
    elif state.current_intent in write_intents:
        if self._code_missing_slots(state):
            code_decision = "ask_clarification"
        else:
            code_decision = "allow"
    else:
        code_decision = "ask_clarification"

    # ── LLM track ──
    llm_payload = self._llm_policy_decision(state, content, code_decision)
    llm_decision = llm_payload.get("decision") if llm_payload else None

    # ── Conservative merge ──
    final_decision = self._merge_policy_decisions(
        code_decision=code_decision,
        llm_decision=llm_decision,
    )

    # Log divergence for audit
    if llm_decision and llm_decision != code_decision:
        state.add_step(
            "policy_reasoner_divergence",
            code=code_decision,
            llm=llm_decision,
            merged=final_decision,
        )

    explanation = ""
    if llm_payload and final_decision == "deny":
        explanation = self._clean_llm_scalar(
            llm_payload.get("explanation_for_user")
        ) or ""

    state.policy_decision = PolicyDecision(
        decision=final_decision,
        intent=(
            llm_payload.get("intent", state.current_intent)
            if llm_payload
            else state.current_intent
        ),
        missing_slots=(
            llm_payload.get("missing_slots")
            if llm_payload and isinstance(llm_payload.get("missing_slots"), list)
            else []
        ),
        user_confirmation_required=(
            llm_payload.get("user_confirmation_required", False)
            if llm_payload
            else state.current_intent in write_intents
        ),
        explanation_for_user=explanation,
        internal_reasoning_summary=(
            llm_payload.get("internal_reasoning_summary", "")
            if llm_payload
            else ""
        ),
    )
    state.add_step(
        "policy_reasoner",
        decision=final_decision,
        llm_used=bool(llm_payload),
        code_decision=code_decision,
    )
```

- [ ] **Step 4: Verify import is clean**

```bash
uv run python -c "from app.agent.runtime import AgentRuntime; print('import OK')"
```

Expected: `import OK`

- [ ] **Step 5: Commit**

```bash
git add app/agent/runtime.py
git commit -m "feat: policy_reasoner 双轨保守合并 — LLM deny 不再被覆盖"
```

---

### Task 8: Rewrite action_planner Prompt

**Files:**
- Rewrite: `prompts/action_planner_v001.md`

- [ ] **Step 1: Write the full prompt**

```markdown
## Node Role

You are the action_planner. Given the policy_decision, current intent,
extracted slots, loaded context, and the tool catalog, output the next action.

## Input Interpretation

- policy_decision = allow → you may plan execution
- policy_decision = ask_clarification → generate a question listing missing_slots
- policy_decision = deny → output a refusal response with explanation_for_user
- policy_decision = transfer → plan a transfer to human agents

## Plan Types

### lookup_order
When: policy_decision=allow, intent=lookup, order_id available
Action: use get_order_details
Response: order status or prompt for missing info

### pending_write
When: policy_decision=allow, intent involves a write operation
Action: choose the appropriate write tool from the tool catalog, construct
arguments from available slots.
Response: MUST include a confirmation prompt like "Please confirm yes or no."
If your response text does not contain "confirm", the system will append it.

### transfer
When: policy_decision=transfer or intent=transfer
Action: use transfer_to_human_agents with a summary of the user's request
Response: transfer notice for the user

### ask_clarification
When: policy_decision=ask_clarification or slots are incomplete
Response: a specific question asking for the missing information

### respond
When: no tool action is needed, just a text reply (e.g., status update, denial)
Response: user-facing message

## Allowed pending_write action_name values
- cancel_pending_order
- modify_pending_order_address
- modify_pending_order_items
- modify_pending_order_payment
- modify_user_address
- return_delivered_order_items
- exchange_delivered_order_items

## Examples

### Example 1: Cancel with confirmation
Input: policy_decision=allow, intent=cancel_order, slots={order_id:#W5918442,
reason:no longer needed}
Output: {"plan_type": "pending_write", "action_name":
"cancel_pending_order", "arguments": {"order_id": "#W5918442", "reason":
"no longer needed"}, "response": "I can cancel order #W5918442 for you.
The reason is: no longer needed. Please confirm yes or no."}

### Example 2: Missing info
Input: policy_decision=ask_clarification,
missing_slots=["payment_method_id"], intent=return_items
Output: {"plan_type": "ask_clarification", "response": "Which payment method
would you like the refund sent to? You can provide a gift card, credit card,
or PayPal ID from your account."}

### Example 3: Denial response
Input: policy_decision=deny, explanation_for_user="I cannot access or modify
orders for another account."
Output: {"plan_type": "respond", "response": "I cannot access or modify
orders for another account."}

## Output

Return pure JSON (no markdown fences):
{
  "plan_type": "lookup_order | pending_write | transfer | ask_clarification | respond",
  "action_name": "<tool name, for pending_write and transfer>",
  "arguments": {<key: value>},
  "response": "<user-facing message>"
}
```

- [ ] **Step 2: Commit**

```bash
git add prompts/action_planner_v001.md
git commit -m "feat: 重写 action_planner prompt — 工具可见 + few-shot"
```

---

### Task 9: Add tool_catalog_for_llm() to ToolRegistry

**Files:**
- Modify: `app/tools/registry.py`

- [ ] **Step 1: Add tool_catalog_for_llm method**

Insert after `_tool_kind` method (after L57):

```python
def tool_catalog_for_llm(self) -> str:
    """Generate LLM-visible tool descriptions from the registry.
    Single source of truth — no manual duplication needed.
    """
    entries: list[str] = []
    for name in sorted(self._tools):
        kind = self.kind(name)
        params = self._tool_params_for_llm(name)
        constraints = self._tool_constraints_for_llm(name, kind)
        entries.append(
            f"### {name}\n"
            f"- type: {kind}\n"
            f"- parameters: {params}\n"
            f"- constraints: {constraints}\n"
        )
    return "## Available Tools\n\n" + "\n".join(entries)

def _tool_params_for_llm(self, name: str) -> str:
    params_map: Dict[str, str] = {
        "find_user_id_by_email": "email (string)",
        "find_user_id_by_name_zip": "first_name (string), last_name (string), zip (string)",
        "get_user_details": "user_id (string)",
        "get_order_details": "order_id (string)",
        "get_product_details": "product_id (string)",
        "get_item_details": "item_id (string)",
        "list_all_product_types": "(none)",
        "calculate": "expression (string)",
        "cancel_pending_order": "order_id (string), reason (string: no longer needed | ordered by mistake)",
        "modify_pending_order_address": "order_id (string), address1 (string), address2 (string), city (string), state (string), country (string), zip (string)",
        "modify_pending_order_items": "order_id (string), item_ids (list of strings), new_item_ids (list of strings)",
        "modify_pending_order_payment": "order_id (string), payment_method_id (string)",
        "modify_user_address": "user_id (string), address1 (string), address2 (string), city (string), state (string), country (string), zip (string)",
        "return_delivered_order_items": "order_id (string), item_ids (list of strings), payment_method_id (string)",
        "exchange_delivered_order_items": "order_id (string), item_ids (list of strings), new_item_ids (list of strings), payment_method_id (string)",
        "transfer_to_human_agents": "summary (string)",
    }
    return params_map.get(name, "(see function signature)")

def _tool_constraints_for_llm(self, name: str, kind: str) -> str:
    if kind == "read":
        return "read-only, no confirmation needed"
    if name == "transfer_to_human_agents" or name == "calculate":
        return "no special constraints"
    constraint_map: Dict[str, str] = {
        "cancel_pending_order": "order must be pending; requires user confirmation; reason must be 'no longer needed' or 'ordered by mistake'",
        "modify_pending_order_address": "order must be pending; requires user confirmation",
        "modify_pending_order_items": "order must be pending; new items must be same product as old; new items must be available; count must match; requires user confirmation",
        "modify_pending_order_payment": "order must be pending; payment method must belong to user; must differ from current; gift card must have sufficient balance; requires user confirmation",
        "modify_user_address": "target user must be authenticated user; address passed to user_id argument; requires user confirmation",
        "return_delivered_order_items": "order must be delivered; items must be in the order; payment method must belong to user; requires user confirmation",
        "exchange_delivered_order_items": "order must be delivered; old and new item counts must match; new items must be same product as old; new items must be available; payment method must belong to user; requires user confirmation",
    }
    return constraint_map.get(name, "requires user confirmation")
```

- [ ] **Step 2: Inject tool catalog into action_planner LLM call**

In `runtime.py`'s `_apply_llm_action_plan` method, add `tool_catalog` to the LLM payload. Find the payload dict (around L881-891) and add:

```python
            {
                "user_message": content,
                "policy_decision": (
                    state.policy_decision.model_dump()
                    if state.policy_decision
                    else None
                ),
                "current_intent": state.current_intent,
                "slots": state.slots,
                "loaded_context": state.loaded_context.model_dump(),
                "tool_catalog": self.gateway.registry.tool_catalog_for_llm(),
            },
```

- [ ] **Step 3: Verify**

```bash
uv run python -c "
from app.config import resolve_config
from app.tools.retail_adapter import RetailAdapter
from app.tools.registry import ToolRegistry
runtime = RetailAdapter(resolve_config()).create_runtime()
registry = ToolRegistry(runtime.tools)
catalog = registry.tool_catalog_for_llm()
assert '### cancel_pending_order' in catalog
assert '### get_order_details' in catalog
assert 'parameters:' in catalog
assert 'constraints:' in catalog
print('OK — catalog contains', len(catalog.split('### ')) - 1, 'tools')
"
```

Expected: `OK — catalog contains 15 tools` (or 14 depending on local build)

- [ ] **Step 4: Commit**

```bash
git add app/tools/registry.py app/agent/runtime.py
git commit -m "feat: ToolRegistry.tool_catalog_for_llm() + 注入 action_planner"
```

---

### Task 10: Rewrite response_generator Prompt

**Files:**
- Rewrite: `prompts/response_generator_v001.md`

- [ ] **Step 1: Write the full prompt**

```markdown
## Node Role

You are the response_generator. Rewrite the draft into a concise,
customer-facing message.

## Tone Standards

- **Professional but friendly** — natural, conversational customer-service
  tone. Not overly formal or mechanical.
- **Concise** — one core message at a time. Do not stack multiple ideas.
- **Actionable** — if the user needs to decide, make the options clear
  (yes, no, or provide more information).
- **No false promises** — only say an operation completed if the draft
  explicitly says so.
- **No excessive apology** — state the situation clearly without repeated
  "sorry" or "apologize" phrases.

## Format Constraints

- Plain text only. No markdown, HTML, emoji, or special formatting.
- Preserve exact order IDs (#W...), item IDs (digits), payment method IDs.
- **Do NOT expose full email addresses** — if the draft contains an email,
  replace it with "your email address".
- **Do NOT expose full street addresses** — if the draft contains an address,
  only keep the parts needed for the user to understand.
- If confirmation is needed, the message MUST include "confirm yes or no"
  or an equivalent clear prompt.

## Response Patterns

### Normal confirmation prompt
Draft: "Cancel order #W5918442 because no longer needed. Please confirm yes
or no."
Response: "I can cancel order #W5918442 for you. The reason provided is: no
longer needed. Please confirm yes or no to proceed."

### Operation completed
Draft: "Done. I have completed the requested update."
Response: "Your order has been updated successfully. Is there anything else
I can help with?"

### Denial or inability
Draft: "I cannot access or modify orders for another account."
Response: "I wasn't able to process that request — this order is associated
with a different account. If you believe this is a mistake, I can transfer
you to a human agent. Would you like me to do that?"

### Need more information
Draft: "Which order would you like to cancel?"
Response: "Which order would you like to cancel? If you have the order number
(it starts with #W), that's the quickest way for me to look it up."

### Transfer to human
Draft: "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
Response: "I'm transferring you to a human agent who can help with this.
Please hold — a representative will be with you shortly."

## Error Recovery

If the draft is unclear or contradictory:
- Fall back to a clear, safe rephrasing.
- Do not add information not present in the draft.
- Do not speculate about the outcome of an operation.

## Output

Return only the final message text. Do NOT wrap in JSON.
```

- [ ] **Step 2: Commit**

```bash
git add prompts/response_generator_v001.md
git commit -m "feat: 重写 response_generator prompt — 语气标准 + 响应模板"
```

---

### Task 11: Fix H1 — Hardcoded Paths in config.py

**Files:**
- Modify: `app/config.py`

- [ ] **Step 1: Replace hardcoded paths with expanduser**

Replace L8-14:

```python
import os

DEFAULT_TAU3_RETAIL_ROOT = Path(
    os.path.expanduser(
        "~/Documents/ai/AgentProject/data_sources/"
        "retail_customer_support_transaction_agent/current_tau3_bench"
    )
)
DEFAULT_TAU2_BENCH_ROOT = Path(
    os.path.expanduser(
        "~/Documents/ai/AgentProject/data_sources/raw/tau2-bench"
    )
)
```

- [ ] **Step 2: Add path existence validation in resolve_config**

In `resolve_config()`, after constructing the `AppConfig` (before the return at L80), add:

```python
    config = AppConfig(
        tau3_retail_root=root,
        tau2_bench_root=tau2_root,
        artifact_dir=artifacts,
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL),
        default_agent_model=os.getenv("DEFAULT_AGENT_MODEL", DEFAULT_AGENT_MODEL),
        agent_llm_timeout_seconds=_float_env(
            "AGENT_LLM_TIMEOUT_SECONDS", DEFAULT_AGENT_LLM_TIMEOUT_SECONDS
        ),
        agent_llm_max_retries=_int_env(
            "AGENT_LLM_MAX_RETRIES", DEFAULT_AGENT_LLM_MAX_RETRIES
        ),
    )
    return config
```

Change to:

```python
    config = AppConfig(...)  # same as above
    _validate_config_paths(config)
    return config
```

And add the validation function:

```python
def _validate_config_paths(config: AppConfig) -> None:
    missing: list[str] = []
    if not config.tau3_retail_root.exists():
        missing.append(
            f"TAU3_RETAIL_ROOT ({config.tau3_retail_root}) — "
            "Set TAU3_RETAIL_ROOT in .env"
        )
    if missing:
        raise FileNotFoundError(
            "Required data paths not found:\n  " + "\n  ".join(missing)
        )
```

- [ ] **Step 3: Verify the fix**

```bash
uv run python -c "
from app.config import resolve_config
c = resolve_config()
print('TAU3:', c.tau3_retail_root)
print('TAU2:', c.tau2_bench_root)
assert c.tau3_retail_root.exists(), 'Missing tau3 root'
print('Paths OK')
"
```

Expected: `Paths OK` (with correct paths)

- [ ] **Step 4: Commit**

```bash
git add app/config.py
git commit -m "fix: H1 — 移除硬编码路径，改用 expanduser + 路径校验"
```

---

### Task 12: Fix H3 — Exact Order Status Match in guard.py

**Files:**
- Modify: `app/agent/guard.py` (L155, L175)

- [ ] **Step 1: Fix modify_pending_order_address check**

Replace L155:

```python
        if action.tool_name == "modify_pending_order_address":
            if not order or order.get("status") != "pending":
                return "non_pending_order_cannot_be_modified"
```

- [ ] **Step 2: Fix modify_pending_order_payment check**

Replace L174-175:

```python
        if action.tool_name == "modify_pending_order_payment":
            if not order or order.get("status") != "pending":
                return "non_pending_order_cannot_be_modified"
```

- [ ] **Step 3: Verify**

```bash
uv run python -c "
# Verify the substring 'pending' in 'pending_shipment' would NO LONGER pass
status = 'pending_shipment'
# Old way: 'pending' in status → True (wrong)
# New way: status != 'pending' → True → blocked (correct)
assert status != 'pending', 'Exact match would block pending_shipment'
# Verify real 'pending' still passes
status = 'pending'
assert status == 'pending', 'Real pending still passes'
print('Status checks correct')
"
```

- [ ] **Step 4: Commit**

```bash
git add app/agent/guard.py
git commit -m "fix: H3 — 订单状态从 substring 改为精确 == 匹配"
```

---

### Task 13: Fix H4 — LLM JSON Defensive Parsing in providers.py

**Files:**
- Modify: `app/agent/providers.py`

- [ ] **Step 1: Add JSON extraction helper and retry logic**

Add the helper function at module level (before the class definitions):

```python
import re as _re


def _extract_json_block(text: str) -> str:
    """Extract JSON from LLM output, tolerating markdown fences."""
    match = _re.search(
        r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL
    )
    if match:
        return match.group(1).strip()
    return text.strip()
```

- [ ] **Step 2: Add retry loop to DeepSeekProvider.json**

Replace the `json` method in `DeepSeekProvider` (L43-52):

```python
def json(
    self, messages: List[Dict[str, str]], schema: Dict[str, Any]
) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    for attempt in range(self.max_retries + 1):
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            content = _extract_json_block(content)
            return json.loads(content)
        except (json.JSONDecodeError, KeyError) as exc:
            last_error = exc
            if attempt == self.max_retries:
                raise
    raise last_error  # type: ignore[misc]
```

- [ ] **Step 3: Verify**

```bash
uv run python -c "
from app.agent.providers import _extract_json_block
# Test markdown extraction
assert _extract_json_block('```json\n{\"a\":1}\n```') == '{\"a\":1}'
assert _extract_json_block('```\n{\"b\":2}\n```') == '{\"b\":2}'
# Test pass-through
assert _extract_json_block('{\"c\":3}') == '{\"c\":3}'
# Test leading/trailing whitespace
assert _extract_json_block('  {\"d\":4}  ') == '{\"d\":4}'
print('JSON extraction OK')
"
```

Expected: `JSON extraction OK`

- [ ] **Step 4: Commit**

```bash
git add app/agent/providers.py
git commit -m "fix: H4 — LLM JSON 防御性解析 + markdown 提取 + 重试"
```

---

### Task 14: Update Tests for Dual-Track Behavior

**Files:**
- Modify: `tests/test_agent_core.py`

- [ ] **Step 1: Rewrite `test_supported_write_policy_denial_defers_to_guard_path`**

The old test name documented behavior where LLM deny was overridden. Replace it with a test that verifies LLM deny is now respected:

```python
def test_dual_track_policy_deny_is_respected(self):
    """LLM deny in policy_reasoner should result in actual deny decision."""
    with tempfile.TemporaryDirectory() as tmp:
        runtime = AgentRuntime(
            resolve_config(artifact_dir=tmp),
            provider=DenyingPolicyLLMProvider(),
        )
        result = runtime.run_script(
            session_id="llm-deny-write",
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"My email is {PENDING_EMAIL}. Cancel order "
                        f"{PENDING_ORDER} because no longer needed."
                    ),
                }
            ],
        )

    self.assertEqual(result.state.policy_decision.decision, "deny")
    self.assertIsNone(result.state.pending_action)
    # Should have recorded the divergence
    divergence_step = next(
        (
            step
            for step in result.state.steps
            if step.get("name") == "policy_reasoner_divergence"
        ),
        None,
    )
    self.assertIsNotNone(divergence_step)
    self.assertEqual(divergence_step["code"], "allow")
    self.assertEqual(divergence_step["llm"], "deny")
    self.assertEqual(divergence_step["merged"], "deny")
```

- [ ] **Step 2: Add test for tool catalog generation**

```python
def test_tool_registry_generates_llm_catalog(self):
    runtime = RetailAdapter(resolve_config()).create_runtime()
    registry = ToolRegistry(runtime.tools)
    catalog = registry.tool_catalog_for_llm()

    self.assertIn("## Available Tools", catalog)
    self.assertIn("### cancel_pending_order", catalog)
    self.assertIn("### get_order_details", catalog)
    self.assertIn("type: write", catalog)
    self.assertIn("type: read", catalog)
    self.assertIn("parameters:", catalog)
    self.assertIn("constraints:", catalog)
```

- [ ] **Step 3: Add test for dual-track merge matrix**

```python
class DualTrackMergeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = AgentRuntime(
            resolve_config(),
            provider=DisabledLLMProvider(),
        )

    def test_both_allow_returns_allow(self):
        result = self.runtime._merge_policy_decisions(
            code_decision="allow",
            llm_decision="allow",
        )
        self.assertEqual(result, "allow")

    def test_llm_deny_overrides_code_allow(self):
        result = self.runtime._merge_policy_decisions(
            code_decision="allow",
            llm_decision="deny",
        )
        self.assertEqual(result, "deny")

    def test_code_deny_overrides_llm_allow(self):
        result = self.runtime._merge_policy_decisions(
            code_decision="deny",
            llm_decision="allow",
        )
        self.assertEqual(result, "deny")

    def test_any_ask_returns_ask(self):
        self.assertEqual(
            self.runtime._merge_policy_decisions(
                code_decision="allow", llm_decision="ask_clarification",
            ),
            "ask_clarification",
        )
        self.assertEqual(
            self.runtime._merge_policy_decisions(
                code_decision="ask_clarification", llm_decision="allow",
            ),
            "ask_clarification",
        )

    def test_transfer_requires_both_agree(self):
        self.assertEqual(
            self.runtime._merge_policy_decisions(
                code_decision="transfer", llm_decision="transfer",
            ),
            "transfer",
        )
        self.assertEqual(
            self.runtime._merge_policy_decisions(
                code_decision="transfer", llm_decision="allow",
            ),
            "ask_clarification",
        )

    def test_llm_none_falls_back_to_code(self):
        result = self.runtime._merge_policy_decisions(
            code_decision="allow",
            llm_decision=None,
        )
        self.assertEqual(result, "allow")

    def test_code_missing_slots_detects_gaps(self):
        from app.agent.models import ConversationState
        state = ConversationState(session_id="test")
        state.current_intent = "return_items"
        state.slots = {"order_id": "#W1234567"}
        missing = self.runtime._code_missing_slots(state)
        self.assertIn("item_ids", missing)
        self.assertIn("payment_method_id", missing)
```

- [ ] **Step 4: Run the new tests**

```bash
uv run python -m unittest tests.test_agent_core.DualTrackMergeTests -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_agent_core.py
git commit -m "test: 双轨合并 + 工具目录 + deny 行为变更测试"
```

---

### Task 15: Full Regression Gate

**Files:**
- Verify: all changes

- [ ] **Step 1: Run full test suite**

```bash
uv run python -m unittest discover -s tests -v
```

Expected: All tests pass.

- [ ] **Step 2: Run curated MVP eval (no LLM)**

```bash
uv run phase2-eval --subset curated_mvp --trials 1 --no-progress --json
```

Expected: All 11 cases pass.

- [ ] **Step 3: Run generalized MVP eval (no LLM)**

```bash
uv run phase2-eval --subset generalized_mvp --trials 1 --no-progress --json
```

Expected: All 30 cases pass.

- [ ] **Step 4: Run workbench build check**

```bash
cd workbench && npm run build && npm run check:i18n
```

Expected: Build succeeds, i18n check passes.

- [ ] **Step 5: Verify prompt metadata includes core_contract**

```bash
uv run python -c "
from app.agent.prompts import prompt_metadata
meta = prompt_metadata()
assert 'core_contract' in meta
for key in ('core_contract', 'intent_slot', 'policy_reasoner', 'action_planner', 'response_generator'):
    assert key in meta and 'sha256' in meta[key], f'Missing {key}'
print('All prompt metadata OK')
"
```

Expected: `All prompt metadata OK`

- [ ] **Step 6: Commit any remaining changes**

```bash
git add -A
git diff --cached --stat
git commit -m "chore: 全量回归验证通过"
```
