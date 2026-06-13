# Retail Customer Support Agent

A 12-node LLM agent for retail customer support with a 7-layer write safety guard and dual-track deterministic + semantic reasoning. Built on tau2-bench retail data, designed to be a portfolio piece demonstrating AI agent engineering — safe writes, intent disambiguation, and full auditability.

> **Demo:** Open `http://localhost:5173` after Quick Start to explore the Workbench with 10 curated demo cases grouped by user journey.

## Problem Statement

Retail customer support agents face three hard challenges:

1. **Safe write operations** — cancelling orders, modifying payments, returning items must not happen accidentally or without authorization. Every write needs explicit confirmation and multi-layer guard checks.
2. **Intent disambiguation** — "I want to change my order" could mean cancel, modify items, modify address, or modify payment. The agent must extract structured intent from unstructured natural language.
3. **Full auditability** — every decision, tool call, and DB mutation must be traceable to a specific policy rule, with before/after hashes and idempotency keys.

This project addresses all three with a deterministic-first, LLM-augmented architecture.

## Architecture Overview

```
receive_message → conversation_gate → identity_resolver → intent_and_slot_extractor
→ context_loader → policy_reasoner → action_planner → write_action_guard
→ tool_executor → observation_reducer → response_generator → run_logger
```

**Dual-track decision**: Every decision node runs two tracks in parallel — a code track (regex-based, always active) and an LLM track (semantic, opt-in). Merge rule: **deny wins**. The code track is the correctness anchor; LLM fills semantic gaps but never overrides code-extracted structured data.

**7-layer write guard**: Authentication → Confirmation → Ownership → Read-before-write → Policy → Resource Locks → Idempotency. Every write tool call passes through all seven layers before execution.

## Key Design Decisions

- **Deny wins merge** — Any track that says deny produces deny. Both must say allow for allow. This ensures the deterministic code track acts as a safety floor.
- **Code track as anchor** — LLM decisions that contradict code decisions are overridden. LLM fills semantic gaps (extracting `reason` from natural language) but doesn't override code-extracted order IDs or item IDs.
- **Single source of truth for write actions** — `app/agent/action_specs.py` defines all 7 write operations. Guards, prompts, tool registry, and runtime all derive from this one file.

## Quick Start

```bash
# 1. Install dependencies
uv sync --extra dev

# 2. Start Workbench demo (deterministic mode, no API key needed)
uv run phase4-workbench &           # Python API on :8000
cd workbench && npm install && npm run dev   # React UI on :5173

# 3. Run eval (deterministic mode)
uv run phase2-eval --subset generalized_mvp --trials 1

# 4. Run tests
uv run python -m pytest tests/ -q
```

Optional: configure LLM mode by setting `DEEPSEEK_API_KEY` in `.env`.

## Demo Walkthrough

Open `http://localhost:5173` and explore the 10 demo cases, grouped by user journey:

| Group | Cases | What It Shows |
|-------|-------|---------------|
| 🔐 身份认证 | Name + ZIP lookup | Authentication flow, user identity resolution |
| ✅ 成功写操作 | Cancel order, Return items, Modify items, Modify payment | Happy path write operations with confirmation |
| 🛡️ 写保护阻止 | Wrong user access, Product mismatch, Insufficient gift card | Guard layers blocking unauthorized writes |
| 🔄 用户确认 | Denied cancellation | User-facing confirmation dialog, deny flow |
| 📞 边界能力 | Transfer to human | Unsupported operations escalation |

**Key evidence in the timeline**: Select any case, click "运行全部" (Run All), then explore the timeline:
- Intent extraction + slots → Policy decision (allow/deny + reason)
- Tool call result → Guard block details (if blocked)
- Write audit (DB hash before/after, idempotency key)

## Eval Results

| Metric | curated_mvp (11 cases) | generalized_mvp (30 cases) |
|--------|------------------------|---------------------------|
| pass_1 | 11/11 | 30/30 |
| pass_k | 11/11 | 30/30 |
| db_accuracy | 100% | 100% |

**Failure classification**: 14 ordered labels (llm_json_failure → auth_failure → wrong_intent → ...) ensure precise debugging.

## Project Structure

```text
app/agent/       — 12-node pipeline runtime, state models, prompts, guard
app/tools/       — retail adapter, tool registry, write gateway
app/eval/        — curated + generalized eval cases, runner, failure labels
app/workbench/   — Workbench API (FastAPI backend)
workbench/       — Workbench React UI
prompts/         — versioned LLM prompts with SHA-256 hashes
docs/            — design specs, plans, architecture docs
```

## Development

```bash
# Lint and format
uv run ruff check .
uv run ruff format --check .

# Run a single test
uv run python -m pytest tests/test_agent_core.py -v

# Run interactive chat
uv run phase1-chat --interactive
```

For detailed architecture reference, see [`docs/portfolio-architecture.md`](docs/portfolio-architecture.md).

For the full roadmap, see [`docs/long-term-optimization-path.md`](docs/long-term-optimization-path.md).
