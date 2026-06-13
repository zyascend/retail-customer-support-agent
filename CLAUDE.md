# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Conventions

- **文档语言**: 项目文档默认使用中文，包括 README、docs 下的设计文档、路线图、计划、评审说明和阶段总结。只有外部 API 名称、代码标识符、命令、指标名、英文专有术语或需要对齐上游英文材料时保留英文。
- **Commit messages**: `<type>: 中文描述` — type 用 `feat` / `fix` / `chore` / `docs` / `refactor` / `test`，描述用中文。示例：`feat: 添加 action_specs 单一事实来源`
- **分支管理**: 使用普通 git 分支开发，优先 `git checkout -b <branch>`；不使用 git worktree。合并后删除已完成分支。

## Commands

```bash
# Install dependencies
uv sync --extra dev

# Run all tests
uv run python -m pytest tests/ -v

# Run a single test file / class / method
uv run python -m pytest tests/test_agent_core.py -v
uv run python -m pytest tests/test_agent_core.py::WriteGuardTests -v
uv run python -m pytest tests/test_agent_core.py::ConfirmationResolverTests::test_negated_change_returns_deny -v

# Lint
uv run ruff check .

# Run agent chat (deterministic mode, no API key needed)
uv run phase1-chat --script examples/chat/cancel_order.json

# Run eval
uv run phase2-eval --subset curated_mvp --trials 1

# Dashboard from eval report
uv run phase3-dashboard artifacts/phase2/reports/<eval_run_id>.json
```

## Architecture

### 12-node Linear Pipeline

The agent runs a LangGraph `StateGraph` of 12 nodes in strict order:

```
receive_message → conversation_gate → identity_resolver → intent_and_slot_extractor
→ context_loader → policy_reasoner → action_planner → write_action_guard
→ tool_executor → observation_reducer → response_generator → run_logger
```

If LangGraph is unavailable, `runtime.py` falls back to sequential execution of the same nodes. The pipeline is defined in `app/agent/graph.py` (`PHASE1_NODES` tuple).

### Dual-Track Architecture (Code + LLM)

Every decision node runs two tracks in parallel and merges conservatively:

- **Code track**: Regex-based intent extraction, hardcoded policy rules, explicit slot checks. Always runs, no external dependency.
- **LLM track**: Semantic extraction via DeepSeek (OpenAI-compatible API). Runs only when `--require-llm` is set and `DEEPSEEK_API_KEY` is configured.

**Merge rule: deny wins.** Any track that says "deny" produces deny. Any track that says "ask_clarification" produces ask. Both must say "allow" for allow. This is implemented in `_merge_policy_decisions()` and `_merge_slots()` in `runtime.py`.

The code track is the correctness anchor — LLM decisions that contradict it are overridden. LLM fills semantic gaps (e.g., extracting `reason` from natural language) but doesn't override code-extracted structured data (order IDs, item IDs).

### Write Safety: 7-Layer Guard

`WriteActionGuard` in `guard.py` executes before any write tool call. Layers:

1. **Authentication** — user must be logged in
2. **Explicit confirmation** — write requires `confirmed=True`
3. **Ownership** — order must belong to authenticated user
4. **Read-before-write** — order must be loaded in context first
5. **Policy compliance** — order status, item availability, payment method ownership, gift card balance
6. **Resource locks** — prevents concurrent/duplicate writes on same resource
7. **Idempotency** — hash-based idempotency keys

### Write Actions: Single Source of Truth

`app/agent/action_specs.py` defines `WriteActionSpec` — the authoritative registry of all 7 write operations. Every other module (guard, runtime, registry, prompts, retail_adapter) derives from this registry. Adding a new write action requires changes only in `action_specs.py`.

### State Management

`ConversationState` in `app/agent/models.py` is the central state object flowing through all 12 nodes. It's a Pydantic v2 `BaseModel` with these key sub-structures:

- `PendingAction` — deferred write waiting for user confirmation
- `PolicyDecision` — merged code+LLM decision with intent, missing_slots, explanation
- `LoadedContext` — in-memory cache of loaded DB records (users, orders, products, items)
- `ToolCallRecord` — per-call record with arguments, status, DB hashes, idempotency
- `step_durations` / `llm_call_durations` — per-node and per-LLM-call timing data

Nodes communicate via the circuit-breaker pattern: if a node appends an assistant message to `state.messages`, downstream nodes skip themselves (checked via `_has_assistant_response()`).

### Tool Layer

- **RetailAdapter** (`app/tools/retail_adapter.py`) — wraps tau2-bench runtime; falls back to `LocalRetailTools` (pure-Python SQLite on `db.json`) when tau2 is unavailable.
- **ToolRegistry** (`app/tools/registry.py`) — auto-discovers tools by type (read/write/generic), generates LLM-visible catalog.
- **ToolGateway** (`app/tools/gateway.py`) — guard-gated execution layer. Every write call passes through `WriteActionGuard.check()` before the tool function runs.

Key invariant: **tools never call the guard directly.** The gateway is the only entry point; tools do not import or reference guard logic.

### Prompts

Prompts live as versioned Markdown files in `prompts/` (e.g., `core_contract_v001.md`). `app/agent/prompts.py` loads them at module import, computes SHA-256 hashes, and assembles system prompts by concatenating `core_contract` as a shared prefix to each task-specific prompt. The `action_planner` prompt uses `{action_catalog}` placeholder that gets replaced at assembly time with auto-generated content from `action_specs.py`.

### Eval Infrastructure

- **Cases**: `app/eval/cases.py` — `curated_mvp` (11 cases) and `generalized_mvp` (30+ cases). Each `EvalCase` specifies expected intents, tool calls, DB state, guard behavior.
- **Runner**: `app/eval/runner.py` — `CuratedEvalRunner` executes cases sequentially or in parallel (`--max-workers`). Compares actual vs expected state.
- **Failure classification**: 14 ordered labels in `classify_failure()` — priority matters (llm_json_failure beats auth_failure beats wrong_intent, etc.).
- **Metrics**: `pass_1` (per-result), `pass_k` (per-unique-case), `db_accuracy`, `tool_call_success_rate`, `guard_block_rate`, `mutation_error_rate`.

### Config

`app/config.py` — `AppConfig` frozen dataclass loaded from env vars / `.env` file. Searches `.env` upward from cwd to git root (supports worktree setups). Key env vars: `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEFAULT_AGENT_MODEL`, `TAU2_BENCH_ROOT`, `TAU2_DATA_DIR`.

### Confirmation Parser

`app/agent/confirmation.py` uses weighted keyword scoring across 3 dimensions (confirm/deny/change). Uses word-boundary matching for English to avoid false positives ("notebook" ≠ "no"), overlap suppression for Chinese, and negation detection ("don't change" → deny). Returns `"confirm" | "deny" | "changed" | "unknown"`.
