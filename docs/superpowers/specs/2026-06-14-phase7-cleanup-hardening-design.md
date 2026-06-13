# Phase 7: Cleanup, Hardening & Live Eval Fix — 设计文档

日期：2026-06-14
状态：待评审
父 spec：`docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md`

## 目标

修复 Phase 1-6 积累的技术债：消除 10 个既存测试失败、退役 `ConversationState`、去重 AgentLoop 校验逻辑、提升 live eval 通过率（0/11 → 8+/11）、将 replay backend 接入 eval runner。

## 背景

Phase 6 完成后，架构迁移的主体工作已结束。但以下问题影响项目健康度：

- 10 个测试持续失败，CI signal 不可信
- `ConversationState` / `SessionState` 双类并存，workbench 仍用旧类
- `AgentLoop._validate_tool_call()` 与 `ToolGateway.execute()` 有重叠校验
- Live eval 0/11 通过 — prompt、tool schema、state summary 质量不足
- `TraceReplayHarness` 已构建但未接入 eval 流程

## 非目标

- 不新增 eval case
- 不修改 guard / gateway 安全逻辑
- 不引入新依赖
- 不修改 AgentLoop 核心循环结构

---

## 1. 测试环境修复

### 根因

`DisabledLLMProvider` → `AgentRuntime.__init__` 中 `provider=None` → `handle_user_message` 走 safe fallback 返回 "offline mode" → 所有 eval case 得 0 分。

### 方案

用 `DeterministicProvider`（Phase 1 已实现，`chat_with_tools()` 返回 `ToolCallResponse(assistant_content=messages[-1].content, finish_reason="stop")`）替代 `DisabledLLMProvider`。

但 `DeterministicProvider` 不会发起 tool calls，所以 eval case 仍然会失败（`wrong_tool`）。真正的修复是：**scripted eval 需要 ScriptedToolCallingProvider 而不是 DisabledLLMProvider**。

方案调整：在 `_run_case` 中为 scripted mode 构建最小可用的 `ScriptedToolCallingProvider`，pre-script 必要的 read tool calls（如 `find_user_id_by_email` → `get_order_details`），让 pre-flight identity shortcut 能正常工作。

更简单的方案：**恢复 pre-flight identity shortcut 后的 DeterministicProvider fallback**。当前 `handle_user_message` 在 `provider is None` 时直接返回 safe fallback。改为：如果 pre-flight 已完成 identity resolution，用 DeterministicProvider 跑 AgentLoop（至少 read 路径能跑）。

```python
# runtime.py handle_user_message
if self.provider is None:
    # Phase 7: use deterministic provider as fallback for scripted eval
    loop = AgentLoop(
        provider=DeterministicProvider(),
        gateway=self.gateway,
        registry=self.registry,
        context_builder=self._context_builder,
    )
    result = loop.run_turn(session, content)
```

`DeterministicProvider.chat_with_tools()` 返回 `ToolCallResponse(finish_reason="stop")`，AgentLoop 会立即 finalize，返回最后一条 user message 作为 assistant 回复。这对 read 路径（用户问了问题但不需要 tool call 就能回复）有帮助，但对 write 路径不够。

但这仍然不够 — eval case 期望特定的 tool calls。真正的解决是：**eval runner 为每个 case 生成 ScriptedToolCallingProvider 的 responses**。

最终方案（最小改动）：**将 `provider=None` 时的 safe fallback 改为抛异常而不是返回假消息**。让调用方（test/runner）显式处理。Eval runner 在 scripted mode 下提供 `DeterministicProvider`（其 `chat_with_tools` 至少能进入 AgentLoop），pre-flight identity 能正常完成 → read case 能过。

### 变更

- `app/agent/runtime.py` — `handle_user_message` 中 `provider is None` 时用 `DeterministicProvider` 代替 safe fallback
- `app/eval/runner.py` — 显式传 `DeterministicProvider`（不再用 `DisabledLLMProvider`）

### 预期效果

Eval 2 个集成测试从 0 passed → 11/30 passed（取决于 pre-flight + deterministic 路径能覆盖多少 case）。

---

## 2. ConversationState 退役

### 当前状态

两个几乎相同的类在 `app/agent/models.py` 中共存：

- `SessionState`（Phase 2 引入）— AgentRuntime 使用
- `ConversationState`（Phase 0 遗留）— workbench、tracing、cli chat 使用

### 方案

所有引用点迁移到 `SessionState`：

| 文件 | 改动 |
|------|------|
| `app/cli/chat.py` | `ConversationState` → `SessionState` |
| `app/workbench/session.py` | 构造、方法签名改用 `SessionState` |
| `app/workbench/snapshot.py` | 函数签名改用 `SessionState` |
| `app/ops/tracing.py` | `TraceWriter`、`build_trace_payload`、`final_state_summary` 改用 `SessionState` |

`ConversationState` 保留为 alias：`ConversationState = SessionState`，不删除（避免破坏外部引用和 test fixtures）。

### 注意事项

`ConversationState` 有但 `SessionState` 没有的字段：
- `run_metrics` — 无引用，可安全丢失
- `llm_call_durations` — workbench 未使用

workbench snapshot 引用 `state.slots`、`state.current_intent`、`state.policy_decision` → Phase 5 已从 SessionState 移除。snapshot 中这些字段改为返回空/None。

---

## 3. AgentLoop 去重

### 当前状态

`AgentLoop._validate_tool_call()` 做：
1. unknown tool 检查
2. missing required args 检查
3. malformed arguments 检查

`ToolGateway.execute()` 做：
1. unknown tool 检查（通过 registry 查找）
2. 通过 function signature 隐式校验参数

### 方案

AgentLoop 只保留 **第 1 项**（未知工具 — 这是最便宜的检查，避免浪费 LLM token 去重试），移除第 2、3 项（交给 gateway 返回结构化 error）。

```python
def _validate_tool_call(self, tool_call: ToolCallRequest) -> ToolExecutionError | None:
    if tool_call.tool_name not in self._registry.tools:
        return ToolExecutionError(
            error_type="unknown_tool",
            message_for_llm=f"Unknown tool: '{tool_call.tool_name}'.",
            retryable=True,
            allowed_tools=sorted(self._registry.tools),
        )
    return None
```

Gateway 已有的错误处理不变。

---

## 4. Live Eval 通过率提升

### 根因分析

| 失败类型 | 数量 | 根因 |
|----------|------|------|
| `tool_exception` | 6 | LLM 调用工具但参数错误 / guard block / 工具执行失败 |
| `wrong_tool` | 3 | LLM 选错工具 |
| `response_mismatch` | 1 | 输出缺少期望文本 |

### 改进措施

**A. Tool 描述强化（`app/tools/registry.py`）**

`_tool_description_for_llm()` 当前生成 "name. constraints" 格式。改为三段式：

```
<name>: <what it does>. <when to use>. <what it returns>.
```

示例：
```
get_order_details: Look up order status, items, shipping, and payment info by order ID. Use this before any order modification. Returns order dict with status/items/address/payment.
```

**B. 参数描述（`_property_schema()`）**

每个参数加 `"description"`：

```python
def _property_schema(self, tool_name: str, arg_name: str) -> dict:
    schema = {"type": "string"}
    desc = self._arg_description(tool_name, arg_name)
    if desc:
        schema["description"] = desc
    if arg_name in {"item_ids", "new_item_ids"}:
        return {"type": "array", "items": {"type": "string"}, "description": desc}
    if tool_name == "cancel_pending_order" and arg_name == "reason":
        return {"type": "string", "enum": [...], "description": desc}
    ...
    return schema

def _arg_description(self, tool_name: str, arg_name: str) -> str:
    return {
        "order_id": "The order ID starting with #W",
        "user_id": "The user's internal ID (from find_user_id_by_email/name_zip)",
        "email": "The user's email address",
        "item_ids": "List of item IDs to modify/return/exchange",
        "payment_method_id": "Payment method ID from user profile",
        "reason": "Cancellation reason",
        ...
    }.get(arg_name, "")
```

**C. Few-shot 示例（`prompts/llm_agent_system_v001.md`）**

在 Rules 段后新增 `## Examples`：

```markdown
## Examples

### Example 1: Look up an order
User: "My email is a@b.com. What's the status of order #W123?"
→ call find_user_id_by_email(email="a@b.com")
→ call get_order_details(order_id="#W123")
→ Reply: "Order #W123 is pending with 2 items..."

### Example 2: Cancel with confirmation
User: "Cancel #W123 because no longer needed"
→ call get_order_details(order_id="#W123")  [read before write]
→ call cancel_pending_order(order_id="#W123", reason="no longer needed")
→ Guard: explicit_confirmation_required
→ Reply: "I'll cancel #W123. Confirm?"
```

**D. State summary 增强（`app/agent/context_builder.py`）**

在 summary 中加入已认证用户的关键信息：

```
Authenticated: user_id=U1, email=a@b.com
Loaded orders: #W123=pending (2 items), #W456=delivered
```

---

## 5. Replay Backend 接入 Eval

### 方案

在 `CuratedEvalRunner` 新增 `eval_backend="replay"` 模式：

```bash
uv run phase2-eval --subset curated_mvp --replay <trace_dir>
```

指定已有的 trace artifact 目录，runner 加载每个 case 的 trace 并用 `TraceReplayHarness` 回放，验证回放结果与 trace 一致。

### 变更

- `app/eval/runner.py` — 新增 `replay_trace_dir` 参数，`_run_case` 在 replay 模式下用 `TraceReplayHarness` 替代 `AgentRuntime`

---

## 文件变更汇总

```
修改:
  app/agent/models.py           — ConversationState → alias
  app/agent/llm_agent.py        — 去重 _validate_tool_call
  app/agent/runtime.py          — DeterministicProvider fallback
  app/agent/context_builder.py  — state summary 增强
  app/tools/registry.py         — tool 描述 + 参数描述强化
  app/cli/chat.py               — SessionState
  app/workbench/session.py      — SessionState
  app/workbench/snapshot.py     — SessionState
  app/ops/tracing.py            — SessionState
  app/eval/runner.py            — DeterministicProvider + replay backend
  prompts/llm_agent_system_v001.md — few-shot examples
  tests/                        — 更新引用
```

## 验收标准

- [ ] 10 个既存测试失败全部修复（或明确标记 skip + 原因）
- [ ] `ConversationState` 已退役为 alias，无功能代码引用
- [ ] `_validate_tool_call` 只做 unknown tool 检查
- [ ] Live eval 通过率 ≥ 8/11
- [ ] Replay backend 可运行：`--replay <trace_dir>`
- [ ] `uv run python -m pytest tests/ -q` 0 失败（或全部 skip 有理由）
- [ ] `uv run ruff check .` 通过
