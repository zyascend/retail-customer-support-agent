# LLM Agent Tool-Calling 架构设计

日期：2026-06-13
状态：设计阶段

## 设计公约

在改架构的过程中，如果原来的架构不符合新要求，直接完全推倒重建。不必为了改动少而放弃最佳实践。

## 方法论

LLM 决策为主，Code 有两项职责：

1. **安全兜底**（不可绕过）— guard、白名单校验、迭代上限、LLM 故障降级
2. **Token 优化**（减少 LLM 调用成本）— pre-flight 确定性短路、上下文压缩、读工具结果摘要化

现有的管道功能（日志、trace、case 回放、eval report、Workbench snapshot）继续由 code 负责，不交给 LLM。

## 架构决策

| # | 决策项 | 结论 |
|---|--------|------|
| 1 | Pipeline 形态 | 纯 while 循环实现第一版。循环体内核心逻辑拆成 `step_*` 独立函数，后续可迁移到 LangGraph 节点 |
| 2 | State 拆分 | `SessionState`（跨轮持久，可序列化）+ `TurnContext`（单轮临时，运行时不持久化） |
| 3 | Pre-flight 边界 | 只放 3 种场景：① pending 确认短路 ② 确定性认证短路 ③ 构建 state_summary 注入上下文。intent/slot/reason 全部交给 LLM |
| 4 | Prompt 维护 | 一个大文件 + 模板变量（`{tool_catalog}`、`{policy}`、`{state_summary}`） |
| 5 | Eval 适配 | 保留所有 DB 断言。放宽工具调用：精确序列 → 必需工具集合。放宽回复：精确包含 → 关键词包含 |
| 6 | Runtime / Harness 边界 | Runtime 只保留 LLM tool-calling 一条路径。Deterministic 能力下沉到测试、eval、CI harness |

## Runtime / Harness 边界

核心原则：**Runtime 单一，Harness 多样**。

生产 runtime 只保留一条路径：

```
pre-flight → agent loop → gateway/guard → post-processing
```

不保留旧 12-node deterministic pipeline，也不保留 `--mode deterministic` 作为同级运行模式。旧 pipeline、plan handlers、LangGraph 线性编排在新架构稳定后删除，不作为 LLM 故障时的 fallback。

Deterministic 能力只存在于 harness 层：

| Harness | 第一阶段 | 用途 |
|---------|----------|------|
| `ScriptedToolCallingProvider` | 必做 | 按脚本返回固定 assistant text / tool calls，保证 agent loop 单测和 CI 稳定 |
| `FakeFailingProvider` | 必做 | 模拟 timeout、unknown tool、malformed JSON、missing args、连续失败 |
| `TraceReplayHarness` | 后续 | 从 trace artifact 回放单轮上下文和工具结果，用于调试和回归分析 |

CI / Eval 分层：

| 场景 | 后端 | 是否调用真实 LLM | 目标 |
|------|------|------------------|------|
| 常规 CI | `scripted` / fake provider | 否 | 验证架构契约、安全边界、loop 行为、eval adapter |
| 手动 eval | `live` | 是 | 验证真实模型能力、prompt 质量、支持率 |
| Nightly benchmark | `live` | 是 | 观察趋势：成功率、tool calls、token、延迟、失败类别 |
| Release smoke | `live` 小集合 | 是 | 发布前验证关键 happy path 和危险写操作边界 |

Eval report 必须标记 backend：`scripted`、`live`，后续可加 `replay`。

## 新架构总览

```
用户消息
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│                   Code Pre-Flight                        │
│                                                         │
│  1. pending action? → ConfirmationResolver 处理          │
│     confirm → 直接 gateway.execute，跳过 LLM              │
│     deny/changed → 直接回复，跳过 LLM                     │
│                                                         │
│  2. 消息中有明确的 email 或 name+zip?                      │
│     → code 直接调 find_user_id_by_* 认证                  │
│     → 跳过 LLM 的身份识别步骤                              │
│                                                         │
│  3. 构建 state_summary（压缩上下文）注入 LLM               │
│                                                         │
│  不做的事: intent 推断、slot 提取、reason 映射、策略判断     │
│  全部交给 LLM                                            │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                 LLM Agent Loop                           │
│                                                         │
│  System: 单文件大 Prompt（角色 + 工具 + policy + 护栏）    │
│  Messages: 对话历史 + state_summary                      │
│                                                         │
│  while 循环，每次迭代：                                    │
│    response = LLM.chat_with_tools(messages, tools)        │
│    ↓                                                     │
│    无 tool_call → LLM 回复用户，loop 结束                  │
│    有 tool_call → gateway.execute → 结果喂回 LLM          │
│    guard 要求确认 → 设 pending，返回确认提示，loop 结束      │
│                                                         │
│  核心逻辑拆成 step_* 独立函数，后续可换 LangGraph           │
│  超过 max_iterations → code 兜底文案                      │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  Code Post-Processing                    │
│                                                         │
│  - step 记录 + step_durations                           │
│  - audit_log 写入                                       │
│  - trace artifact 输出                                  │
│  - eval result 对比                                     │
└─────────────────────────────────────────────────────────┘
```

## State 模型

```
SessionState（跨轮持久，可序列化）
  ├─ session_id: str
  ├─ task_id: str | None
  ├─ authenticated_user_id: str | None
  ├─ auth_method: str | None
  ├─ messages: list[Message]           # 完整对话历史
  ├─ loaded_context: LoadedContext     # DB 缓存（跨轮复用，不清空）
  ├─ tool_results: list[ToolCallRecord]
  ├─ write_locks: list[str]
  ├─ audit_logs: list[dict]
  └─ pending_action: PendingAction | None  # 等待下轮确认

TurnContext（单轮临时，运行时对象，不序列化）
  ├─ steps: list[TurnStep]            # 本轮决策轨迹
  ├─ step_durations: dict
  ├─ llm_call_durations: list[dict]
  ├─ llm_token_usage: dict | None     # 本轮 token 消耗
  └─ termination: str | None          # 本轮如何结束
```

**去除的字段**（新架构不再需要）：
- `current_intent` — LLM 内部推理，不暴露为 state
- `slots` — LLM 自主提取参数
- `policy_decision` — LLM 自主判断，guard 做最终检查
- `confirmation_status` — 由 `pending_action` 存在与否表达
- `risk_level` — 由 action_specs 决定

## Pre-flight 边界

**放进 pre-flight 的三种场景**：

| 场景 | 触发条件 | 处理 | 节省 |
|------|---------|------|------|
| 确认短路 | `pending_action` 存在 + `ConfirmationResolver` 能确定判定 | confirm → 直接 gateway；deny/changed → 直接回复 | 1-2 次 LLM 调用 |
| 认证短路 | 消息中有明确的 email 或 name+zip | code 直接调 `find_user_id_by_*` | 1 次 LLM tool-call 往返 |
| 信息注入 | 每条消息 | 构建 `state_summary`，告诉 LLM 已认证用户、已加载订单、已有锁 | LLM 不需要再查 |

**不放 pre-flight 的**：
- intent 推断 → LLM 自己理解
- slot 提取 → LLM 自己从消息中提取
- reason 映射（"不太想要了" → "no longer needed"）→ LLM 自己做
- 策略判断 → LLM 对照 policy 自己做（guard 兜底）
- 订单号正则 → LLM 完全能识别 `#W5918442`

## Code 的安全兜底：三层防线

```
═══════════════════════════════════════════════════════════════
防线 1: Tool Call 执行前 — Gateway + Guard
═══════════════════════════════════════════════════════════════
LLM 的任何 tool call 都必须经过 ToolGateway.execute()
  - tool_name 不在 registry → 拒绝（LLM 幻觉拦截）
  - 写工具 → WriteActionGuard.check()（7 层不变）
  - guard block → 返回结构化 context，喂回 LLM 让它解释
  - explicit_confirmation_required → 设 pending，退出 loop

═══════════════════════════════════════════════════════════════
防线 2: LLM Loop 内 — 迭代上限 + 连续失败保护
═══════════════════════════════════════════════════════════════
  - max_iterations = 5：超过后 code 强制终止，给兜底回复
  - 连续 3 次 tool call 失败 → code 中断，避免死循环
  - try/except 包裹 LLM 调用：API 错误 → 重试或降级

═══════════════════════════════════════════════════════════════
防线 3: LLM 完全故障 — 安全失败 / 转人工
═══════════════════════════════════════════════════════════════
  - provider 不可用 → 安全失败或转人工
  - 不降级到旧 deterministic pipeline
  - 写操作在 LLM 故障时绝不执行
═══════════════════════════════════════════════════════════════
```

## LLM 故障与 Tool Call 错误策略

LLM/provider 故障时采用**安全失败，不旧路代跑**：

- provider timeout / unavailable → 返回暂时无法处理，或转人工
- malformed tool call / unknown tool / missing args → 先作为结构化 tool error 喂回 LLM，让 LLM 自修正
- 单轮连续 tool-call 失败最多 3 次，超过阈值后中断并转人工
- 写操作必须同时满足：合法 tool call、参数 schema 通过、gateway/guard allow、用户显式确认
- 任一条件不满足，写工具不执行

结构化 tool error 的最小字段：

```python
ToolExecutionError:
    status: Literal["error"]
    error_type: Literal[
        "unknown_tool",
        "malformed_arguments",
        "missing_required_args",
        "tool_execution_error",
        "guard_blocked",
    ]
    message_for_llm: str
    retryable: bool
    missing_args: list[str]
    allowed_tools: list[str] | None
```

未知工具、参数解析失败、缺 required 参数不应直接抛出到 runtime 顶层；它们应该进入 agent loop，作为 tool observation 反馈给 LLM。只有连续失败超过阈值，runtime 才安全中断。

## Pending Confirmation 协议

`pending_action` 只保存**候选动作**，不保存“guard 已通过”状态。

```python
PendingAction:
    tool_name: str
    arguments: dict
    user_facing_summary: str
    created_from_tool_call_id: str | None
```

流程：

1. LLM 发起写工具调用。
2. `gateway.execute(..., confirmed=False)` 进入 guard。
3. guard 返回 `explicit_confirmation_required`。
4. agent 设置 `pending_action`，向用户输出确认问题，loop 结束。
5. 下一轮用户明确确认后，pre-flight 短路调用 `gateway.execute(..., confirmed=True)`。
6. guard 重新校验认证、ownership、read-before-write、policy、lock、idempotency。
7. 只有重新校验通过，才执行写工具。

这样即使确认前后 session state、DB、write lock 发生变化，也不会执行过期或不再合法的写操作。

## System Prompt

一个大文件，code 做模板变量替换：

```markdown
# {prompt_file_content}   ← 来自 prompts/llm_agent_system_v001.md

# Available Tools
{tool_catalog}            ← code 从 registry 自动生成 OpenAI function calling JSON schema

# Retail Policy
{policy}                   ← code 从 policy.md 加载

# Current Session State
{state_summary}            ← code 运行时构建，压缩版
```

## Tool Schema 生成

从 `action_specs.py` + `retail_adapter.py` 的已有定义自动派生 17 个工具的 OpenAI function calling schema：

```python
def tool_schemas_for_llm(self) -> list[dict]:
    """所有 tool schema 自动派生，无手写硬编码"""
    ...
```

Schema 生成要求：

- 使用真正的 JSON Schema，不只生成文本 catalog
- 每个工具包含 `name`、`description`、`parameters`
- `required` 来自 function signature 或 `action_specs.py`
- enum 约束显式写入 schema，例如：
  - `reason`: `"no longer needed" | "ordered by mistake"`
  - `shipping_method`: `"standard" | "express" | "overnight"`
- list 参数必须声明 item type，例如 `item_ids: array[string]`
- 默认 `additionalProperties: false`
- schema 生成测试要校验 registry 中所有工具都能生成 schema，且 prompt/tool catalog 中没有不存在的工具名

## Tool Calling Provider Contract

`LLMProvider` 新增 tool-calling 接口：

```python
class LLMProvider(Protocol):
    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> ToolCallResponse: ...
```

标准响应结构：

```python
ToolCallResponse:
    assistant_content: str | None
    tool_calls: list[ToolCallRequest]
    finish_reason: str | None
    token_usage: dict | None
    raw: dict | None

ToolCallRequest:
    id: str
    tool_name: str
    arguments: dict
    raw_arguments: str | None
```

Provider adapter 负责把 DeepSeek/OpenAI 返回格式归一化到上述结构。`raw_arguments` 保留原始字符串，用于 trace 和 malformed arguments 调试。

## Eval 适配

| 字段 | 变更 |
|------|------|
| `expected_intent` | **废弃** — LLM 不输出 intent |
| `expected_tool_names` → `required_tools: set[str]` | **放宽** — 从精确序列变成必需工具集合 |
| `expected_tool_sequence` | **废弃** — LLM 可能调不同顺序 |
| `expected_write_lock` | 不变 |
| `expected_order_status` | 不变 |
| `expected_no_write` | 不变 |
| `expected_db_assertions` | 不变 |
| `expected_assistant_contains` | **放宽** — 从精确包含变成"必须包含的关键词" |
| `expected_confirmation_status` | 不变（由 `pending_action` 推导） |

新增 LLM 专属指标：

```python
EvalCaseResult:
    llm_tool_call_count: int       # LLM 总共发起多少次 tool call
    llm_token_usage: dict | None    # prompt + completion tokens
    llm_loop_iterations: int        # agent loop 迭代次数
    eval_backend: str               # scripted | live | replay
```

负向断言继续保留：

- `expected_no_write` 仍然是强断言
- 可新增 `forbidden_tools: set[str]`，用于禁止危险或不应出现的工具调用
- DB 断言优先级高于回复文本断言
- live LLM eval 的失败不直接等同于代码回归，需要在 report 中归类为 code / prompt / model / provider / data / policy / unknown

## Context Summary 与 Trace

`state_summary` 是 token 优化的核心契约，必须稳定、短、可测试。

建议第一版预算：

- `state_summary` 目标不超过 1200 tokens
- 最近对话窗口保留最近 6 条 user/assistant 消息
- tool observation 默认只保留摘要，不把完整 DB 对象反复塞给 LLM
- 已认证用户只暴露必要字段：user_id、姓名、email 摘要、地址摘要、payment method 摘要
- 已加载订单只暴露：order_id、status、user_id、items 摘要、shipping/payment 摘要、可写性提示
- `write_locks`、`pending_action`、最近 guard block 必须进入 summary

`TurnContext` 不进入跨轮 session 序列化，但必须进入 trace artifact。trace 至少记录：

- 本轮 steps
- LLM calls 和 token usage
- tool call request / result / error
- pending action 创建和确认结果
- termination reason
- eval backend

## 核心保留模块

| 模块 | 原因 |
|------|------|
| `app/agent/guard.py` | 7 层护栏逻辑不变。扩展 `WriteActionGuardResult.block_context` |
| `app/agent/action_specs.py` | 写操作注册表不变。新增 `build_tool_schema_for_llm()` |
| `app/tools/gateway.py` | 执行入口保留，但需把 unknown tool / malformed args 归一化为结构化错误 |
| `app/tools/retail_adapter.py` | 工具函数实现不变 |
| `app/agent/confirmation.py` | ConfirmationResolver 不变，用于 pre-flight 确认短路 |
| `app/ops/tracing.py` | Trace 写入不变 |
| `app/synthetic/` | 不变 |
| `app/workbench/` | 不变 |

## 可以删除 / 精简的模块

| 模块 | 变更 |
|------|------|
| `app/agent/pipeline.py` (445 行) | **删除** — 12 节点逻辑不再需要。`conversation_gate` 确认处理移到 pre-flight |
| `app/agent/plan_handlers.py` (277 行) | **删除** — 8 个 intent 的 plan handler 由 LLM 替代 |
| `app/agent/graph.py` (63 行) | **删除** — LangGraph 编排不再需要。保留 LangGraph 迁移口子在 llm_agent 的 `step_*` 函数 |
| `app/agent/parsers.py` (277 行) | **精简** — 只保留 `EMAIL_RE`、`NAME_ZIP_RE`、`ConfirmationResolver`、`clean_llm_*`。删除 `infer_intent`、`parse_address`、`parse_item_replacement_pairs`、`parse_shipping_method`、`code_missing_slots`、`merge_policy_decisions` |
| `app/agent/builders.py` (96 行) | **精简** — `merge_slots`、`pending_action_has_required_args`、`normalize_llm_action_arguments` 不再需要 |

## 新增模块

| 模块 | 职责 |
|------|------|
| `app/agent/llm_agent.py` | while 循环 + `step_*` 独立函数（LLM 调用、tool 执行、结果处理、pending 设置）|
| `app/agent/context_builder.py` | `state_summary` 构建、对话历史压缩、读工具结果摘要化 |
| `prompts/llm_agent_system_v001.md` | 一个大文件，含角色定义 + 行为指南 + 护栏说明 |

## 改动的模块

| 模块 | 变更 |
|------|------|
| `app/agent/models.py` | `ConversationState` → `SessionState` + `TurnContext`。去掉 `current_intent`、`slots`、`policy_decision`、`confirmation_status`、`risk_level` |
| `app/agent/runtime.py` | `handle_user_message()` 改为 pre-flight → LLM loop → post-processing。删除 `--mode deterministic` 运行时 |
| `app/tools/registry.py` | 新增 `tool_schemas_for_llm()` 生成 OpenAI function calling schema |
| `app/agent/providers.py` | `LLMProvider` protocol 新增 `chat_with_tools(messages, tools)` 方法。`DeepSeekProvider` 实现 |
| `app/eval/runner.py` | EvalCaseResult 新增 LLM 专属指标 |
| `app/eval/cases.py` | `EvalCase` 新增 `required_tools: set[str]`（替代 `expected_tool_names` 的严格顺序匹配）|

## 实施步骤

### Step 1：Provider + Registry + Harness 扩展（不改 runtime 主路径）

- `LLMProvider` protocol 新增 `chat_with_tools(messages, tools) -> ToolCallResponse`
- `ToolRegistry` 新增 `tool_schemas_for_llm()` 生成 OpenAI function calling schema
- `DeepSeekProvider` 实现 `chat_with_tools()`
- 新增 `ScriptedToolCallingProvider`
- 新增 `FakeFailingProvider`
- 验证：现有 228 tests 绿色，全部 eval case 通过

### Step 2：State 拆分 + 新增 llm_agent 模块

- `ConversationState` → `SessionState` + `TurnContext`
- 新增 `app/agent/llm_agent.py`（while 循环 + `step_*` 独立函数）
- 新增 `app/agent/context_builder.py`（state_summary + 对话压缩）
- 新增 `prompts/llm_agent_system_v001.md`
- 单元测试覆盖：loop 正常结束、loop 超上限、LLM 异常、guard block、unknown tool、malformed args、连续失败
- 验证：scripted harness 下 smoke case 通过

### Step 3：AgentRuntime 切换到单 LLM Runtime

- `handle_user_message()` 改为 pre-flight → LLM loop → post-processing
- 删除 `--mode deterministic` 作为运行时模式
- provider 不可用时安全失败或转人工，不走旧 pipeline
- 验证：scripted backend 下 curated_mvp + generalized_mvp + synthetic 通过

### Step 4：Guard 结构化 context + 清理旧 Runtime

- `WriteActionGuardResult` 新增 `block_context: dict`
- 删除 `pipeline.py`、`plan_handlers.py`、`graph.py`
- 精简 `parsers.py`、`builders.py`
- 确认 `pending_action` confirm 后重新跑 guard

### Step 5：Token 优化迭代 + Eval 适配

- `EvalCase` 适配：`required_tools`、`forbidden_tools`、放宽 `expected_assistant_contains`
- `EvalCaseResult` 增加 `eval_backend`
- `state_summary` 压缩比例调优
- 对话历史窗口裁剪
- 读工具结果摘要化
- tau_retail_supported 基准测试：目标 32/69 → 55+/69

### Step 6：Live Eval 与 Replay 增强（后续）

- live LLM eval 手动或 nightly 跑，不进常规 CI
- eval report 增加失败归因
- 设计并实现 `TraceReplayHarness`
