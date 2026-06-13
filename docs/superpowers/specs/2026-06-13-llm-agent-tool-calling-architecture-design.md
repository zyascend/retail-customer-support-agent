# LLM Agent Tool-Calling Architecture — Design Spec

日期：2026-06-13
状态：待评审

## 目标

将当前 retail customer support agent 从 12-node deterministic pipeline 重构为 LLM tool-calling agent。

新架构以 LLM 决策为主，让模型根据对话上下文、工具 schema、retail policy 和 session summary 自主选择工具与参数；code 只负责不可绕过的安全边界、token 优化、运行账本、trace、eval 和测试 harness。

核心原则：

> Runtime 单一，Harness 多样。

生产 runtime 只保留 LLM tool-calling 一条路径。旧 12-node deterministic pipeline 不作为并行模式，也不作为 LLM 故障 fallback。deterministic 能力下沉到测试、CI、eval harness。

## 背景

Phase 9 完成 full tau ingestion 后，当前系统支持 69 个 tau retail supported task 中的 32 个。现有架构依赖 code 正则提取 intent / slot，并硬编码路由到 plan handler。LLM 只在 intent slot、policy、action plan、response generation 等环节做语义补充，不能改变 code 的核心决策。

这种架构对新增场景不够自然：

- intent 和 slot 枚举会持续膨胀
- 多轮对话中用户表达变化需要大量 parser patch
- LLM 已经能理解上下文，但最终决策仍被 code pipeline 限制
- eval 支持率提升越来越依赖硬编码分支

新架构目标是把“理解和决策”交给 LLM，把“安全和执行”留给 code。

## 非目标

- 不保留 `--mode deterministic` runtime。
- 不保留旧 12-node pipeline 作为 provider 不可用时的 fallback。
- 不在第一阶段实现 `TraceReplayHarness`。
- 不引入 LangGraph 作为第一版 runtime。
- 不让 LLM 直接绕过 `ToolGateway` 或 `WriteActionGuard` 执行写操作。
- 不把 live LLM eval 放入常规 CI gate。
- 不在本阶段新增 Dashboard 或 Workbench UI。

## 架构决策

| # | 决策项 | 结论 |
|---|--------|------|
| 1 | Runtime 形态 | 使用 plain while loop。循环体拆成 `step_*` 函数，保留未来迁移 LangGraph 的边界 |
| 2 | Runtime / Harness | Runtime 单一，Harness 多样。生产只保留 LLM tool-calling 路径 |
| 3 | State 模型 | 拆成 `SessionState` + `TurnContext` |
| 4 | Pre-flight 边界 | 只做 pending confirmation、确定性认证、state summary 注入 |
| 5 | Prompt 维护 | 单文件 system prompt + 模板变量 |
| 6 | Tool schema | 从 registry / action specs 自动生成 JSON Schema |
| 7 | Safety | 所有 tool call 必须经过 gateway。所有写工具必须经过 guard |
| 8 | Eval | DB 断言强保留。工具顺序断言改为 required / forbidden tool 集合 |

## Runtime 总览

```
user message
  │
  ▼
pre-flight
  ├─ pending confirmation short-circuit
  ├─ deterministic identity shortcut
  └─ state_summary build
  │
  ▼
LLM agent loop
  ├─ step_llm_reason()
  ├─ step_tool_execute()
  ├─ step_pending()
  └─ step_finalize()
  │
  ▼
post-processing
  ├─ session state update
  ├─ turn context trace
  ├─ audit log
  └─ eval metrics
```

## Runtime / Harness 边界

生产 runtime 只保留一条路径：

```
pre-flight → agent loop → gateway/guard → post-processing
```

删除旧 runtime 形态：

- `app/agent/pipeline.py`
- `app/agent/plan_handlers.py`
- `app/agent/graph.py`
- `--mode deterministic`

Deterministic 能力只在 harness 层保留。

| Harness | 第一阶段 | 用途 |
|---------|----------|------|
| `ScriptedToolCallingProvider` | 是 | 按脚本返回固定 assistant text / tool calls，用于单测、CI、eval smoke |
| `FakeFailingProvider` | 是 | 模拟 timeout、unknown tool、malformed arguments、missing args、连续失败 |
| `TraceReplayHarness` | 否 | 后续从 trace artifact 回放上下文和工具结果 |

CI / eval 分层：

| 场景 | 后端 | 调用真实 LLM | 用途 |
|------|------|--------------|------|
| 常规 CI | `scripted` / fake provider | 否 | 稳定验证架构契约和安全边界 |
| 手动 eval | `live` | 是 | 验证真实模型能力、prompt 质量、支持率 |
| Nightly benchmark | `live` | 是 | 跟踪成功率、token、延迟、失败类别 |
| Release smoke | `live` 小集合 | 是 | 发布前验证关键路径 |

Eval report 必须记录 `eval_backend`：`scripted`、`live`，后续可加 `replay`。

## State 模型

### SessionState

跨轮持久，可序列化。只保存会影响后续轮次的事实、缓存和安全账本。

```python
class SessionState(BaseModel):
    session_id: str
    task_id: str | None = None
    authenticated_user_id: str | None = None
    auth_method: str | None = None
    active_user_identity: dict[str, Any] = Field(default_factory=dict)
    messages: list[Message] = Field(default_factory=list)
    loaded_context: LoadedContext = LoadedContext()
    tool_results: list[ToolCallRecord] = Field(default_factory=list)
    write_locks: list[str] = Field(default_factory=list)
    audit_logs: list[dict[str, Any]] = Field(default_factory=list)
    pending_action: PendingAction | None = None
    termination_reason: str | None = None
```

### TurnContext

单轮临时对象，不进入跨轮 session 序列化，但进入 trace artifact。

```python
class TurnContext(BaseModel):
    steps: list[TurnStep] = Field(default_factory=list)
    step_durations: dict[str, float] = Field(default_factory=dict)
    llm_call_durations: list[dict[str, Any]] = Field(default_factory=list)
    llm_token_usage: dict[str, Any] | None = None
    loop_iterations: int = 0
    consecutive_tool_failures: int = 0
    termination: str | None = None
```

### 删除字段

这些字段不再属于持久 state：

- `current_intent`
- `slots`
- `policy_decision`
- `confirmation_status`
- `risk_level`

LLM 的中间推理不写入 state。runtime 只记录可审计的 tool calls、tool results、guard decisions 和 final response。

## Pre-flight

Pre-flight 只做三类确定性工作。

| 场景 | 触发条件 | 行为 |
|------|----------|------|
| Pending confirmation | `pending_action` 存在，且 `ConfirmationResolver` 明确判定 confirm / deny / changed | confirm 直接调用 `gateway.execute(..., confirmed=True)`；deny / changed 直接清空 pending 并回复 |
| Identity shortcut | 用户消息中有明确 email 或 name + zip | code 直接调用 `find_user_id_by_email` 或 `find_user_id_by_name_zip` |
| State summary | 每轮都执行 | 构建压缩上下文注入 LLM |

Pre-flight 不做：

- intent 推断
- slot 提取
- cancel reason 映射
- order id 正则提取
- policy 判断
- tool selection

这些都交给 LLM 和 tool schema / guard 共同处理。

## LLM Agent Loop

`app/agent/llm_agent.py` 提供 while loop 和可迁移到 LangGraph 的 `step_*` 函数。

```python
def run_llm_agent_turn(
    *,
    session: SessionState,
    content: str,
    provider: LLMProvider,
    gateway: ToolGateway,
    registry: ToolRegistry,
    context_builder: ContextBuilder,
    max_iterations: int = 5,
) -> AgentTurnResult:
    ...
```

Step 函数：

| 函数 | 职责 |
|------|------|
| `step_llm_reason()` | 调用 `provider.chat_with_tools()`，归一化 response |
| `step_tool_execute()` | 校验 tool call，调用 gateway，写入 tool observation |
| `step_pending()` | guard 要求确认时设置 `pending_action` 并结束本轮 |
| `step_finalize()` | 无 tool call 时写入 assistant response 并结束本轮 |

Loop 终止条件：

- LLM 返回 final assistant text，且没有 tool call
- guard 要求 explicit confirmation，pending 已设置
- pre-flight 已短路处理 pending confirmation
- 超过 `max_iterations = 5`
- 连续 tool-call 失败达到 3 次
- provider timeout / unavailable

## Provider Contract

`LLMProvider` 新增 tool-calling 方法。

```python
class LLMProvider(Protocol):
    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ToolCallResponse: ...
```

标准响应结构：

```python
class ToolCallResponse(BaseModel):
    assistant_content: str | None = None
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    finish_reason: str | None = None
    token_usage: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None

class ToolCallRequest(BaseModel):
    id: str
    tool_name: str
    arguments: dict[str, Any]
    raw_arguments: str | None = None
```

`DeepSeekProvider` 负责把 provider-specific response 归一化成上述结构。`raw_arguments` 保留原始字符串，用于 trace 和 malformed argument 调试。

## Tool Schema

`ToolRegistry.tool_schemas_for_llm()` 从 registry、function signature、`action_specs.py` 自动生成 OpenAI-compatible JSON Schema。

要求：

- 所有 registry tools 都能生成 schema。
- schema 包含 `name`、`description`、`parameters`。
- `required` 来自 function signature 或 write action spec。
- list 参数声明 item type。
- enum 显式声明，例如 cancellation reason、shipping method。
- 默认 `additionalProperties: false`。
- schema 生成测试校验 schema tool names 与 registry 一致。

示例：

```python
{
    "type": "function",
    "function": {
        "name": "cancel_pending_order",
        "description": "Cancel a pending order after user confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "reason": {
                    "type": "string",
                    "enum": ["no longer needed", "ordered by mistake"],
                },
            },
            "required": ["order_id", "reason"],
            "additionalProperties": False,
        },
    },
}
```

## Gateway 与 Guard

所有 tool calls 必须经过 `ToolGateway.execute()`。

Gateway 职责：

- unknown tool → 结构化 tool error
- malformed arguments → 结构化 tool error
- missing required args → 结构化 tool error
- read / generic tool → 执行并记录 result
- write tool → 调用 `WriteActionGuard.check()`

Guard 职责保持不可绕过：

- authentication required
- ownership validation
- read-before-write validation
- retail policy validation
- duplicate write lock validation
- idempotency key generation
- resource lock generation
- explicit confirmation requirement

`WriteActionGuardResult` 新增 `block_context`，用于给 LLM 解释 block 原因。

```python
class WriteActionGuardResult:
    allowed: bool
    block_reason: str | None
    missing_requirements: list[str]
    required_user_confirmation: bool
    risk_level: str
    normalized_action: ToolCall | None
    user_facing_summary: str | None
    idempotency_key: str | None
    resource_lock: str | None
    block_context: dict[str, Any]
```

## Tool Error Contract

未知工具、参数错误、缺参数、tool execution error、guard block 都返回结构化 observation，不直接让 runtime 崩溃。

```python
class ToolExecutionError(BaseModel):
    status: Literal["error"] = "error"
    error_type: Literal[
        "unknown_tool",
        "malformed_arguments",
        "missing_required_args",
        "tool_execution_error",
        "guard_blocked",
    ]
    message_for_llm: str
    retryable: bool
    missing_args: list[str] = Field(default_factory=list)
    allowed_tools: list[str] | None = None
```

LLM 每轮可以根据 tool error 自修正。单轮连续失败最多 3 次，超过后 runtime 安全失败或转人工。

## Pending Confirmation 协议

`pending_action` 只保存候选动作，不保存“guard 已通过”状态。

```python
class PendingAction(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    user_facing_summary: str
    created_from_tool_call_id: str | None = None
```

流程：

1. LLM 发起写工具调用。
2. Gateway 调用 guard，`confirmed=False`。
3. guard 返回 `explicit_confirmation_required`。
4. agent 设置 `pending_action`，向用户输出确认问题，本轮结束。
5. 用户下一轮明确确认。
6. Pre-flight 调用 `gateway.execute(..., confirmed=True)`。
7. guard 重新校验认证、ownership、read-before-write、policy、lock、idempotency。
8. 校验通过才执行写工具。

如果用户 deny 或 changed：

- 清空 `pending_action`
- 不执行写工具
- changed 时让 LLM 在下一轮重新理解新请求

## Context Builder

新增 `app/agent/context_builder.py`。

职责：

- 构建 `state_summary`
- 裁剪对话历史
- 摘要化 tool observations
- 摘要 loaded context
- 给 prompt 注入 pending action、write locks、最近 guard block

第一版预算：

- `state_summary` 目标不超过 1200 tokens
- 最近对话窗口保留最近 6 条 user / assistant 消息
- tool observation 默认摘要化，不重复塞完整 DB 对象
- user summary 只暴露必要字段：user_id、姓名、email 摘要、地址摘要、payment method 摘要
- order summary 只暴露：order_id、status、user_id、items 摘要、shipping/payment 摘要、可写性提示
- `write_locks`、`pending_action`、最近 guard block 必须进入 summary

## System Prompt

新增 `prompts/llm_agent_system_v001.md`，使用单文件 prompt。

Runtime 注入变量：

```markdown
# Available Tools
{tool_catalog}

# Retail Policy
{policy}

# Current Session State
{state_summary}
```

Prompt 约束：

- LLM 必须使用工具读取订单或用户信息，不得凭空编造 DB 状态。
- 写操作必须先读取相关 resource，再请求确认。
- guard block 时，LLM 应向用户解释可行动的下一步。
- provider/tool failure 时，LLM 不应声称操作已完成。
- 对危险写操作，最终执行前必须有明确用户确认。

Prompt 测试：

- 所有模板变量被替换。
- prompt 中不存在未知 tool name。
- tool schema 与 prompt catalog 一致。

## Runtime 集成

`AgentRuntime.handle_user_message()` 改为：

```python
def handle_user_message(self, state: SessionState, content: str) -> str:
    state.messages.append(Message(role="user", content=content))
    turn = TurnContext()

    preflight = self.preflight.handle(state, content, turn)
    if preflight.handled:
        self.post_process(state, turn)
        return preflight.assistant_message

    result = run_llm_agent_turn(
        session=state,
        content=content,
        provider=self.provider,
        gateway=self.gateway,
        registry=self.registry,
        context_builder=self.context_builder,
    )

    self.post_process(state, result.turn)
    return result.assistant_message
```

Provider 不可用时：

- 不走旧 pipeline
- 不执行写工具
- 返回安全失败文案或转人工

## Eval 适配

`EvalCase` 调整：

```python
class EvalCase(BaseModel):
    required_tools: set[str] = Field(default_factory=set)
    forbidden_tools: set[str] = Field(default_factory=set)
    expected_no_write: bool = False
    expected_db_assertions: list[DBAssertion] = Field(default_factory=list)
    expected_assistant_keywords: list[str] = Field(default_factory=list)
```

废弃或弱化：

- `expected_intent`
- `expected_tool_sequence`
- 精确 `expected_tool_names`
- 精确 `expected_assistant_contains`

`EvalCaseResult` 新增：

```python
class EvalCaseResult(BaseModel):
    llm_tool_call_count: int = 0
    llm_token_usage: dict[str, Any] | None = None
    llm_loop_iterations: int = 0
    eval_backend: Literal["scripted", "live", "replay"]
    failure_category: str | None = None
```

DB 断言和 `expected_no_write` 仍是强断言。`forbidden_tools` 用于防止 LLM 多调用危险工具。

Live LLM eval 失败需要归类：

- `code`
- `prompt`
- `model`
- `provider`
- `data`
- `policy`
- `unknown`

## Trace 与 Observability

`TurnContext` 不进入跨轮 session 序列化，但必须进入 trace artifact。

Trace 至少记录：

- messages window
- rendered state summary
- LLM calls
- token usage
- tool call requests
- tool results / tool errors
- guard results
- pending action created / cleared / confirmed
- termination reason
- eval backend

写操作 audit log 保持 code 负责，不能由 LLM 生成。

## 文件变更

### 新增

```
app/agent/llm_agent.py
app/agent/context_builder.py
prompts/llm_agent_system_v001.md
```

Provider / harness 可放在现有 `app/agent/providers.py`，或后续拆分为：

```
app/agent/tool_calling.py
app/agent/harness.py
```

### 修改

```
app/agent/models.py
app/agent/runtime.py
app/agent/providers.py
app/agent/guard.py
app/tools/gateway.py
app/tools/registry.py
app/eval/cases.py
app/eval/runner.py
app/ops/tracing.py
```

### 删除 / 精简

```
app/agent/pipeline.py
app/agent/plan_handlers.py
app/agent/graph.py
app/agent/parsers.py
app/agent/builders.py
```

其中 `pipeline.py`、`plan_handlers.py`、`graph.py` 删除。`parsers.py`、`builders.py` 精简，而不是必须删除整个文件：只保留 pre-flight 需要的 deterministic helpers，例如 email、name+zip、confirmation resolver 相关能力。若 `ConfirmationResolver` 已在 `confirmation.py` 中，则不再从 parser 暴露。

## 实施切片

### Slice 1：Provider、Tool Schema、Harness

- 定义 `ToolCallResponse`、`ToolCallRequest`
- `LLMProvider` 新增 `chat_with_tools`
- `DeepSeekProvider` 实现 tool-calling adapter
- `ToolRegistry` 新增 `tool_schemas_for_llm`
- 新增 `ScriptedToolCallingProvider`
- 新增 `FakeFailingProvider`

验证：

- schema 覆盖所有 registry tools
- fake provider 可模拟 final text、tool call、timeout、malformed args
- 现有 tests 仍通过

### Slice 2：State 与 Context Builder

- `ConversationState` 拆为 `SessionState` + `TurnContext`
- 更新 trace serialization
- 新增 `ContextBuilder`
- 增加 state summary 单测

验证：

- summary 包含 auth、loaded context、write locks、pending action
- summary 不包含完整大 DB 对象
- trace 记录 turn context

### Slice 3：LLM Agent Loop

- 新增 `llm_agent.py`
- 实现 `step_llm_reason`
- 实现 `step_tool_execute`
- 实现 `step_pending`
- 实现 `step_finalize`
- 实现 max iterations 和 consecutive failures

验证：

- scripted happy path
- read tool path
- write requires confirmation path
- guard block path
- unknown tool self-correction path
- failure threshold path

### Slice 4：Runtime 切换与旧 Runtime 删除

- `AgentRuntime.handle_user_message` 切到新 runtime
- 删除 `--mode deterministic`
- provider 不可用时安全失败或转人工
- 删除旧 pipeline / plan handlers / graph
- 精简 parsers / builders

验证：

- scripted backend 下 curated / generalized / synthetic smoke 通过
- no API key 时不会执行写操作
- pending confirmation 仍可跨轮执行

### Slice 5：Eval 与 Live Benchmark

- `EvalCase` 新增 `required_tools`、`forbidden_tools`
- `EvalCaseResult` 新增 LLM metrics 和 `eval_backend`
- report 区分 scripted / live
- live eval 作为手动或 nightly，不进常规 CI

验证：

- scripted CI 稳定
- live tau_retail_supported 目标从 32/69 提升到 55+/69
- report 能输出 token、tool count、loop iterations、failure category

## 测试计划

单元测试：

- provider response normalization
- tool schema generation
- context builder summary
- pre-flight pending confirmation
- pre-flight identity shortcut
- agent loop final response
- agent loop tool execution
- guard confirmation pending
- confirm 后重新跑 guard
- unknown tool error
- malformed arguments error
- missing required args error
- consecutive failures threshold
- provider timeout safe failure

集成测试：

- scripted happy path order lookup
- scripted pending order cancellation
- scripted deny confirmation
- scripted changed confirmation
- scripted guard block explanation
- scripted no-write safety case

Eval：

- existing curated_mvp
- generalized_mvp
- synthetic
- tau_retail_smoke scripted
- tau_retail_supported live manual / nightly

## 验收标准

- [ ] 生产 runtime 不再包含 `--mode deterministic`
- [ ] 旧 pipeline 不作为 LLM/provider 故障 fallback
- [ ] 常规 CI 不调用真实 LLM API
- [ ] `ScriptedToolCallingProvider` 和 `FakeFailingProvider` 可用于稳定单测
- [ ] 所有 tool schemas 从 registry/action specs 自动生成
- [ ] unknown tool / malformed args / missing args 返回结构化 tool error
- [ ] 连续 tool-call 失败 3 次后安全失败或转人工
- [ ] 写工具必须经过 gateway + guard + explicit confirmation
- [ ] pending confirmation 后重新跑 guard
- [ ] `state_summary` 有预算并进入 prompt
- [ ] `TurnContext` 进入 trace artifact
- [ ] eval report 标记 `eval_backend`
- [ ] scripted CI 通过现有核心 case
- [ ] live tau_retail_supported 目标达到 55+/69
- [ ] `uv run python -m pytest tests/ -q` 通过
- [ ] `uv run ruff check .` 通过

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| LLM tool call 不稳定 | 使用 JSON Schema、结构化 tool error、自修正机会、失败阈值 |
| 删除旧 runtime 后 CI 不稳定 | 用 scripted / fake provider 替代 deterministic runtime |
| 写操作误执行 | gateway / guard / confirmation / idempotency / lock 全部由 code 强制执行 |
| token 成本上升 | state summary、history window、tool observation 摘要 |
| live eval 波动 | live eval 不进常规 CI，只做 manual / nightly / release smoke |
| prompt 与 tool schema 漂移 | schema 生成测试和 prompt tool name 校验 |
| state 迁移影响 trace | 明确 SessionState / TurnContext 分工，trace 同时记录 turn context |

## 后续扩展

- `TraceReplayHarness`
- LangGraph runtime experiment：把 `step_*` 注册为 StateGraph nodes
- 更细的 failure attribution dashboard
- prompt A/B benchmark
- provider 多模型切换策略
