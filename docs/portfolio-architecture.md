# Portfolio Architecture: Retail Customer Support Agent

> 面试深度参考资料 — 当面试官从 README 产生兴趣后，想深入了解设计决策时，就打开这一个文档。

## 1. 系统概述

一个基于 12-node LangGraph StateGraph 的零售客服 Agent。核心设计理念：**确定性先行，LLM 增强，拒绝优先**。系统必须始终做出安全决策，即使 LLM 出错或不可用。

关键数字：12 个 pipeline 节点、7 层写保护、2 轨并行决策（code + LLM）、1 个单一事实来源（action_specs.py）、30 个 eval case 全部通过。

## 2. 12-Node Pipeline

```
receive_message → conversation_gate → identity_resolver → intent_and_slot_extractor
→ context_loader → policy_reasoner → action_planner → write_action_guard
→ tool_executor → observation_reducer → response_generator → run_logger
```

| # | Node | 职责 | 输入 | 输出 |
|---|------|------|------|------|
| 1 | receive_message | 解析用户输入，加入 state.messages | raw text | user message |
| 2 | conversation_gate | 协议过滤（问候、感谢、无关话题） | user message | pass / early reply |
| 3 | identity_resolver | 用户身份认证（email / name+zip） | user message | user_id, auth_method |
| 4 | intent_and_slot_extractor | 意图识别 + 槽位填充 | user message | intent, slots |
| 5 | context_loader | 加载订单、商品、用户、支付数据 | user_id, order_id | loaded_context |
| 6 | policy_reasoner | 策略检查：允许/拒绝/需澄清 | intent, context | policy_decision |
| 7 | action_planner | 生成待执行写操作 | policy_decision | pending_action |
| 8 | write_action_guard | 7 层安全检查 | pending_action | pass / block |
| 9 | tool_executor | 执行工具调用 | action, args | tool_results |
| 10 | observation_reducer | 结果归纳，提取要点 | tool_results | observation |
| 11 | response_generator | 生成用户回复 | observation, context | assistant message |
| 12 | run_logger | 记录 trace artifact | full state | trace JSON |

**Circuit-breaker 模式**: 如果某节点追加了 assistant 消息到 `state.messages`，后续节点自动跳过（通过 `_has_assistant_response()` 检查）。这允许 conversation_gate 和 policy_reasoner 提前终止 pipeline。

## 3. Dual-Track Decision

### Code Track

- Regex-based intent extraction（关键词 + 模式匹配）
- Hardcoded policy rules（订单状态、商品可用性、支付方式归属）
- Explicit slot checks（order_id 格式、user_id 匹配）
- **始终运行**，不依赖外部 API

### LLM Track

- Semantic extraction via DeepSeek（OpenAI-compatible API）
- 仅在 `--require-llm` 且 `DEEPSEEK_API_KEY` 配置时运行
- 提取 code track 难以捕获的语义信息（如 `reason` 字段）

### Merge Rule: Deny Wins

```
track_a \ track_b | allow              | deny               | ask_clarification
------------------+--------------------+--------------------+-------------------
allow             | allow              | deny               | ask_clarification
deny              | deny               | deny               | deny
ask_clarification | ask_clarification  | deny               | ask_clarification
```

**为什么这样设计？** 在金融交易场景中，false negative（拒绝合法操作）优于 false positive（允许非法操作）。用户遇到 false negative 可以重新请求，但 false positive 可能造成不可逆的损失。

Code track 是"锚"——它提取的 order_id、item_id、user_id 等结构化数据，LLM 不能覆盖。LLM 只能补充 code track 未提取的字段。

## 4. 7-Layer Write Guard

`WriteActionGuard` 在 `app/agent/guard.py` 中实现，在**每一个写工具调用前**执行：

| Layer | 检查项 | 失败处理 | 实现位置 |
|-------|--------|----------|----------|
| 1. Authentication | 用户必须已登录 | block: `auth_required` | guard.py |
| 2. Confirmation | write 必须 `confirmed=True` | block: `confirmation_required` | guard.py |
| 3. Ownership | 订单必须属于认证用户 | block: `wrong_user` | guard.py |
| 4. Read-before-write | 订单必须先加载到 context | block: `order_not_loaded` | guard.py |
| 5. Policy | 订单状态、商品可用性、支付归属、礼品卡余额 | block: 具体原因 | guard.py |
| 6. Resource Locks | 同一资源不允许多个并发/重复写入 | block: `resource_locked` | guard.py |
| 7. Idempotency | 基于 hash 的幂等性 key | 去重而非 block | guard.py |

**关键不变量**: tools never call the guard directly。`ToolGateway` (`app/tools/gateway.py`) 是唯一入口点。

## 5. ToolGateway & Action Specs

### 读写分离

```
                   ┌──────────────────┐
User Message → ... →  action_planner  →  write_action_guard → ToolGateway
                   └──────────────────┘                              │
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

`app/agent/action_specs.py` 定义 `WriteActionSpec` — 所有 7 个写操作的权威注册表。每次新增写操作，**只需修改这一个文件**。Guard rules、tool registry、LLM prompts 中的 {action_catalog} 模板、runtime 中的 merge 逻辑全部从此派生。

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

所有 artifact 包含 schema_version、dataset paths、code commit、model config、prompt hashes、DB hashes。

## 7. Workbench

Workbench (`app/workbench/` + `workbench/`) 是一个 FastAPI + React 单会话演示面板。

- **Demo**: Phase 6 的核心演示工具 — 面试官可以看到完整的 agent 运行过程
- **Debug**: 开发者可以逐步运行 case，观察每个 pipeline 节点的输入输出
- **Future AgentOps**: Phase 11 将在此基础增加 run history、trace comparison、eval report browser

当前约束：单会话、不保存历史、不比较 trace、交互范围受限于预设 case 脚本。
