# Retail Customer Support Agent — 项目专属 Context

> 这是**项目级** `CLAUDE.md`，叠加在你全局 / 上层的 `CLAUDE.md` 之上。
> 只写**这个项目**特有的接续规则，不复述上层已经有的全局规则。

---

## 新会话醒来的头 30 秒

**先判断单工作流还是多工作流**（看 `brain/` 下的文件命名）：
- 只有 `STATUS.md` / `HANDOFF.md` → 走"**单工作流**"分支
- 有多个 `STATUS_<工作流>.md` 文件 → 走"**多工作流**"分支（v2.1）

### 单工作流（默认）

**必读两份**（都在 `brain/` 下）：

1. `brain/MAP.md` — 项目地图。回答"这个项目长什么样、文档去哪找？"
2. `brain/STATUS.md` — 当前状态。回答"现在停在哪、下一步做什么？"

**如果存在 `brain/HANDOFF.md`** —— 也读它。这是上个会话切窗口前留下的、还没落到结构化文件里的"还热乎"的内容。

读完后简短回报：项目识别 + 当前进度 + 上次卡点。**不要静默动手** —— 确认理解对了再开始干。

### 多工作流（v2.1）

**先读项目级共享文件**：`brain/MAP.md`（含第 6 节工作流清单）+ `brain/PROJECT.md`（如需）。

**不要自己猜窗口归属** —— 简短回报并询问：

> "我看到这是多工作流项目，有 [列出所有工作流名]。这个窗口做哪个？"

用户显式说后，**再读对应工作流的** `brain/STATUS_<工作流>.md` + `brain/HANDOFF_<工作流>.md`，然后做和单工作流一样的简短回报。

**如果同会话内用户让窗口切换工作流** —— 必须重新读新工作流的 STATUS + HANDOFF，**不要混用上一个工作流的记忆**。

## 什么时候读其他接续层文件

- **范围模糊 / 有人问"这个项目能不能加 X 功能"** → 读 `brain/PROJECT.md`（看是不是被"刻意不做什么"挡了）
- **想搞清楚"为什么现在长成这样"** → 读 `brain/DECISIONS.md`
- **想知道 `brain/topics/` 下某份文件在哪** → 回 `brain/MAP.md` 第 5 节文档索引

## 什么时候读 `brain/topics/` 内容

`brain/MAP.md` 第 5 节会给每份 topic 文档标"何时读"。按触发条件读，不要每次都全部读。

## 更新职责

**核心原则**：AI 不静默修改 `brain/` 下任何文件 —— 先提议，用户拍板。

**判断分工**（重要）：
- 用户决定"**现在该不该记**"
- AI 决定"**具体记什么、每条怎么写**"（用户不知道每个文件内部怎么运作 —— 不要把这种判断推回去）
- 用户拥有对 AI 判断的批准 / 否决权

具体节奏：

- 用户说"**更新项目脑**" → 跑"判断 + 清单"工作流：基于本次会话发生了什么，主动判断哪些文件该更新、写什么，给一份**带理由的清单**让用户审
- AI 感觉"那段像是决策" → **温柔询问**："这算定下来了吗？要不要追加到 DECISIONS？" —— 不要断言
- 模块新增 / 删除 → 提议更新 `brain/MAP.md` 第 2 节
- 新增文档 / 废弃文档 → 提议更新 `brain/MAP.md` 第 5 节
- 用户暗示会话结束（"就这样 / 我先走了 / 该切了"）→ 主动起草 `brain/STATUS.md` 让用户审（软上限 80 行）
- 用户说切窗口 → 写 `brain/HANDOFF.md`，把上一份归档到 `brain/handoffs/YYYY-MM-DD-HHMM.md`
- 用户显式说"更新 STATUS / 记一条决策" → 直接做，不要再问

---

## 项目架构与工程规范

### Conventions

- **文档语言**: 项目文档默认使用中文，包括 README、docs 下的设计文档、路线图、计划、评审说明和阶段总结。只有外部 API 名称、代码标识符、命令、指标名、英文专有术语或需要对齐上游英文材料时保留英文。
- **Commit messages**: `<type>: 中文描述` — type 用 `feat` / `fix` / `chore` / `docs` / `refactor` / `test`，描述用中文。示例：`feat: 添加 action_specs 单一事实来源`
- **分支管理**: 使用普通 git 分支开发，优先 `git checkout -b <branch>`；不使用 git worktree。合并后删除已完成分支。

### Commands

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

### Architecture

#### LLM Tool-Calling Runtime

The production runtime is `AgentRuntime` + `AgentLoop`:

```
user message → pre-flight checks → AgentLoop → ToolGateway / WriteActionGuard
→ tool observation → assistant response → trace artifact
```

`AgentLoop` sends tool schemas to the configured provider with `chat_with_tools()`, executes requested tools through `ToolGateway`, appends structured observations, and stops when the model returns an assistant response or a safety limit is reached.

Pre-flight logic in `AgentRuntime` handles pending write confirmations and identity shortcuts before the LLM loop. This keeps confirmation safety deterministic while preserving LLM ownership of intent/tool selection.

#### Runtime / Harness Boundary

Production/default `AgentRuntime` requires an LLM provider. If no provider is configured, the runtime returns a safe human-transfer message.

The Workbench API no longer supports `"offline_demo"` mode; only `"llm"` mode is available.

#### Write Safety: 7-Layer Guard

`WriteActionGuard` in `guard.py` executes before any write tool call. Layers:

1. **Authentication** — user must be logged in
2. **Explicit confirmation** — write requires `confirmed=True`
3. **Ownership** — order must belong to authenticated user
4. **Read-before-write** — order must be loaded in context first
5. **Policy compliance** — order status, item availability, payment method ownership, gift card balance
6. **Resource locks** — prevents concurrent/duplicate writes on same resource
7. **Idempotency** — hash-based idempotency keys

#### Write Actions: Single Source of Truth

`app/agent/action_specs.py` defines `WriteActionSpec` — the authoritative registry of all 7 write operations. Every other module (guard, runtime, registry, prompts, retail_adapter) derives from this registry. Adding a new write action requires changes only in `action_specs.py`.

#### State Management

`SessionState` in `app/agent/models.py` is the central state object for runtime turns. `ConversationState` remains as a backward-compatible alias for older imports. Key sub-structures:

- `PendingAction` — deferred write waiting for user confirmation
- `PolicyDecision` — merged code+LLM decision with intent, missing_slots, explanation
- `LoadedContext` — in-memory cache of loaded DB records (users, orders, products, items)
- `ToolCallRecord` — per-call record with arguments, status, DB hashes, idempotency
- `step_durations` / `llm_call_durations` — per-node and per-LLM-call timing data

`AgentRuntime.handle_user_message()` mutates `SessionState` per turn and records timing, steps, tool calls, guard blocks, pending actions, and write audit evidence.

#### Tool Layer

- **RetailAdapter** (`app/tools/retail_adapter.py`) — wraps tau2-bench runtime; falls back to `LocalRetailTools` (pure-Python SQLite on `db.json`) when tau2 is unavailable.
- **ToolRegistry** (`app/tools/registry.py`) — auto-discovers tools by type (read/write/generic), generates LLM-visible catalog.
- **ToolGateway** (`app/tools/gateway.py`) — guard-gated execution layer. Every write call passes through `WriteActionGuard.check()` before the tool function runs.

Key invariant: **tools never call the guard directly.** The gateway is the only entry point; tools do not import or reference guard logic.

#### Prompts

Prompts live as versioned Markdown files in `prompts/` (e.g., `core_contract_v001.md`). `app/agent/prompts.py` loads them at module import, computes SHA-256 hashes, and assembles system prompts by concatenating `core_contract` as a shared prefix to each task-specific prompt. The `action_planner` prompt uses `{action_catalog}` placeholder that gets replaced at assembly time with auto-generated content from `action_specs.py`.

#### Eval Infrastructure

- **Cases**: `app/eval/cases.py` — `curated_mvp` (11 cases) and `generalized_mvp` (30+ cases). Each `EvalCase` specifies expected intents, tool calls, DB state, guard behavior.
- **Runner**: `app/eval/runner.py` — `CuratedEvalRunner` executes cases sequentially or in parallel (`--max-workers`). Live eval uses the real LLM provider (requires `DEEPSEEK_API_KEY`). No offline/deterministic harness is supported.
- **Failure classification**: 14 ordered labels in `classify_failure()` — priority matters (llm_json_failure beats auth_failure beats wrong_intent, etc.).
- **Metrics**: `pass_1` (per-result), `pass_k` (per-unique-case), `db_accuracy`, `tool_call_success_rate`, `guard_block_rate`, `mutation_error_rate`.

#### Config

`app/config.py` — `AppConfig` frozen dataclass loaded from env vars / `.env` file. Searches `.env` upward from cwd to git root (supports worktree setups). Key env vars: `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEFAULT_AGENT_MODEL`, `TAU2_BENCH_ROOT`, `TAU2_DATA_DIR`.

#### Confirmation Parser

`app/agent/confirmation.py` uses weighted keyword scoring across 3 dimensions (confirm/deny/change). Uses word-boundary matching for English to avoid false positives ("notebook" ≠ "no"), overlap suppression for Chinese, and negation detection ("don't change" → deny). Returns `"confirm" | "deny" | "changed" | "unknown"`.
