# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**On session start, also read `HANDOFF.md`** — it contains the latest session's progress, eval baselines, and next steps. Updated automatically by `/pr` and `/prm`.

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

# Run agent chat (requires DEEPSEEK_API_KEY for LLM tool-calling;
# without a provider, runtime safely transfers to a human agent)
uv run phase1-chat --script examples/chat/cancel_order.json

# Run eval (requires DEEPSEEK_API_KEY for --live mode;
# without API key, runtime safely transfers to a human agent)
uv run phase2-eval --subset curated_mvp --trials 1
```

## Architecture

### LLM Tool-Calling Runtime

The production runtime is `AgentRuntime` + `AgentLoop`:

```
user message → pre-flight checks → AgentLoop → ToolGateway / WriteActionGuard
→ tool observation → assistant response → trace artifact
```

`AgentLoop` sends tool schemas to the configured provider with `chat_with_tools()`, executes requested tools through `ToolGateway`, appends structured observations, and stops when the model returns an assistant response or a safety limit is reached.

Pre-flight logic in `AgentRuntime` handles pending write confirmations and identity shortcuts before the LLM loop. This keeps confirmation safety deterministic while preserving LLM ownership of intent/tool selection.

### Runtime / Harness Boundary

Production/default `AgentRuntime` requires an LLM provider. If no provider is configured, the runtime returns a safe human-transfer message.

The Workbench API no longer supports `"offline_demo"` mode; only `"llm"` mode is available.

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

`SessionState` in `app/agent/models.py` is the central state object for runtime turns. `ConversationState` remains as a backward-compatible alias for older imports. Key sub-structures:

- `PendingAction` — deferred write waiting for user confirmation
- `PolicyDecision` — merged code+LLM decision with intent, missing_slots, explanation
- `LoadedContext` — in-memory cache of loaded DB records (users, orders, products, items)
- `ToolCallRecord` — per-call record with arguments, status, DB hashes, idempotency
- `step_durations` / `llm_call_durations` — per-node and per-LLM-call timing data

`AgentRuntime.handle_user_message()` mutates `SessionState` per turn and records timing, steps, tool calls, guard blocks, pending actions, and write audit evidence.

### Tool Layer

- **RetailAdapter** (`app/tools/retail_adapter.py`) — wraps tau2-bench runtime; falls back to `LocalRetailTools` (pure-Python SQLite on `db.json`) when tau2 is unavailable.
- **ToolRegistry** (`app/tools/registry.py`) — auto-discovers tools by type (read/write/generic), generates LLM-visible catalog.
- **ToolGateway** (`app/tools/gateway.py`) — guard-gated execution layer. Every write call passes through `WriteActionGuard.check()` before the tool function runs.

Key invariant: **tools never call the guard directly.** The gateway is the only entry point; tools do not import or reference guard logic.

### Prompts

Prompts live as versioned Markdown files in `prompts/` (e.g., `core_contract_v001.md`). `app/agent/prompts.py` loads them at module import, computes SHA-256 hashes, and assembles system prompts by concatenating `core_contract` as a shared prefix to each task-specific prompt. The `action_planner` prompt uses `{action_catalog}` placeholder that gets replaced at assembly time with auto-generated content from `action_specs.py`.

### Eval Infrastructure

- **Cases**: `app/eval/cases.py` — `curated_mvp` (11 cases) and `generalized_mvp` (30+ cases). Each `EvalCase` specifies expected intents, tool calls, DB state, guard behavior.
- **Runner**: `app/eval/runner.py` — `CuratedEvalRunner` executes cases sequentially or in parallel (`--max-workers`). Live eval uses the real LLM provider (requires `DEEPSEEK_API_KEY`). No offline/deterministic harness is supported.
- **Failure classification**: 14 ordered labels in `classify_failure()` — priority matters (llm_json_failure beats auth_failure beats wrong_intent, etc.).
- **Metrics**: `pass_1` (per-result), `pass_k` (per-unique-case), `db_accuracy`, `tool_call_success_rate`, `guard_block_rate`, `mutation_error_rate`.

### Config

`app/config.py` — `AppConfig` frozen dataclass loaded from env vars / `.env` file. Searches `.env` upward from cwd to git root (supports worktree setups). Key env vars: `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEFAULT_AGENT_MODEL`, `TAU2_BENCH_ROOT`, `TAU2_DATA_DIR`.

### Confirmation Parser

`app/agent/confirmation.py` uses weighted keyword scoring across 3 dimensions (confirm/deny/change). Uses word-boundary matching for English to avoid false positives ("notebook" ≠ "no"), overlap suppression for Chinese, and negation detection ("don't change" → deny). Returns `"confirm" | "deny" | "changed" | "unknown"`.
