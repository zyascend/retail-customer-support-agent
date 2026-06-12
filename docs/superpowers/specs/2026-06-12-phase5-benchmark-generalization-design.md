# Phase 5 Benchmark Generalization And Agent Capability Design

Date: 2026-06-12

## Context

The project currently has a working guarded retail support agent, curated eval
runner, static dashboard, and local workbench. The deterministic path passes the
existing `curated_mvp` subset, but the agent is still closer to a curated demo
than a broadly capable retail benchmark agent.

Phase 5 will move the project from a narrow MVP toward benchmark-grade coverage
by pairing two goals:

- Fill the most important retail transaction capability gaps.
- Expand deterministic eval from 11 curated cases to an approximately 30-case
  generalized subset.

This phase is intentionally a bridge toward full tau retail benchmark ingestion,
not the full ingestion effort itself.

## Decision Summary

Use a capability-matrix-first approach.

Phase 5 will:

- Create a capability matrix linking intents, slots, tools, guard rules, and
  eval cases.
- Keep `curated_mvp` as a regression subset.
- Add a new `generalized_mvp` subset with around 30 deterministic cases.
- Add name plus zip authentication.
- Add agent support for modifying pending order items.
- Add agent support for modifying pending order payment.
- Add agent support for modifying the authenticated user's default address.
- Strengthen multi-item return and exchange handling.
- Strengthen write guard checks for inventory, payment ownership, gift card
  balance, user ownership, and duplicate writes.
- Keep the current trace and workbench contracts mostly stable.

This phase does not add full tau task ingestion, WebSocket streaming,
multi-session persistence, large-scale prompt optimization, CI/CD, or dashboard
redesign.

## Capability Scope

### Authentication

Current behavior primarily supports email authentication.

Phase 5 adds support for authentication by first name, last name, and zip:

- Try email first when an email is present.
- If no email is present, try name plus zip when all required fields are present.
- If authentication fields are incomplete, ask for the missing information.
- Continue to reject direct user id authentication as a valid identity proof.

### Order Modification

Phase 5 adds the missing planning and guard coverage for:

- `modify_pending_order_items`
- `modify_pending_order_payment`

Order item modification must verify:

- The order belongs to the authenticated user.
- The order is pending.
- The original item ids are in the order.
- The replacement item ids exist.
- Each replacement item belongs to the same product as the original item.
- Each replacement item is available.
- Old and new item counts match.

Payment modification must verify:

- The order belongs to the authenticated user.
- The order is pending or policy-allowed pending-like status.
- The payment method belongs to the authenticated user.
- The payment method is different from the current order payment method.
- Gift card balance is sufficient when a gift card is used.

### User Address Modification

The local tool already contains `modify_user_address`, but the agent planning
path is incomplete.

Phase 5 adds:

- `modify_user_address` intent detection.
- Address slot extraction for user default address changes.
- Pending action creation and confirmation.
- Guard checks that the target user is the authenticated user.
- Read-before-write checks against loaded user context.

The agent must not confuse changing a default user address with changing a
shipping address on an existing order.

### Return And Exchange Enhancements

Current return and exchange coverage focuses on single-item cases.

Phase 5 strengthens:

- Multi-item input parsing.
- Duplicate item count validation.
- Exchange old/new count matching.
- Exchange same-product checks.
- Exchange replacement availability checks.
- Duplicate return/exchange lock conflict prevention.

Complex price difference handling and multi-payment refund explanations are not
Phase 5 acceptance criteria.

### Refusal And Transfer

Phase 5 adds eval coverage for unsupported or out-of-policy requests:

- Explicit human requests still transfer.
- Tool-unsupported business requests transfer when the system cannot fulfill
  them.
- Policy-disallowed transaction requests should be refused or guard-blocked with
  a stable machine-readable reason.

## Eval Design

Phase 5 keeps the existing `curated_mvp` subset unchanged as a regression suite.

Add `generalized_mvp`, approximately 30 cases, containing:

- All existing curated cases or equivalent regression coverage.
- Success cases for every new capability.
- Guard block cases for each high-risk policy area.
- Confirmation confirm, deny, and changed flows for key write actions.
- No-write cases that assert DB hash invariants.
- Wrong-user and wrong-payment ownership cases.
- Unsupported request and transfer cases.

Recommended case categories:

- `auth`
- `lookup`
- `cancel`
- `modify_address`
- `modify_items`
- `modify_payment`
- `modify_user_address`
- `return`
- `exchange`
- `confirmation`
- `guard`
- `transfer`

The eval model should remain deterministic/offline first. LLM-backed eval is
allowed as an exploratory run, but it is not a Phase 5 gate.

### Eval Case Metadata

Extend `EvalCase` only as needed. Candidate fields:

- `capability`
- `policy_area`
- `expected_db_assertions`
- `expected_tool_sequence`

The phase can start with the current expected fields where sufficient. Add new
assertion structure only when single-field expectations become ambiguous, such
as payment changes or user address changes.

## Runtime Design

Keep `AgentRuntime` as the main orchestrator for Phase 5. Avoid broad
architectural rewrites while expanding capabilities.

### Intent Coverage

Add or complete:

- `modify_order_items`
- `modify_order_payment`
- `modify_user_address`

Continue supporting:

- `lookup`
- `cancel_order`
- `modify_order_address`
- `return_items`
- `exchange_items`
- `transfer`
- `unknown`

### Slot Extraction

Extend deterministic extraction for:

- First name, last name, zip.
- Old and new item ids for order item modification.
- Multiple item ids for returns and exchanges.
- Payment method ids.
- User default address changes.

LLM extraction may assist when configured, but deterministic extraction must be
sufficient for `generalized_mvp`.

### Planning

Add planner methods for:

- `_plan_modify_items`
- `_plan_modify_payment`
- `_plan_user_address_change`

All write operations still produce a `PendingAction` and require explicit user
confirmation before reaching the write tool.

### Responses

Add stable user-facing explanations for important guard block reasons without
changing the machine-readable reason values used by eval.

Examples:

- `replacement_item_product_mismatch`
- `replacement_item_unavailable`
- `payment_method_not_owned`
- `gift_card_balance_insufficient`
- `non_pending_order_cannot_be_modified`

## Tool And Guard Design

The write boundary remains `ToolGateway` plus `WriteActionGuard`.

Runtime should understand and plan actions. Guard and tools decide whether writes
are allowed and apply mutations.

### Tool Layer

Add or complete local fallback behavior for:

- `modify_pending_order_items` (new tool implementation)
- `modify_pending_order_payment` (new tool implementation)
- `modify_user_address`: the tool already exists in `retail_adapter.py`; this phase adds runtime intent routing, slot extraction, planner method, and guard integration

Local fallback behavior should mirror tau retail tool behavior where possible.
When tau and local behavior differ, record the difference in tests or docs rather
than silently normalizing it.

### Guard Layer

The guard must enforce:

- Authentication before writes.
- Explicit confirmation before writes.
- Ownership validation.
- Read-before-write.
- Policy validation.
- Resource locks.
- Idempotency keys.
- Audit log entries for successful writes.

Additional policy checks:

- Item replacement same-product and availability.
- Payment method ownership.
- Gift card balance.
- Different payment method requirement.
- User default address ownership.
- Duplicate or conflicting item-level write locks.

Internal block reasons should stay machine-readable. User-facing text should be
derived from those reasons.

## Workbench And Dashboard Impact

Workbench should be updated only enough to expose new demo cases in the case
catalog. Recommended new demo cases:

- Name plus zip authentication.
- Modify pending order item.
- Modify pending order payment.

The workbench layout and API snapshot contract should remain stable.

The Phase 3 dashboard should continue to read Phase 2 report artifacts. No
visual redesign is required.

## Acceptance Criteria

Phase 5 is complete when the following pass:

```bash
uv run python -m unittest discover -s tests
uv run phase2-eval --subset curated_mvp --trials 1 --no-progress --json
uv run phase2-eval --subset generalized_mvp --trials 1 --no-progress --json
cd workbench && npm run build
cd workbench && npm run check:i18n
```

Target metrics:

- `curated_mvp`: 11/11 pass.
- `generalized_mvp`: approximately 30/30 pass.
- `db_accuracy`: 1.0.
- `mutation_error_rate`: 0.0.
- `tool_error_rate`: 0.0.
- Guard block cases leave DB hash unchanged.
- Every successful write has confirmation, audit log, idempotency key, and
  write lock.

## Out Of Scope

Phase 5 does not include:

- Full tau retail train/test ingestion.
- LLM-backed generalized eval as a hard gate.
- Full LangGraph conditional state machine rewrite.
- Persistent DB, SQLite, PostgreSQL, or Redis.
- Multi-user workbench sessions.
- WebSocket streaming.
- Dashboard redesign.
- Full CI/CD setup.
- Broad prompt optimization.

These are good follow-up phases once the generalized deterministic capability
surface is stable.
