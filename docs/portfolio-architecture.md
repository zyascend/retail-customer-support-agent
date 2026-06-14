# Portfolio Architecture: Retail Customer Support Agent

> 面试深度参考资料 — 当面试官从 README 产生兴趣后，想深入了解设计决策时，就打开这一个文档。

## 1. 系统概述

一个基于 LLM tool-calling runtime 的零售客服 Agent。核心设计理念：**LLM 负责理解和工具选择，代码负责工具边界、写入护栏、确认流程和审计证据**。系统必须始终做出安全决策：LLM 可以请求写操作，但不能绕过 guard；没有 LLM provider 时，生产 runtime 安全转人工，不悄悄降级成规则写操作。

关键数字：1 个 `AgentLoop`、7 层写保护、1 个显式 `offline_demo` harness、1 个单一事实来源（`action_specs.py`）、`scripted_offline_demo` + live LLM eval 双验证路径。

## 2. LLM Tool-Calling Runtime

```
user message → pre-flight checks → AgentLoop → ToolGateway / WriteActionGuard
→ tool observation → assistant response → trace artifact
```

| Stage | 职责 | 关键产物 |
|-------|------|----------|
| Pre-flight confirmation | 如果已有 `pending_action`，先解析用户确认/拒绝/修改 | `confirmation_status`, write tool call |
| Pre-flight identity | email / name+zip shortcut，减少 LLM 不必要工具调用 | `authenticated_user_id`, `auth_method` |
| AgentLoop | 将工具 schema 暴露给 provider，执行 tool calls，回填 observation | `TurnContext`, `ToolCallRecord` |
| ToolGateway | 统一执行 read/write tools；写工具强制进 guard | tool observation, guard block + `block_context` |
| TraceWriter | 输出可审计 artifact | prompt hash, DB hash, LLM response, tool result |

`AgentLoop` 是普通 while loop，不是旧 LangGraph 线性 pipeline。它每轮调用 provider 的 `chat_with_tools()`，将模型请求的工具交给 `ToolGateway` 执行，并把 structured observation 追加回上下文，直到模型返回最终 assistant message 或触达安全上限。

## 3. Runtime / Harness Boundary

### Production Runtime

默认 `AgentRuntime` 需要真实 LLM provider。没有 provider 且未开启 `offline_demo` 时，runtime 返回安全转人工消息，并记录 `provider_unavailable` step。这个边界避免了“看似 LLM，实际规则 fallback”的误导。

### Offline Demo Harness

`offline_demo=True` 是显式演示/CI harness，用于 Workbench 和 `scripted_offline_demo` eval：

- 无需 API key 演示用户确认、guard block、write audit。
- 可以用规则解析覆盖精选脚本案例，保持本地 demo 稳定。
- 不作为生产 LLM 能力的证据，也不作为 generalized/live eval 的通过标准。

Phase 7 之后，demo-only 解析逻辑已移动到 `app/agent/offline_demo.py` 的 `OfflineDemoHarness`。`AgentRuntime` 只显式调用这个 harness，不再把 demo parser 混在生产 runtime 主体里。

Workbench API 仍兼容 legacy `"deterministic"` 输入，但会 canonicalize 为 `"offline_demo"`；新的 UI 和 snapshot 统一输出 `"offline_demo"`。

## 4. 7-Layer Write Guard

`WriteActionGuard` 在 `app/agent/guard.py` 中实现，在**每一个写工具调用前**由 `ToolGateway` (`app/tools/gateway.py`) 统一调度。共 26 个 block reason + 1 个 idempotency key 生成，分布在 8 个校验步骤中。

Phase 8 后，guard block 不再只是字符串 reason：`WriteActionGuardResult.block_context` 会被 `ToolGateway` 传播到 `ToolCallRecord`、LLM tool observation、trace/replay artifact 和 Workbench timeline。上下文保持最小化，只包含解释安全拒绝所需的 resource id、owner/auth identity、required read、policy state 或 lock id 等字段。

### 4.1 设计哲学

写操作安全是交易型 Agent 的核心竞争力。7 层设计遵循三个原则：

- **纵深防御**：每层解决一类独立的安全威胁。即使上游层被绕过，下游层仍会拦截 —— 例如 parser 错误提取了 order_id，ownership 校验仍会拒绝不属于该用户的订单。
- **Guard 是最终裁决层**：LLM 可以建议写操作，但不能决定写操作是否安全。ToolGateway 强制执行 guard check，LLM 没有绕过路径。
- **Deny-wins 短路**：任何一层返回 block 即立即终止。false negative（拒绝合法操作）优于 false positive（允许非法操作）—— 用户遇到 false negative 可以重新请求，但 false positive 可能造成不可逆的损失。

### 4.2 架构全景

```
用户请求 → LLM tool call 或 offline_demo pending_action
              ↓
         ToolGateway.execute()
              ↓
     WriteActionGuard.check(state, db, action, confirmed)
              ↓
    ┌─────────────────────────────────────────┐
    │ Layer 0: Action Type Validation         │ → unsupported_in_mvp / unknown_write_action
    │ Layer 1: Authentication                 │ → authentication_required
    │ Layer 2: Explicit Confirmation          │ → explicit_confirmation_required
    │ Layer 3: Ownership Validation           │ → ownership_violation / order_not_found
    │ Layer 4: Read-Before-Write              │ → read_before_write_required
    │ Layer 5: Policy Compliance              │ → 15 个具体 policy block reason
    │ Layer 6: Resource Locks                 │ → 4 个 lock conflict reason
    │ Layer 7: Idempotency                    │ → idempotency_key 生成（去重，不 block）
    └─────────────────────────────────────────┘
              ↓
    allowed=True  → tool 执行 → DB mutation + write audit
    allowed=False → 返回 block_reason，不执行 tool，DB 不变
```

**关键不变量**: tools never call the guard directly。ToolGateway 是唯一入口点，所有 write tool call 必须通过 `gateway.execute()` → `guard.check()`。

### 4.3 分层详解

#### 4.3.0 Layer 0 — Action Type Validation (`guard.py:42-45`)

在进入 7 层安全校验之前，先验证 action 本身是否合法：

- `unsupported_in_mvp`：action 在 `DEFERRED_WRITE_ACTIONS` 集合中（当前为空，为未来扩展预留）
- `unknown_write_action`：action 不在 `WRITE_ACTIONS` 白名单中（`app/agent/action_specs.py:WRITE_ACTION_NAMES` 派生）

这一层是防御性代码 —— ToolGateway 已经在调度层过滤了非写操作，但 guard 内部保留二次校验作为纵深防御。

#### 4.3.1 Layer 1 — Authentication (`guard.py:46-47`)

`state.authenticated_user_id` 必须非空。用户可以通过 pre-flight identity shortcut 或 LLM 工具调用完成认证。如果跳过认证直接发起写操作，此层拦截。

Block reason: `authentication_required`

#### 4.3.2 Layer 2 — Explicit Confirmation (`guard.py:48-52`)

`confirmed` 参数必须为 `True`。Agent 在准备写操作后，会先向用户展示操作摘要并请求确认。用户回复 "yes" / "confirm" 后，`confirmation.py` 解析确认意图，runtime 将 `confirmed=True` 传入 guard。

Block reason: `explicit_confirmation_required`

这是用户可感知的最直接安全层 —— 没有用户的明确确认，任何写操作都不会执行。

#### 4.3.3 Layer 3 — Ownership Validation (`guard.py:109-124`)

验证操作目标属于当前认证用户：

- **订单操作**：`order.user_id` 必须等于 `state.authenticated_user_id`（`guard.py:122-123`）
- **用户地址操作**（`modify_user_address`）：`user_id` 参数必须等于认证用户（`guard.py:113-116`）
- **订单存在性**：order_id 必须在 DB 中存在（`guard.py:120-121`）

Block reason: `ownership_violation`, `order_not_found`

#### 4.3.4 Layer 4 — Read-Before-Write (`guard.py:126-136`)

操作目标必须已加载到 `state.loaded_context`：

- 订单操作：`order_id` 必须在 `state.loaded_context.orders` 中（`guard.py:130-131`）
- 用户地址操作：`user_id` 必须在 `state.loaded_context.users` 中（`guard.py:134-135`）

这一层确保 Agent 在修改数据前已经读取并理解了当前状态。正常流程中，LLM 会先调用 read tool，offline demo harness 也会自动加载订单上下文；如果绕过读取直接写入，此层会拦截。

Block reason: `read_before_write_required`

#### 4.3.5 Layer 5 — Policy Compliance (`guard.py:138-221`)

最复杂的校验层，按写操作类型分派到不同的策略校验方法：

**订单状态校验**：
- `cancel_pending_order` → 订单状态必须为 `pending`（`guard.py:143-144`）
- `modify_pending_order_address/items/payment` → 订单状态必须为 `pending`（`guard.py:148-149, 162-163, 168-169`）
- `return_delivered_order_items` → 订单状态必须为 `delivered`（`guard.py:151-152`）
- `exchange_delivered_order_items` → 订单状态必须为 `delivered`（`guard.py:154-155`）

Block reason: `non_pending_order_cannot_be_cancelled`, `non_pending_order_cannot_be_modified`, `non_delivered_order_cannot_be_returned`, `non_delivered_order_cannot_be_exchanged`

**Cancel reason 校验**（`guard.py:145-146`）：
- reason 只允许 `"no longer needed"` 和 `"ordered by mistake"`

Block reason: `invalid_cancel_reason`

**商品替换校验**（`_validate_item_replacements`, `guard.py:178-200`）：
- 新旧 item 数量必须匹配（`guard.py:183-184`）
- 旧 item 必须在订单中（`guard.py:191-192`）
- 新 item 必须在 DB variant 中存在（`guard.py:194-195`）
- 新旧 item 必须属于同一 product（`guard.py:196-197`）
- 新 item 必须 available（`guard.py:198-199`）

Block reason: `replacement_item_count_mismatch`, `exchange_item_count_mismatch`, `order_item_not_found`, `replacement_item_not_found`, `replacement_item_product_mismatch`, `replacement_item_unavailable`

**支付方式校验**（`_validate_payment_change`, `guard.py:202-221`）：
- 支付方式必须属于当前用户（`guard.py:210-211`）
- 新支付方式不能与当前相同（`guard.py:213-214`）
- 如果使用 gift card，余额必须覆盖订单金额（`guard.py:219-220`）

Block reason: `payment_method_not_owned`, `same_payment_method`, `gift_card_balance_insufficient`

**用户地址校验**（`guard.py:173-175`）：
- 目标用户必须在 DB 中存在

Block reason: `user_not_found`

#### 4.3.6 Layer 6 — Resource Locks (`guard.py:243-262`)

防止同一资源上的并发/重复写入。每次成功的写操作会向 `state.write_locks` 追加一个 lock key：

- `duplicate_write_lock`：完全相同的 lock key 已存在（`guard.py:246-247`）
- `order_already_cancelled_or_locked`：订单已被取消或有 cancel lock（`guard.py:250-251`）
- `order_items_already_modified`：订单已修改过 items（`guard.py:252-254`）
- `item_already_returned_or_exchanged`：同一 item 已有 return/exchange lock（`guard.py:260-261`）

当前 Workbench 单会话 demo 中这些 lock 不会触发（每个 case 只有一次写操作），但在多轮对话或多 Agent 协作场景中，它们是防止重复操作的最后一道防线。

Block reason: `duplicate_write_lock`, `order_already_cancelled_or_locked`, `order_items_already_modified`, `item_already_returned_or_exchanged`

#### 4.3.7 Layer 7 — Idempotency (`guard.py:73-80`)

基于 `session_id + tool_name + arguments + resource_lock` 生成 `stable_hash` 作为 idempotency key。这一层不产生 block reason（它是去重机制，不是阻断机制），但它是安全架构的关键组成部分 —— 即使 guard 被重复调用，相同的操作也会产生相同的 idempotency key，tool executor 可根据此 key 去重。

Idempotency key 包含在 `ToolCallRecord` 和 trace artifact 中，用于审计追溯。

### 4.4 覆盖率矩阵

以下矩阵展示 26 个 block reason + idempotency key 的测试和 eval 覆盖状态：

| # | Layer | Block Reason / 行为 | 单元测试 | Eval Case | 状态 |
|---|-------|--------------------|---------|-----------|------|
| 1 | 0 | `unsupported_in_mvp` | — | — | ❌ 防御性 |
| 2 | 0 | `unknown_write_action` | — | — | ❌ 防御性 |
| 3 | 1 | `authentication_required` | `test_blocks_unauthenticated_write` | — | ✅ 单元覆盖 |
| 4 | 2 | `explicit_confirmation_required` | `test_gateway_blocks_write_without_confirmation` | `deny_cancel_confirmation` 等 5 个 | ✅ 双覆盖 |
| 5 | 3 | `ownership_violation` | `test_blocks_wrong_user_order_mutation` | `block_wrong_user_order_access` | ✅ 双覆盖 |
| 6 | 3 | `order_not_found` | — | — | ❌ 防御性 |
| 7 | 4 | `read_before_write_required` | — | — | ❌ 防御性 |
| 8 | 5 | `non_pending_order_cannot_be_cancelled` | `test_blocks_invalid_order_statuses` | `block_cancel_processed_order` | ✅ 双覆盖 |
| 9 | 5 | `invalid_cancel_reason` | — | — | ❌ 防御性 |
| 10 | 5 | `non_pending_order_cannot_be_modified` | — | `block_modify_items_non_pending_order`, `block_modify_payment_processed_order` | ⚠️ eval 覆盖 |
| 11 | 5 | `non_delivered_order_cannot_be_returned` | `test_blocks_invalid_order_statuses` | `block_return_pending_order` | ✅ 双覆盖 |
| 12 | 5 | `non_delivered_order_cannot_be_exchanged` | — | — | ❌ 防御性 |
| 13 | 5 | `exchange_item_count_mismatch` | — | — | ❌ 防御性 |
| 14 | 5 | `replacement_item_count_mismatch` | — | — | ❌ 防御性 |
| 15 | 5 | `order_item_not_found` | — | — | ❌ 防御性 |
| 16 | 5 | `replacement_item_not_found` | — | — | ❌ 防御性 |
| 17 | 5 | `replacement_item_product_mismatch` | `test_blocks_item_replacement_across_products`, `test_blocks_exchange_across_products` | `block_item_product_mismatch`, `block_exchange_product_mismatch` | ✅ 双覆盖 |
| 18 | 5 | `replacement_item_unavailable` | — | `block_item_unavailable`, `block_exchange_unavailable_replacement` | ⚠️ eval 覆盖 |
| 19 | 5 | `payment_method_not_owned` | `test_blocks_payment_method_not_owned` | `block_payment_not_owned` | ✅ 双覆盖 |
| 20 | 5 | `same_payment_method` | — | `block_same_payment_method` | ⚠️ eval 覆盖 |
| 21 | 5 | `gift_card_balance_insufficient` | — | `block_payment_insufficient_gift_card` | ⚠️ eval 覆盖 |
| 22 | 5 | `user_not_found` | — | — | ❌ 防御性 |
| 23 | 6 | `duplicate_write_lock` | — | — | ❌ 单会话 |
| 24 | 6 | `order_already_cancelled_or_locked` | — | — | ❌ 单会话 |
| 25 | 6 | `order_items_already_modified` | — | — | ❌ 单会话 |
| 26 | 6 | `item_already_returned_or_exchanged` | — | — | ❌ 单会话 |
| 27 | 7 | idempotency_key 生成 | `test_idempotency_key_changes_with_arguments` | 所有 write eval cases | ✅ 双覆盖 |

**汇总**:
- ✅ 双覆盖（单元 + eval）: **8** — 核心安全路径充分验证
- ✅ 单元覆盖（仅单元测试）: **1** — `authentication_required`
- ⚠️ eval 覆盖（仅 eval case）: **4** — eval 层面完整，单元测试可后续补充
- ❌ 未覆盖: **14** — 全部为防御性代码或单会话限制，在正常 runtime 流程中由上游读取/参数约束保证不会触发

### 4.5 审计结论

#### 已知弱覆盖区域

以下 14 个 block reason 在当前测试和 eval 中无覆盖：

| 类别 | Block Reason | 为何可接受 |
|------|-------------|-----------|
| 被上游 shadow | `order_not_found`, `read_before_write_required`, `user_not_found` | 正常 runtime 会先通过 read tool / pre-flight 加载上下文 |
| 被上游 shadow | `invalid_cancel_reason`, `exchange_item_count_mismatch`, `replacement_item_count_mismatch`, `order_item_not_found`, `replacement_item_not_found` | tool schema、prompt contract 和 guard 共同约束参数合法性 |
| 防御性占位 | `unsupported_in_mvp`, `unknown_write_action` | 当前无 deferred actions，ToolGateway 已过滤非写操作 |
| 防御性占位 | `non_delivered_order_cannot_be_exchanged` | 行为与 return 对称，测试覆盖了 return 侧 |
| 单会话限制 | `duplicate_write_lock`, `order_already_cancelled_or_locked`, `order_items_already_modified`, `item_already_returned_or_exchanged` | 当前 Workbench 单会话 demo 中不会触发并发写；Phase 7（synthetic sandbox）和 Phase 11（多轮 history）为自然补充时机 |

#### 后续 Phase 中 guard 扩展检查清单

当 Phase 7 新增 `modify_pending_order_shipping_method` 写操作时：
- [ ] `action_specs.py` 新增 `WriteActionSpec`
- [ ] `_validate_policy()` 新增配送方式相关 block reason
- [ ] `_resource_lock()` 新增 lock key 生成
- [ ] 至少 1 个单元测试覆盖新增 block reason
- [ ] 至少 2 个 eval case（success + block）
- [ ] 更新本文档 4.4 覆盖率矩阵

### 4.6 证据展示

#### Guard Block 证据

![Guard Block Trace](../demo-screenshots/guard-block-evidence.png)

*Workbench 中 `block_wrong_user_order_access` case 的 timeline 截图。关键证据：① ToolGateway 返回 blocked 状态 ② block_reason = `ownership_violation` ③ block_context 标明 order owner 与 authenticated user 不一致 ④ before_db_hash = after_db_hash（no-write invariant）⑤ 无 write lock 生成*

#### Successful Write 证据

![Write Audit Trace](../demo-screenshots/write-audit-evidence.png)

*Workbench 中 `cancel_pending_order` case 的 timeline 截图。关键证据：① confirmation 通过（用户回复 "yes"）② guard check allowed=True ③ tool 执行成功，DB mutation 完成 ④ idempotency_key 和 resource_lock 记录在 ToolCallRecord 中 ⑤ write audit log 可追溯*

#### 当前关键指标

| 指标 | 值 | 来源 |
|------|-----|------|
| `mutation_error_rate` | 0.0 | scripted generalized smoke |
| `guard_block_rate` | case-dependent | eval report 按 case subset 统计 |
| no-write invariant | 100% | 所有 guard block case 的 before/after DB hash 一致 |
| `tool_call_success_rate` | report-dependent | 每次 eval report 输出 |

## 5. ToolGateway & Action Specs

### 读写分离

```
                   ┌──────────────────┐
User Message → AgentLoop tool call / offline_demo action → ToolGateway
                                                             │
                                              ┌──────────────────────┤
                                              ▼                      ▼
                                        Read Tools            Write Tools
                                   (lookup, get_details)   (cancel, return, ...)
                                              │                      │
                                              └──────────┬───────────┘
                                                         ▼
                                                  Tool Results
```

- **Read tools**: 直接从 adapter 调取数据，不经过 guard
- **Write tools**: 必须先通过 `WriteActionGuard.check()`，由 gateway 统一调度

### 单一事实来源

`app/agent/action_specs.py` 定义 `WriteActionSpec` — 所有 7 个写操作的权威注册表。每次新增写操作，**只需修改这一个文件**。Guard rules、tool registry、LLM prompts 中的 `{action_catalog}` 模板和写操作参数约束全部从此派生。

## 6. Eval & Trace Infrastructure

### Eval Case 设计

- **curated_mvp** (11 cases): 人工精选，覆盖核心能力
- **generalized_mvp** (30+ cases): 基于 capability × policy_area 矩阵的系统化变体

每个 `EvalCase` 指定：messages、expected_intent、expected_tool_names、expected_guard_block_reason、expected_db_assertions、expected_no_write。

### 14 种 Failure Classification

优先级顺序：llm_json_failure → auth_failure → wrong_intent → wrong_tool → unexpected_tool → missing_tool → guard_miss → guard_false_positive → db_mismatch → mutation_error → confirmation_error → tool_error → timeout → unknown。定义在 `classify_failure()`。

### Artifact 契约

- **Eval run**: `artifacts/phase2/eval_runs/<id>.json` — schema_version v1
- **Eval report**: `artifacts/phase2/reports/<id>.json` — schema_version v1
- **Trace**: `artifacts/phase1/runs/<id>.json`
- **Dashboard**: `artifacts/phase3/dashboard/<id>/index.html`

Phase 9 后，eval report 还包含 `baseline_metadata`：model、provider、prompt hash、tool schema hash、action specs hash 和 eval backend。Report metrics 汇总 `total_token_usage`、`average_llm_loop_iterations`、tool call count、guard block count、mutation error rate；失败 case 可通过 `app.eval.live_triage` 输出 root cause 和 trace-derived triage bundle。

所有 artifact 包含 schema_version、dataset paths、code commit、model config、prompt hashes、DB hashes。

## 7. Workbench

Workbench (`app/workbench/` + `workbench/`) 是一个 FastAPI + React 单会话演示面板。

- **Demo**: Phase 6 的核心演示工具 — 面试官可以看到完整的 agent 运行过程
- **Debug**: 开发者可以逐步运行 case，观察 pre-flight、tool calls、guard blocks 和 write audit
- **Future AgentOps**: Phase 11 将在此基础增加 run history、trace comparison、eval report browser

当前约束：单会话、不保存历史、不比较 trace、交互范围受限于预设 case 脚本。
