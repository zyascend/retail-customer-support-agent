# Phase 3: 独立 LLM Agent Loop — 设计 Spec

日期：2026-06-13
状态：设计阶段
依赖：Phase 1（tool-calling contract/schema/harness）✅、Phase 2（state 拆分/context builder）✅

## 目标

在 `app/agent/llm_agent.py` 中实现独立的 LLM tool-calling agent loop。loop 使用 `ScriptedToolCallingProvider` 和 `FakeFailingProvider` 做确定性测试，覆盖 read、write pending、guard block、unknown tool、malformed args、provider timeout 等全部路径。Phase 3 不切换主 runtime，loop 作为独立模块存在。

## 非目标

- 不修改 `AgentRuntime.handle_user_message()` 主路径（Phase 4 做）
- 不删除旧 pipeline/plan_handlers/graph（Phase 4 做）
- 不引入真实 LLM 调用到 CI（只通过 scripted/fake provider 测试）
- 不实现 pre-flight 确认短路和认证短路（Phase 4 在 runtime 层集成）
- 不修改 eval cases/runner（Phase 5 做）

---

## 架构设计

### AgentLoop 类

`AgentLoop` 是一个类，封装 tool-calling loop 的所有依赖和配置：

```python
class AgentLoop:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        gateway: ToolGateway,
        registry: ToolRegistry,
        context_builder: ContextBuilder,
        max_iterations: int = 5,
        max_consecutive_failures: int = 3,
    ) -> None:
        ...

    def run_turn(
        self,
        session: SessionState,
        user_content: str,
    ) -> AgentTurnResult:
        ...
```

选类而非纯函数的理由：
- 依赖（provider、gateway、registry、context_builder、阈值）跨轮稳定，一次注入，多轮复用
- Phase 4 中 `AgentRuntime` 可直接持有 `AgentLoop` 实例
- step_* 作为方法可独立测试，仍保留 LangGraph 迁移边界

### AgentTurnResult

```python
class AgentTurnResult(BaseModel):
    assistant_message: str
    turn: TurnContext
    pending_action_set: bool = False
```

三个字段的含义：
- `assistant_message`：最终返回给用户的文本
- `turn`：本轮完整的 TurnContext（steps、durations、token usage、loop iterations、termination）
- `pending_action_set`：是否因 guard 要求 confirmation 而设置了 pending_action（调用方用此判断下一轮是否需要走 pre-flight 确认短路）

### Step 函数

四个 step 方法，每个有明确的输入输出：

| 方法 | 职责 | 输入 | 输出 |
|------|------|------|------|
| `_step_llm_reason()` | 调用 provider.chat_with_tools()，构建 messages | session、user_content、tool_schemas | ToolCallResponse |
| `_step_tool_execute()` | 解析 tool calls，调用 gateway，构建 tool observations | tool_calls、session | list[ToolCallRecord]、tool 消息 |
| `_step_pending()` | 判断是否需要设置 pending action | guard result、tool_call | bool（是否设置 pending） |
| `_step_finalize()` | 判断是否结束 loop 并返回 final text | response、tool_results | str \| None（有值=结束） |

### Loop 流程

```
run_turn(session, user_content)
  │
  ├── 构建 messages（system prompt + history + state_summary）
  ├── 获取 tool_schemas
  │
  └── while loop:
        ├── iteration += 1
        ├── if iteration > max_iterations → 兜底文案，termination="max_iterations"
        │
        ├── _step_llm_reason(messages, tool_schemas) → response
        │   ├── provider timeout → 安全失败，termination="provider_timeout"
        │   └── 记录 token_usage
        │
        ├── if no tool_calls:
        │   └── _step_finalize(response) → assistant_message, termination="final_response"
        │
        ├── for each tool_call in response.tool_calls:
        │   └── _step_tool_execute(tool_call, session) → record
        │       ├── unknown tool → ToolExecutionError 消息 feed 回 messages
        │       ├── malformed arguments → ToolExecutionError 消息
        │       ├── missing required args → ToolExecutionError 消息
        │       ├── tool execution error → ToolExecutionError 消息
        │       ├── guard blocked (非 confirmation) → ToolExecutionError 消息
        │       └── guard requires confirmation → _step_pending() → 设置 pending_action
        │
        ├── if pending_action set → break loop
        │
        ├── update consecutive_failures:
        │   ├── 本轮所有 tool call 都失败 → failures += 1
        │   └── 至少一个成功 → failures = 0
        │
        ├── if consecutive_failures > max_consecutive_failures → 转人工文案
        │
        └── append tool result messages → 继续 loop
```

### 终止条件（优先级从高到低）

1. **provider_timeout** — `_step_llm_reason` 中 provider 抛异常，安全失败文案
2. **pending_action_set** — guard 要求 explicit confirmation，设置 pending 并退出
3. **final_response** — LLM 返回 assistant_content 且无 tool_calls
4. **max_iterations** — 超过 5 次迭代，兜底文案
5. **consecutive_failures** — 连续 3 次 tool call 失败，转人工文案

---

## 需要修改的现有文件

### 1. `app/agent/models.py` — SessionState 补字段 + 新增 AgentTurnResult

**SessionState 永久补全**：`SessionState` 是未来的主 state 对象，补上 `steps` 和 `add_step()`（ConversationState 已有这些，SessionState 补全后两者在 gateway/guard 视角下 duck-type 兼容）：

```python
class SessionState(BaseModel):
    # ... existing fields ...
    steps: List[AgentStep] = Field(default_factory=list)
    # ... rest unchanged ...

    def add_step(self, node: str, **detail: Any) -> None:
        self.steps.append(AgentStep(node=node, detail=detail))
```

`steps` 是永久字段（跨轮可审计），不是临时补丁。Phase 4 ConversationState 删除后 SessionState 自然承担所有职责。

**AgentTurnResult 新增**：在 `TurnContext` 定义后新增：

```python
class AgentTurnResult(BaseModel):
    assistant_message: str
    turn: TurnContext
    pending_action_set: bool = False
```

### 2. `app/tools/gateway.py` — 适配 SessionState

**变更**：`execute()` 参数类型从 `ConversationState` → `SessionState`。逻辑和返回值不变。

`ConversationState` 是 `SessionState` 的超集（多了 `current_intent`、`slots`、`policy_decision`、`confirmation_status`、`risk_level`、`run_metrics`），gateway 和 guard 不使用这些多余字段。`SessionState` 补上 `steps`/`add_step()` 后，gateway 内部的 `state.add_step()`、`state.tool_results.append()`、`state.write_locks.append()`、`state.audit_logs.append()` 全部正常工作。runtime.py 传 `ConversationState` 实例给 gateway 也不受影响（ConversationState 有全部这些属性）。

**返回类型不变**：`execute()` 继续返回 `ToolCallRecord`。`ToolCallRecord` 已有的字段足以让 AgentLoop 判断所有情况：

| 场景 | record.status | record.error | AgentLoop 行为 |
|------|--------------|-------------|----------------|
| 成功 | "success" | None | append tool result message |
| Guard requires confirmation | "blocked" | "explicit_confirmation_required" | step_pending |
| Guard blocked (其他) | "blocked" | 其他 block_reason | ToolExecutionError feed 回 LLM |
| Tool execution error | "error" | Exception name | ToolExecutionError feed 回 LLM |

不需要新增 `ToolExecutionResult` wrapper 类。

### 3. `app/agent/guard.py` — 适配 SessionState

**变更**：`check()` 参数类型从 `ConversationState` → `SessionState`。

Guard 实际使用的字段（`authenticated_user_id`、`loaded_context`、`write_locks`、`session_id`）SessionState 都有，改类型注解即可，逻辑零改动。

### 4. `app/agent/runtime.py` — 无需改动

Gateway 和 guard 的签名从 `ConversationState` 改为 `SessionState`，但 runtime.py 传递的 `ConversationState` 实例拥有 `SessionState` 的全部字段和方法（包括新增的 `steps`/`add_step()`），Python duck typing 下无需任何适配。runtime.py 在 Phase 3 零改动。

---

## 消息构建

### System Prompt

使用 `prompts/llm_agent_system_v001.md`（Phase 3 创建），模板变量由 AgentLoop 替换：

```markdown
# Role
You are a retail customer support agent...

# Available Tools
{tool_catalog}

# Retail Policy
{policy}

# Current Session State
{state_summary}
```

### Messages 结构

每轮 LLM 调用发送的消息序列：

```
[system]     ← system prompt（role: "system"）
[user]       ← user_content（当前用户消息）
[assistant]  ← 上一轮 LLM 回复（如有 tool_calls，包含 tool_calls 数组）
[tool]       ← 上一轮 tool 执行结果（role: "tool"，tool_call_id 对应）
[assistant]  ← 上一轮 LLM 再次回复（如有）
...          ← 历史往复
```

### Tool Observation 消息格式

```python
# 成功
{"role": "tool", "tool_call_id": "call_1", "content": "<json summary>"}

# 失败（结构化 ToolExecutionError）
{"role": "tool", "tool_call_id": "call_2", "content": "<ToolExecutionError JSON>"}
```

成功时 `content` 使用 `observation_reducer`（或简要摘要）压缩后的 JSON。失败时 content 是 `ToolExecutionError.model_dump_json()`。

---

## 错误处理路径

### Path 1: Unknown Tool

```
LLM 返回 tool_name="hallucinated_tool"
→ gateway 查找失败 → ToolExecutionError(error_type="unknown_tool")
→ feed 回 messages 作为 tool observation
→ LLM 自修正（选择正确的 tool）或最终返回无法处理
→ 如果连续 3 次失败 → 转人工
```

### Path 2: Malformed Arguments

```
LLM 返回 tool_name="get_order_details", raw_arguments="{not-json"
→ normalize_tool_calling_message 将 arguments 设为 {}
→ 缺少 required args → ToolExecutionError(error_type="missing_required_args")
→ feed 回 messages
→ LLM 自修正
```

### Path 3: Missing Required Args

```
LLM 返回 tool_name="cancel_pending_order", arguments={"order_id": "O1"}  # 缺 reason
→ 或 arguments={} (malformed)
→ _step_tool_execute 校验 required args
→ ToolExecutionError(error_type="missing_required_args", missing_args=["reason"])
→ feed 回 messages
```

### Path 4: Guard Blocked (非 confirmation)

```
LLM 调用 cancel_pending_order(order_id="O2")，但 O2 是 delivered
→ gateway.execute() → guard.check() → block_reason="non_pending_order_cannot_be_cancelled"
→ ToolExecutionRecord(status="blocked", error="non_pending_order_cannot_be_cancelled")
→ ToolExecutionError(error_type="guard_blocked", message_for_llm="...")
→ feed 回 messages，让 LLM 向用户解释
```

### Path 5: Guard Requires Confirmation

```
LLM 调用 cancel_pending_order(order_id="O1", reason="no longer needed")，O1 是 pending
→ gateway.execute(confirmed=False) → guard.check() → block_reason="explicit_confirmation_required"
→ _step_pending 设置 session.pending_action
→ 构建确认提示文案 → assistant_message，pending_action_set=True
→ loop 终止
```

### Path 6: Provider Timeout

```
_step_llm_reason 调用 provider.chat_with_tools()
→ TimeoutError
→ assistant_message = "I'm having trouble processing your request right now. Please try again."
→ termination = "provider_timeout"
```

### Path 7: Consecutive Failures

```
连续 3 次 loop 迭代中，所有本轮 tool call 都失败（status != "success"）
→ assistant_message = "I'm unable to complete this request. Let me transfer you to a human agent."
→ termination = "consecutive_failures"
→ 可选：调用 transfer_to_human_agents
```

---

## Loop 内 tool call 参数校验

AgentLoop 在调用 gateway 之前做轻量级参数校验。这要求在 `ToolRegistry` 上暴露一个公开方法 `required_args_for_tool()`（当前是 `_required_args_for_tool` 私有方法，改为公开）：

```python
# ToolRegistry 新增公开方法（重命名 _required_args_for_tool）
def required_args_for_tool(self, name: str) -> list[str]:
    ...
```

AgentLoop 的校验逻辑：

```python
def _validate_tool_call(self, tool_call: ToolCallRequest) -> ToolExecutionError | None:
    # 1. 检查 tool 是否存在
    if tool_call.tool_name not in self._registry.tools:
        return ToolExecutionError(
            error_type="unknown_tool",
            message_for_llm=f"Unknown tool: {tool_call.tool_name}. Available: {sorted(self._registry.tools)}",
            retryable=True,
            allowed_tools=sorted(self._registry.tools),
        )
    # 2. 检查 required args
    required = self._registry.required_args_for_tool(tool_call.tool_name)
    missing = [a for a in required if not tool_call.arguments.get(a)]
    if missing:
        return ToolExecutionError(
            error_type="missing_required_args",
            message_for_llm=f"Missing required arguments for {tool_call.tool_name}: {missing}",
            retryable=True,
            missing_args=missing,
        )
    # 3. 检查 raw_arguments 是否 malformed
    if tool_call.raw_arguments and not tool_call.arguments:
        return ToolExecutionError(
            error_type="malformed_arguments",
            message_for_llm=f"Could not parse arguments for {tool_call.tool_name}",
            retryable=True,
        )
    return None
```

---

## 测试计划

测试文件：`tests/test_llm_agent.py`

### 测试用例（15 个）

#### 基础路径（4 个）

| # | 测试名 | Provider | Scenario | 断言 |
|---|--------|----------|----------|------|
| 1 | `test_agent_read_tool_then_respond` | Scripted | LLM 先调 get_order_details，再返回最终文本 | `assistant_message` 非空，`turn.loop_iterations == 2`，`turn.termination == "final_response"` |
| 2 | `test_agent_final_response_no_tool_calls` | Scripted | LLM 直接返回文本，不调工具 | `assistant_message` 匹配脚本，`turn.loop_iterations == 1` |
| 3 | `test_agent_multiple_read_tools` | Scripted | LLM 依次调两个 read 工具 | 两次 tool call 都成功，最终有 assistant_message |
| 4 | `test_agent_max_iterations_exceeded` | Scripted (无限 tool_calls) | LLM 一直返回 tool_calls，超过 5 次 | `assistant_message` 含兜底文本，`turn.termination == "max_iterations"` |

#### 写操作与确认路径（3 个）

| # | 测试名 | Provider | Scenario | 断言 |
|---|--------|----------|----------|------|
| 5 | `test_write_requires_confirmation` | Scripted | LLM 调 cancel_pending_order，guard 要求确认 | `pending_action_set == True`，`session.pending_action is not None`，`turn.termination == "pending_confirmation"` |
| 6 | `test_write_read_before_write_blocks` | Scripted | LLM 调 cancel_pending_order 但未先读 order | guard block → ToolExecutionError → LLM 回复解释 |
| 7 | `test_write_guard_block_no_confirmation` | Scripted | LLM 调 cancel 但 order 是 delivered | guard block → ToolExecutionError feed 回 LLM → LLM 回复解释 |

#### 错误与故障路径（5 个）

| # | 测试名 | Provider | Scenario | 断言 |
|---|--------|----------|----------|------|
| 8 | `test_unknown_tool_self_correction` | FakeFailing(unknown_tool) + Scripted | LLM 第一次调 hallucinated tool → error → 第二次调正确 tool | 最终成功 |
| 9 | `test_malformed_arguments_self_correction` | FakeFailing(malformed) + Scripted | LLM 第一次参数 malformed → error → 第二次正确 | 最终成功 |
| 10 | `test_missing_args_self_correction` | FakeFailing(missing_args) + Scripted | LLM 第一次缺参数 → error → 第二次补全 | 最终成功 |
| 11 | `test_provider_timeout` | FakeFailing(timeout) | Provider 超时 | `assistant_message` 含安全失败文案，`turn.termination == "provider_timeout"` |
| 12 | `test_consecutive_failures_transfer` | Scripted (3 次失败) | 连续 3 次 tool call 全部失败 | `turn.termination == "consecutive_failures"`，`assistant_message` 含转人工提示，`turn.consecutive_tool_failures >= 3` |

#### 集成级路径（3 个）

| # | 测试名 | Provider | Scenario | 断言 |
|---|--------|----------|----------|------|
| 13 | `test_full_read_flow_with_context` | Scripted | 已认证用户查订单 → LLM 读 order → 回复含订单信息 | context_builder 的 summary 进入 prompt、order 信息在回复中 |
| 14 | `test_pending_action_preserved_in_session` | Scripted | LLM 发起 cancel → pending 设置 → session 保留 pending_action | `session.pending_action` 持久化，`pending_action_set == True` |
| 15 | `test_turn_context_populated_after_loop` | Scripted | 正常读流程 | `turn.steps` 非空、`turn.loop_iterations > 0`、`turn.termination` 非 None、`turn.step_durations` 非空 |

---

## 文件变更总览

### 新增

| 文件 | 职责 |
|------|------|
| `app/agent/llm_agent.py` | AgentLoop 类 + 4 个 step 方法 + while loop + 参数校验 |
| `prompts/llm_agent_system_v001.md` | 单文件 system prompt，含 `{tool_catalog}`、`{policy}`、`{state_summary}` 模板变量 |
| `tests/test_llm_agent.py` | 15 个测试用例，覆盖所有 loop 路径 |

### 修改

| 文件 | 变更 |
|------|------|
| `app/agent/models.py` | `SessionState` 永久补 `steps` + `add_step()`；新增 `AgentTurnResult` |
| `app/tools/gateway.py` | `execute()` 参数类型 `ConversationState` → `SessionState`；返回类型不变 |
| `app/agent/guard.py` | `check()` 参数类型 `ConversationState` → `SessionState`；逻辑不变 |
| `app/tools/registry.py` | `_required_args_for_tool` → `required_args_for_tool`（私有变公开） |
| `app/agent/runtime.py` | **零改动**（ConversationState 实例满足 SessionState duck typing） |

---

## 验收标准

- [ ] `uv run python -m pytest tests/test_llm_agent.py -q` — 15 个测试通过
- [ ] `uv run python -m pytest tests/ -q` — 全部现有测试通过（无回归）
- [ ] `uv run ruff check .` — lint 通过
- [ ] Phase 3 exit criteria from plan: "scripted loop 测试覆盖 read、write pending、guard block、失败路径"
- [ ] AgentLoop 可作为独立模块被 import 和实例化，不依赖 ConversationState
