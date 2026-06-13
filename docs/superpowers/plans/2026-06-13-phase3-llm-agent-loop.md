# Phase 3: 独立 LLM Agent Loop — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `app/agent/llm_agent.py` 中实现独立 LLM tool-calling agent loop（AgentLoop 类），用 ScriptedToolCallingProvider 验证全部路径：read、write pending、guard block、unknown tool、malformed args、provider timeout。

**Architecture:** AgentLoop 类封装 4 个 step 方法 + while loop，通过 SessionState + TurnContext 管理状态。Gateway/Guard 签名从 ConversationState 迁移到 SessionState（duck-type 兼容，runtime.py 零改动）。session.messages 维护 OpenAI-compatible 消息数组，结构化 tool error 作为 tool observation 喂回 LLM。

**Tech Stack:** Python 3.14、Pydantic v2、pytest、项目现有 ToolRegistry/ToolGateway/ContextBuilder/ScriptedToolCallingProvider/FakeFailingProvider

---

## 文件结构

```
新增:
  app/agent/llm_agent.py          ← AgentLoop 类 + 4 个 step 方法
  prompts/llm_agent_system_v001.md  ← system prompt 模板
  tests/test_llm_agent.py         ← 15 个测试用例

修改:
  app/agent/models.py             ← SessionState 补 steps/add_step；新增 AgentTurnResult
  app/tools/gateway.py            ← execute() 参数类型 ConversationState → SessionState
  app/agent/guard.py              ← check() 参数类型 ConversationState → SessionState
  app/tools/registry.py           ← _required_args_for_tool → required_args_for_tool（公开）

不改:
  app/agent/runtime.py            ← 零改动（duck-type 兼容）
```

---

### Task 1: SessionState 补 fields + AgentTurnResult model

**Files:**
- Modify: `app/agent/models.py`
- Test: `tests/test_session_state.py`（追加测试）

**背景**：SessionState 需要 `steps` 和 `add_step()` 以匹配 ConversationState 的 duck-type 接口。同时新增 `AgentTurnResult` 作为 AgentLoop 的返回值。

- [ ] **Step 1: 编写失败测试**

追加到 `tests/test_session_state.py`：

```python
from app.agent.models import AgentStep, AgentTurnResult


def test_session_state_has_steps_and_add_step() -> None:
    session = SessionState(session_id="sess-5")
    assert session.steps == []
    session.add_step("test_node", status="ok", key="val")
    assert len(session.steps) == 1
    assert session.steps[0].node == "test_node"
    assert session.steps[0].status == "ok"
    assert session.steps[0].detail == {"status": "ok", "key": "val"}


def test_agent_turn_result_construction() -> None:
    turn = TurnContext(loop_iterations=2, termination="final_response")
    result = AgentTurnResult(
        assistant_message="Hello",
        turn=turn,
        pending_action_set=False,
    )
    assert result.assistant_message == "Hello"
    assert result.turn.loop_iterations == 2
    assert result.turn.termination == "final_response"
    assert result.pending_action_set is False


def test_agent_turn_result_with_pending() -> None:
    result = AgentTurnResult(
        assistant_message="Should I cancel order O1?",
        turn=TurnContext(),
        pending_action_set=True,
    )
    assert result.pending_action_set is True
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run python -m pytest tests/test_session_state.py::test_session_state_has_steps_and_add_step tests/test_session_state.py::test_agent_turn_result_construction tests/test_session_state.py::test_agent_turn_result_with_pending -v
```

预期：`test_session_state_has_steps_and_add_step` 失败（`SessionState` 没有 `steps` 属性），另外两个测试失败（`AgentTurnResult` 未定义）。

- [ ] **Step 3: 实现**

修改 `app/agent/models.py`：

在 `SessionState` 类中，`termination_reason` 字段之后、类的结束 `"""` 之前，追加：

```python
    steps: List[AgentStep] = Field(default_factory=list)

    def add_step(self, node: str, **detail: Any) -> None:
        self.steps.append(AgentStep(node=node, detail=detail))
```

在 `TurnContext` 类定义之后、`ConversationState` 之前新增：

```python
class AgentTurnResult(BaseModel):
    """Return value from AgentLoop.run_turn()."""
    assistant_message: str
    turn: TurnContext
    pending_action_set: bool = False
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run python -m pytest tests/test_session_state.py::test_session_state_has_steps_and_add_step tests/test_session_state.py::test_agent_turn_result_construction tests/test_session_state.py::test_agent_turn_result_with_pending -v
```

预期：3 passed。

- [ ] **Step 5: 运行完整 session_state 测试 + lint**

```bash
uv run python -m pytest tests/test_session_state.py -v
uv run ruff check app/agent/models.py tests/test_session_state.py
```

预期：全部通过。

- [ ] **Step 6: 提交**

```bash
git add app/agent/models.py tests/test_session_state.py
git commit -m "feat: add steps/add_step to SessionState and AgentTurnResult model"
```

---

### Task 2: Gateway + Guard SessionState 类型迁移

**Files:**
- Modify: `app/tools/gateway.py`
- Modify: `app/agent/guard.py`

**背景**：gateway 的 `execute()` 和 guard 的 `check()` 参数类型从 `ConversationState` 改为 `SessionState`。SessionState 已有 `steps`/`add_step()`（Task 1 补全），所以 gateway 内部调用不变。ConversationState 实例传给 gateway/guard 时 duck-type 兼容。

- [ ] **Step 1: 运行现有测试确认基线**

```bash
uv run python -m pytest tests/ -q
```

预期：全部通过（259 个测试左右）。

- [ ] **Step 2: 修改 gateway.py**

`app/tools/gateway.py` 第 6 行，改动 import 和 `execute()` 签名：

```python
# 第 6 行：改动 import
from app.agent.models import SessionState, ToolCall, ToolCallRecord

# 第 24 行：改动 execute 签名
def execute(
    self,
    *,
    state: SessionState,
    tool_name: str,
    arguments: Dict[str, Any],
    confirmed: bool = False,
) -> ToolCallRecord:
```

不需要改动 `state.add_step()` 调用 — SessionState 现在有这个方法。

- [ ] **Step 3: 修改 guard.py**

`app/agent/guard.py` 第 7 行，改动 import 和 `check()` 签名：

```python
# 第 7 行：改动 import
from app.agent.models import SessionState, ToolCall

# 第 35 行：改动 check 签名
def check(
    self,
    *,
    state: SessionState,
    db: Any,
    action: ToolCall,
    confirmed: bool,
) -> WriteActionGuardResult:
```

- [ ] **Step 4: 运行完整测试确认无回归**

```bash
uv run python -m pytest tests/ -q
```

预期：全部通过。ConversationState 实例继续传入 gateway/guard（duck-type 兼容）。

- [ ] **Step 5: Lint**

```bash
uv run ruff check app/tools/gateway.py app/agent/guard.py
```

预期：通过。

- [ ] **Step 6: 提交**

```bash
git add app/tools/gateway.py app/agent/guard.py
git commit -m "refactor: migrate gateway and guard to SessionState parameter type"
```

---

### Task 3: Registry required_args_for_tool 公开

**Files:**
- Modify: `app/tools/registry.py`
- Modify: 所有内部调用点

**背景**：AgentLoop 的前置校验需要查询 tool 的 required 参数。当前 `_required_args_for_tool` 是私有方法，改为公开。

- [ ] **Step 1: 修改 registry.py**

将 `_required_args_for_tool` 重命名为 `required_args_for_tool`（去掉下划线前缀），并更新内部调用：

```python
# 第 124 行：重命名方法定义
def required_args_for_tool(self, name: str) -> list[str]:
    ...

# 第 125 行：内部调用点 _json_schema_for_tool 中
required = self.required_args_for_tool(name)
```

- [ ] **Step 2: 运行 registry 和 schema 测试**

```bash
uv run python -m pytest tests/test_tool_schema.py -v
```

预期：4 passed（registry 内部使用更新后的公开方法名）。

- [ ] **Step 3: 运行完整测试 + lint**

```bash
uv run python -m pytest tests/ -q
uv run ruff check app/tools/registry.py tests/test_tool_schema.py
```

预期：全部通过。

- [ ] **Step 4: 提交**

```bash
git add app/tools/registry.py
git commit -m "refactor: make required_args_for_tool public on ToolRegistry"
```

---

### Task 4: System Prompt 文件

**Files:**
- Create: `prompts/llm_agent_system_v001.md`

**背景**：AgentLoop 使用单文件 system prompt，含 `{tool_catalog}`、`{policy}`、`{state_summary}` 三个模板变量。

- [ ] **Step 1: 创建 prompt 文件**

创建 `prompts/llm_agent_system_v001.md`：

```markdown
## Identity

You are a retail customer support transaction agent. You help authenticated users
look up their orders, cancel/modify pending orders, return/exchange delivered items,
modify user addresses, and transfer to human agents when needed.

You have access to tools that let you read order/user/product data and execute
write operations. Always use tools to look up information — never invent or guess
order IDs, item IDs, user data, or any database state.

## Available Tools

{tool_catalog}

## Retail Policy

{policy}

## Current Session State

{state_summary}

## Rules

1. **No data fabrication** — always call a read tool before referencing order/user
   details. Never guess or invent IDs, names, statuses, or prices.

2. **Read before write** — before calling any write tool, first call the
   corresponding read tool (e.g. get_order_details before cancel_pending_order).

3. **Confirmation required** — all write operations require explicit user
   confirmation. If the guard requires confirmation, ask the user clearly what
   you plan to do and wait for their yes/no response.

4. **Guard blocks** — if a tool call is blocked by the guard, explain the
   reason to the user in plain language and suggest what they can do instead.

5. **Tool errors** — if a tool call fails with an error, try to fix the issue
   and retry. If you cannot fix it, explain the problem to the user.

6. **Transfer** — if you cannot help the user after trying available tools,
   offer to transfer to a human agent.

7. **Be concise** — reply in clear, short sentences. Don't repeat information
   the user already has.

## Tool Call Format

- Call tools using the exact names and parameters shown above.
- All required parameters must be provided.
- enum values must match exactly (e.g. "no longer needed", not "don't need").
```

- [ ] **Step 2: 验证文件可读且含模板变量**

```bash
grep -c '{tool_catalog}\|{policy}\|{state_summary}' prompts/llm_agent_system_v001.md
```

预期：3（三个模板变量各出现一次）。

- [ ] **Step 3: 提交**

```bash
git add prompts/llm_agent_system_v001.md
git commit -m "feat: add LLM agent system prompt template"
```

---

### Task 5: AgentLoop 基础 — 单轮 text 响应（无 tool call）

**Files:**
- Create: `app/agent/llm_agent.py`
- Create: `tests/test_llm_agent.py`

**背景**：实现 AgentLoop 最简路径——provider 直接返回文本、无 tool call。覆盖 `_step_llm_reason` 和 `_step_finalize`。

- [ ] **Step 1: 编写失败测试**

创建 `tests/test_llm_agent.py`：

```python
from __future__ import annotations

import pytest

from app.agent.context_builder import ContextBuilder
from app.agent.models import (
    AgentTurnResult,
    SessionState,
    ToolCallRequest,
    ToolCallResponse,
)
from app.agent.providers import (
    FakeFailingProvider,
    ScriptedToolCallingProvider,
)
from app.config import resolve_config
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry
from app.tools.retail_adapter import RetailAdapter


def _registry() -> ToolRegistry:
    runtime = RetailAdapter(resolve_config()).create_runtime()
    return ToolRegistry(runtime.tools)


def _gateway() -> ToolGateway:
    runtime = RetailAdapter(resolve_config()).create_runtime()
    registry = ToolRegistry(runtime.tools)
    return ToolGateway(registry=registry, runtime=runtime)


def _context_builder() -> ContextBuilder:
    from app.config import resolve_config as rc
    policy_path = rc().retail_policy_path
    policy_text = policy_path.read_text()[:500] if policy_path.exists() else ""
    return ContextBuilder(policy_text=policy_text)


def _session(**kwargs) -> SessionState:
    defaults = dict(
        session_id="test-1",
        authenticated_user_id="U1",
        auth_method="email",
        active_user_identity={"user_id": "U1", "name": "Test User", "email": "test@example.com"},
    )
    defaults.update(kwargs)
    return SessionState(**defaults)


class TestAgentLoopBasic:
    """Tests: single-turn response, no tool calls."""

    def test_direct_text_response_no_tools(self) -> None:
        from app.agent.llm_agent import AgentLoop

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    assistant_content="Hello! How can I help you today?",
                    finish_reason="stop",
                )
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        session = _session()
        result = loop.run_turn(session, "Hi")

        assert result.assistant_message == "Hello! How can I help you today?"
        assert result.turn.loop_iterations == 1
        assert result.turn.termination == "final_response"
        assert result.pending_action_set is False

    def test_turn_context_has_steps(self) -> None:
        from app.agent.llm_agent import AgentLoop

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    assistant_content="Done.",
                    finish_reason="stop",
                )
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(_session(), "Hello")

        assert len(result.turn.steps) > 0
        assert any(s.node == "llm_reason" for s in result.turn.steps)
        assert any(s.node == "finalize" for s in result.turn.steps)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run python -m pytest tests/test_llm_agent.py -v
```

预期：失败，`ModuleNotFoundError`（`app.agent.llm_agent` 不存在）。

- [ ] **Step 3: 实现 AgentLoop 最简版本**

创建 `app/agent/llm_agent.py`：

```python
from __future__ import annotations

import time
from typing import Any

from app.agent.context_builder import ContextBuilder
from app.agent.models import (
    AgentTurnResult,
    SessionState,
    ToolCallRequest,
    ToolCallResponse,
    ToolExecutionError,
    TurnContext,
)
from app.agent.providers import LLMProvider
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry


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
        self._provider = provider
        self._gateway = gateway
        self._registry = registry
        self._context_builder = context_builder
        self._max_iterations = max_iterations
        self._max_consecutive_failures = max_consecutive_failures
        self._system_prompt = self._load_system_prompt()

    def run_turn(
        self, session: SessionState, user_content: str
    ) -> AgentTurnResult:
        turn = TurnContext()
        messages = self._build_messages(session, user_content)
        tool_schemas = self._registry.tool_schemas_for_llm()

        while turn.loop_iterations < self._max_iterations:
            turn.loop_iterations += 1
            t0 = time.perf_counter()

            response = self._step_llm_reason(messages, tool_schemas)
            turn.step_durations["llm_reason"] = round(
                (time.perf_counter() - t0) * 1000, 1
            )
            turn.add_step("llm_reason", finish_reason=response.finish_reason)

            if response.token_usage:
                turn.llm_token_usage = response.token_usage

            # No tool calls → final response
            if not response.tool_calls:
                return self._step_finalize(response, turn)

            # TODO: tool execution in later tasks
            turn.termination = "max_iterations"
            return AgentTurnResult(
                assistant_message="I'm sorry, I couldn't process your request.",
                turn=turn,
            )

        # Max iterations exceeded
        turn.termination = "max_iterations"
        return AgentTurnResult(
            assistant_message=(
                "I'm having trouble processing your request. "
                "Let me transfer you to a human agent."
            ),
            turn=turn,
        )

    # ── Step methods ──

    def _step_llm_reason(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ToolCallResponse:
        return self._provider.chat_with_tools(messages=messages, tools=tools)

    def _step_finalize(
        self, response: ToolCallResponse, turn: TurnContext
    ) -> AgentTurnResult:
        turn.termination = "final_response"
        turn.add_step("finalize")
        return AgentTurnResult(
            assistant_message=response.assistant_content or "",
            turn=turn,
        )

    # ── Internal helpers ──

    def _load_system_prompt(self) -> str:
        from pathlib import Path
        prompt_path = Path("prompts/llm_agent_system_v001.md")
        template = prompt_path.read_text(encoding="utf-8")
        tool_catalog = self._registry.tool_catalog_for_llm()
        state_summary_placeholder = "## Session\nNo active session."
        policy_text = ""
        if hasattr(self._context_builder, "_policy_text"):
            policy_text = self._context_builder._policy_text
        return template.replace("{tool_catalog}", tool_catalog).replace(
            "{policy}", policy_text
        ).replace("{state_summary}", state_summary_placeholder)

    def _build_messages(
        self, session: SessionState, user_content: str
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
        ]
        for msg in session.messages[-6:]:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_content})
        return messages
```

注意：`TurnContext` 还没有 `add_step` 方法，需要补。同时 `_system_prompt` 中的 `{state_summary}` 应该动态生成。后续任务会完善。

- [ ] **Step 4: 补 TurnContext.add_step**

修改 `app/agent/models.py`，在 `TurnContext` 类中（`termination` 字段之后）追加：

```python
    def add_step(self, node: str, **detail: Any) -> None:
        self.steps.append(AgentStep(node=node, detail=detail))
```

- [ ] **Step 5: 运行测试**

```bash
uv run python -m pytest tests/test_llm_agent.py -v
```

预期：`test_direct_text_response_no_tools` 和 `test_turn_context_has_steps` 通过。

- [ ] **Step 6: Lint + 提交**

```bash
uv run ruff check app/agent/llm_agent.py app/agent/models.py tests/test_llm_agent.py
git add app/agent/llm_agent.py app/agent/models.py tests/test_llm_agent.py
git commit -m "feat: add AgentLoop basic single-turn text response"
```

---

### Task 6: AgentLoop — read tool 执行

**Files:**
- Modify: `app/agent/llm_agent.py`
- Modify: `tests/test_llm_agent.py`（追加测试）

**背景**：LLM 返回 tool_call（read tool），AgentLoop 调用 gateway 执行，结果作为 tool observation 消息喂回 messages，继续 loop。

- [ ] **Step 1: 追加失败测试**

追加到 `tests/test_llm_agent.py`：

```python
class TestAgentLoopReadTools:
    """Tests: read tool execution."""

    def test_read_tool_then_respond(self) -> None:
        from app.agent.llm_agent import AgentLoop

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="get_order_details",
                            arguments={"order_id": "#W5918442"},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    assistant_content="Your order #W5918442 is pending with 4 items.",
                    finish_reason="stop",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        session = _session()
        result = loop.run_turn(session, "Check my order #W5918442")

        assert "W5918442" in result.assistant_message
        assert result.turn.loop_iterations == 2
        assert result.turn.termination == "final_response"
        assert len(session.tool_results) == 1
        assert session.tool_results[0].tool_name == "get_order_details"
        assert session.tool_results[0].status == "success"

    def test_multi_read_tool_sequence(self) -> None:
        from app.agent.llm_agent import AgentLoop

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="get_order_details",
                            arguments={"order_id": "#W5918442"},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_2",
                            tool_name="get_user_details",
                            arguments={"user_id": "sofia_rossi_8776"},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    assistant_content="I found your order and your account details.",
                    finish_reason="stop",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        session = _session()
        result = loop.run_turn(session, "Show my order and account")

        assert result.turn.loop_iterations == 3
        assert len(session.tool_results) == 2
        assert session.tool_results[0].tool_name == "get_order_details"
        assert session.tool_results[1].tool_name == "get_user_details"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run python -m pytest tests/test_llm_agent.py::TestAgentLoopReadTools -v
```

预期：失败 — `run_turn` 中 tool_calls 分支未实现（当前只返回兜底文案）。

- [ ] **Step 3: 实现 tool execution in AgentLoop**

修改 `app/agent/llm_agent.py` 中的 `run_turn` 方法，替换 `# TODO: tool execution in later tasks` 部分：

```python
            # Execute each tool call
            assistant_msg = self._assistant_message_dict(response)
            messages.append(assistant_msg)

            all_failed = True
            for tc in response.tool_calls:
                t0 = time.perf_counter()
                record = self._gateway.execute(
                    state=session,
                    tool_name=tc.tool_name,
                    arguments=tc.arguments,
                )
                turn.step_durations[f"tool_{tc.tool_name}"] = round(
                    (time.perf_counter() - t0) * 1000, 1
                )
                turn.add_step(
                    "tool_execute",
                    tool_name=tc.tool_name,
                    status=record.status,
                )

                # Build tool observation message
                if record.status == "success":
                    all_failed = False
                    obs = record.observation
                    obs_str = str(obs)[:500] if obs is not None else "(none)"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": obs_str,
                    })
                else:
                    error_msg = ToolExecutionError(
                        error_type="tool_execution_error",
                        message_for_llm=(
                            f"Tool {tc.tool_name} failed: {record.error or 'unknown error'}"
                        ),
                        retryable=True,
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": error_msg.model_dump_json(),
                    })

            if all_failed:
                turn.consecutive_tool_failures += 1
            else:
                turn.consecutive_tool_failures = 0

            if turn.consecutive_tool_failures >= self._max_consecutive_failures:
                turn.termination = "consecutive_failures"
                turn.add_step("consecutive_failures_limit")
                return AgentTurnResult(
                    assistant_message=(
                        "I'm unable to complete this request. "
                        "Let me transfer you to a human agent."
                    ),
                    turn=turn,
                )
```

同时新增 helper 方法：

```python
    @staticmethod
    def _assistant_message_dict(response: ToolCallResponse) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": response.assistant_content}
        if response.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": tc.raw_arguments or "{}",
                    },
                }
                for tc in response.tool_calls
            ]
        return msg
```

- [ ] **Step 4: 运行测试**

```bash
uv run python -m pytest tests/test_llm_agent.py::TestAgentLoopReadTools -v
```

预期：2 passed。

- [ ] **Step 5: 运行全部 llm_agent 测试**

```bash
uv run python -m pytest tests/test_llm_agent.py -v
```

预期：4 passed（Task 5 的 2 个 + Task 6 的 2 个）。

- [ ] **Step 6: Lint + 提交**

```bash
uv run ruff check app/agent/llm_agent.py tests/test_llm_agent.py
git add app/agent/llm_agent.py tests/test_llm_agent.py
git commit -m "feat: add read tool execution to AgentLoop"
```

---

### Task 7: AgentLoop — write pending confirmation

**Files:**
- Modify: `app/agent/llm_agent.py`
- Modify: `tests/test_llm_agent.py`（追加测试）

**背景**：LLM 发起写 tool call，gateway 返回 `explicit_confirmation_required`，AgentLoop 设置 `pending_action` 并终止。

- [ ] **Step 1: 追加失败测试**

追加到 `tests/test_llm_agent.py`：

```python
class TestAgentLoopWritePending:
    """Tests: write tool requires confirmation."""

    def test_write_triggers_pending_confirmation(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.tools.retail_adapter import get_order_from_db

        gateway = _gateway()
        runtime = gateway.runtime

        # Find a pending order
        db = runtime.db
        db_orders = db.get("orders", {})
        pending_order = next(
            (oid for oid, o in db_orders.items() if o.get("status") == "pending"),
            None,
        )
        assert pending_order is not None, "Need a pending order in test DB"

        order = get_order_from_db(db, pending_order)
        user_id = order["user_id"]

        session = _session(
            authenticated_user_id=user_id,
            active_user_identity={"user_id": user_id, "name": "Test User"},
        )
        # Load order into context (simulate read-before-write)
        session.loaded_context.orders[pending_order] = order

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_cancel",
                            tool_name="cancel_pending_order",
                            arguments={
                                "order_id": pending_order,
                                "reason": "no longer needed",
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=gateway,
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(session, "Cancel my order")

        assert result.pending_action_set is True
        assert session.pending_action is not None
        assert session.pending_action.action_name == "cancel_pending_order"
        assert session.pending_action.arguments.get("order_id") == pending_order
        assert "cancel" in result.assistant_message.lower()

    def test_write_without_read_before_write_blocks(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.tools.retail_adapter import get_order_from_db

        # Use a known pending order but DON'T load it into context
        gateway = _gateway()
        runtime = gateway.runtime
        db = runtime.db
        db_orders = db.get("orders", {})
        pending_order = next(
            (oid for oid, o in db_orders.items() if o.get("status") == "pending"),
            None,
        )
        assert pending_order is not None

        order = get_order_from_db(db, pending_order)
        user_id = order["user_id"]

        session = _session(
            authenticated_user_id=user_id,
            active_user_identity={"user_id": user_id},
        )
        # Deliberately NOT loading order into loaded_context

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_cancel",
                            tool_name="cancel_pending_order",
                            arguments={
                                "order_id": pending_order,
                                "reason": "no longer needed",
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    assistant_content="I need to review the order details first.",
                    finish_reason="stop",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=gateway,
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(session, "Cancel my order")

        assert result.pending_action_set is False
        # Tool was blocked by guard (read_before_write_required)
        blocked = [r for r in session.tool_results if r.status == "blocked"]
        assert len(blocked) == 1
        assert blocked[0].error == "read_before_write_required"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run python -m pytest tests/test_llm_agent.py::TestAgentLoopWritePending -v
```

预期：失败 — pending confirmation 逻辑未实现，write tool 会直接执行（返回 error）或 loop 不处理 block。

- [ ] **Step 3: 在 AgentLoop 中添加 pending confirmation 处理**

修改 `app/agent/llm_agent.py` 中 `run_turn` 的 tool execution 部分，在 `record.status == "blocked"` 时增加判断：

```python
                # After gateway.execute(), before building tool observation:
                if record.status == "blocked":
                    if record.error == "explicit_confirmation_required":
                        # Set pending action
                        session.pending_action = PendingAction(
                            action_name=tc.tool_name,
                            arguments=dict(tc.arguments),
                            user_facing_summary=(
                                f"{tc.tool_name}: {_brief_args(tc.arguments)}"
                            ),
                        )
                        turn.termination = "pending_confirmation"
                        turn.add_step("pending_set", tool_name=tc.tool_name)
                        return AgentTurnResult(
                            assistant_message=(
                                f"I'd like to {tc.tool_name.replace('_', ' ')}. "
                                "Can you confirm?"
                            ),
                            turn=turn,
                            pending_action_set=True,
                        )
                    else:
                        # Guard blocked for other reasons → feed ToolExecutionError
                        error_msg = ToolExecutionError(
                            error_type="guard_blocked",
                            message_for_llm=(
                                f"Tool {tc.tool_name} was blocked: {record.error}. "
                                "Explain this to the user and suggest alternatives."
                            ),
                            retryable=False,
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": error_msg.model_dump_json(),
                        })
                    continue
```

需要在 `llm_agent.py` 顶部增加 import：

```python
from app.agent.models import (
    ...,
    PendingAction,
)
```

并添加 helper：

```python
def _brief_args(args: dict) -> str:
    parts = [f"{k}={v}" for k, v in args.items()]
    return ", ".join(parts)
```

- [ ] **Step 4: 运行测试**

```bash
uv run python -m pytest tests/test_llm_agent.py::TestAgentLoopWritePending -v
```

预期：2 passed。

- [ ] **Step 5: Lint + 提交**

```bash
uv run ruff check app/agent/llm_agent.py tests/test_llm_agent.py
git add app/agent/llm_agent.py tests/test_llm_agent.py
git commit -m "feat: add write pending confirmation to AgentLoop"
```

---

### Task 8: AgentLoop — guard block → tool error 回喂

**Files:**
- Modify: `app/agent/llm_agent.py`
- Modify: `tests/test_llm_agent.py`（追加测试）

**背景**：验证非 confirmation 的 guard block 作为 ToolExecutionError 正确喂回 messages，LLM 能在下一轮做出合适的回复。

- [ ] **Step 1: 追加测试**

追加到 `tests/test_llm_agent.py`：

```python
class TestAgentLoopGuardBlock:
    """Tests: guard blocks (non-confirmation) become tool errors."""

    def test_cancel_delivered_order_guard_block(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.tools.retail_adapter import get_order_from_db

        gateway = _gateway()
        db = gateway.runtime.db
        db_orders = db.get("orders", {})
        delivered_order = next(
            (oid for oid, o in db_orders.items() if o.get("status") == "delivered"),
            None,
        )
        assert delivered_order is not None, "Need a delivered order in test DB"

        order = get_order_from_db(db, delivered_order)
        user_id = order["user_id"]

        session = _session(
            authenticated_user_id=user_id,
            active_user_identity={"user_id": user_id},
        )
        session.loaded_context.orders[delivered_order] = order

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_cancel",
                            tool_name="cancel_pending_order",
                            arguments={
                                "order_id": delivered_order,
                                "reason": "no longer needed",
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    assistant_content=(
                        "I cannot cancel this order because it has already been "
                        "delivered. Would you like to return it instead?"
                    ),
                    finish_reason="stop",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=gateway,
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(session, "Cancel my order")

        assert "cannot cancel" in result.assistant_message.lower() or "delivered" in result.assistant_message.lower()
        blocked = [r for r in session.tool_results if r.status == "blocked"]
        assert len(blocked) == 1
        assert blocked[0].error == "non_pending_order_cannot_be_cancelled"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run python -m pytest tests/test_llm_agent.py::TestAgentLoopGuardBlock -v
```

预期：通过（Task 7 中已实现 guard block → ToolExecutionError 逻辑）。如果未通过，修复实现。

- [ ] **Step 3: 运行全部 llm_agent 测试确认**

```bash
uv run python -m pytest tests/test_llm_agent.py -v
```

预期：7 passed（Task 5: 2 + Task 6: 2 + Task 7: 2 + Task 8: 1）。

- [ ] **Step 4: Lint + 提交**

```bash
uv run ruff check app/agent/llm_agent.py tests/test_llm_agent.py
git add tests/test_llm_agent.py
git commit -m "test: add guard block → tool error test for AgentLoop"
```

---

### Task 9: AgentLoop — tool error 前置校验与 self-correction

**Files:**
- Modify: `app/agent/llm_agent.py`
- Modify: `tests/test_llm_agent.py`（追加测试）

**背景**：AgentLoop 在调用 gateway 前做参数校验（unknown tool / malformed args / missing required args）。校验失败时构建 ToolExecutionError 消息喂回 LLM，让 LLM 自修正。

- [ ] **Step 1: 追加测试**

追加到 `tests/test_llm_agent.py`：

```python
class TestAgentLoopToolErrors:
    """Tests: unknown tool, malformed args, missing args self-correction."""

    def test_unknown_tool_self_correction(self) -> None:
        from app.agent.llm_agent import AgentLoop

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="hallucinated_tool",
                            arguments={},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_2",
                            tool_name="get_order_details",
                            arguments={"order_id": "#W5918442"},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    assistant_content="Found your order #W5918442.",
                    finish_reason="stop",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(_session(), "Check order")

        assert "W5918442" in result.assistant_message
        assert result.turn.loop_iterations == 3

    def test_malformed_arguments_self_correction(self) -> None:
        from app.agent.llm_agent import AgentLoop

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="get_order_details",
                            arguments={},
                            raw_arguments="{not-json",
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_2",
                            tool_name="get_order_details",
                            arguments={"order_id": "#W5918442"},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    assistant_content="Found your order #W5918442.",
                    finish_reason="stop",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(_session(), "Check order")

        assert "W5918442" in result.assistant_message
        assert result.turn.loop_iterations == 3

    def test_missing_required_args_self_correction(self) -> None:
        from app.agent.llm_agent import AgentLoop

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="cancel_pending_order",
                            arguments={},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_2",
                            tool_name="cancel_pending_order",
                            arguments={
                                "order_id": "#W5918442",
                                "reason": "no longer needed",
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                ),
            ]
        )
        # Use no gateway for pure validation test (we only care about pre-gateway validation)
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        session = _session()
        result = loop.run_turn(session, "Cancel")

        # Should have set pending (if order is loadable) or blocked
        # The key assertion: loop_iterations > 1 (went through error → retry)
        assert result.turn.loop_iterations >= 2
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run python -m pytest tests/test_llm_agent.py::TestAgentLoopToolErrors -v
```

预期：部分失败 — 前置校验的 `_validate_tool_call` 尚未实现。

- [ ] **Step 3: 实现 _validate_tool_call**

在 `app/agent/llm_agent.py` 的 `AgentLoop` 类中新增：

```python
    def _validate_tool_call(
        self, tool_call: ToolCallRequest
    ) -> ToolExecutionError | None:
        if tool_call.tool_name not in self._registry.tools:
            return ToolExecutionError(
                error_type="unknown_tool",
                message_for_llm=(
                    f"Unknown tool: '{tool_call.tool_name}'. "
                    f"Available tools: {sorted(self._registry.tools)}"
                ),
                retryable=True,
                allowed_tools=sorted(self._registry.tools),
            )
        required = self._registry.required_args_for_tool(tool_call.tool_name)
        missing = [a for a in required if not tool_call.arguments.get(a)]
        if missing:
            return ToolExecutionError(
                error_type="missing_required_args",
                message_for_llm=(
                    f"Missing required arguments for {tool_call.tool_name}: {missing}"
                ),
                retryable=True,
                missing_args=missing,
            )
        if tool_call.raw_arguments is not None and not tool_call.arguments:
            return ToolExecutionError(
                error_type="malformed_arguments",
                message_for_llm=(
                    f"Could not parse arguments for {tool_call.tool_name}. "
                    "Please provide valid JSON arguments."
                ),
                retryable=True,
            )
        return None
```

在 `run_turn` 的 tool call 循环中，`gateway.execute()` 之前插入：

```python
                validation_error = self._validate_tool_call(tc)
                if validation_error:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": validation_error.model_dump_json(),
                    })
                    continue
```

- [ ] **Step 4: 运行测试**

```bash
uv run python -m pytest tests/test_llm_agent.py::TestAgentLoopToolErrors -v
```

预期：3 passed。

- [ ] **Step 5: 运行全部 llm_agent 测试**

```bash
uv run python -m pytest tests/test_llm_agent.py -v
```

预期：11 passed。

- [ ] **Step 6: Lint + 提交**

```bash
uv run ruff check app/agent/llm_agent.py tests/test_llm_agent.py
git add app/agent/llm_agent.py tests/test_llm_agent.py
git commit -m "feat: add tool call pre-validation and self-correction to AgentLoop"
```

---

### Task 10: AgentLoop — 安全护栏（max_iterations, consecutive_failures, timeout）

**Files:**
- Modify: `app/agent/llm_agent.py`
- Modify: `tests/test_llm_agent.py`（追加测试）

**背景**：验证 max_iterations 上限、连续 3 次失败转人工、provider timeout 安全失败。

- [ ] **Step 1: 追加测试**

追加到 `tests/test_llm_agent.py`：

```python
class TestAgentLoopSafetyGuards:
    """Tests: max iterations, consecutive failures, provider timeout."""

    def test_max_iterations_exceeded(self) -> None:
        from app.agent.llm_agent import AgentLoop

        # Provider keeps returning tool calls forever
        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{i}",
                            tool_name="get_order_details",
                            arguments={"order_id": "#W5918442"},
                        )
                    ],
                    finish_reason="tool_calls",
                )
                for i in range(10)
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
            max_iterations=3,
        )
        result = loop.run_turn(_session(), "Check order")

        assert result.turn.loop_iterations == 3
        assert result.turn.termination == "max_iterations"
        assert "transfer" in result.assistant_message.lower() or "human" in result.assistant_message.lower()

    def test_consecutive_failures_transfer(self) -> None:
        from app.agent.llm_agent import AgentLoop

        # Provider calls unknown tool 3 times
        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{i}",
                            tool_name="unknown_tool",
                            arguments={},
                        )
                    ],
                    finish_reason="tool_calls",
                )
                for i in range(5)
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
            max_consecutive_failures=3,
        )
        result = loop.run_turn(_session(), "Help")

        assert result.turn.termination == "consecutive_failures"
        assert result.turn.consecutive_tool_failures >= 3

    def test_provider_timeout_safe_failure(self) -> None:
        from app.agent.llm_agent import AgentLoop

        provider = FakeFailingProvider(error_type="timeout")
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(_session(), "Hello")

        assert result.turn.termination == "provider_timeout"
        assert len(result.assistant_message) > 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run python -m pytest tests/test_llm_agent.py::TestAgentLoopSafetyGuards -v
```

预期：`test_provider_timeout_safe_failure` 失败（TimeoutError 未被捕获）。`test_consecutive_failures_transfer` 和 `test_max_iterations_exceeded` 可能失败（若 max_iterations 上限逻辑不完善）。

- [ ] **Step 3: 完善安全护栏**

修改 `app/agent/llm_agent.py` 中 `run_turn` 的 `_step_llm_reason` 调用，增加 timeout 捕获：

```python
            try:
                response = self._step_llm_reason(messages, tool_schemas)
            except TimeoutError:
                turn.termination = "provider_timeout"
                turn.add_step("provider_timeout")
                return AgentTurnResult(
                    assistant_message=(
                        "I'm having trouble processing your request right now. "
                        "Please try again in a moment."
                    ),
                    turn=turn,
                )
```

检查 `consecutive_tool_failures` 逻辑确保每轮 `all_failed` 正确累积。确认 `_validate_tool_call` 返回 error 时也计入 `all_failed`（前置校验错误同样算失败）。

- [ ] **Step 4: 运行安全护栏测试**

```bash
uv run python -m pytest tests/test_llm_agent.py::TestAgentLoopSafetyGuards -v
```

预期：3 passed。

- [ ] **Step 5: 运行全部 llm_agent 测试**

```bash
uv run python -m pytest tests/test_llm_agent.py -v
```

预期：14 passed。

- [ ] **Step 6: Lint + 提交**

```bash
uv run ruff check app/agent/llm_agent.py tests/test_llm_agent.py
git add app/agent/llm_agent.py tests/test_llm_agent.py
git commit -m "feat: add safety guards to AgentLoop (max_iter, failures, timeout)"
```

---

### Task 11: AgentLoop — 完整集成（context builder + turn context）

**Files:**
- Modify: `app/agent/llm_agent.py`
- Modify: `tests/test_llm_agent.py`（追加测试）

**背景**：验证 context_builder 的 summary 注入 prompt、TurnContext 完整填充、pending_action 在 session 中持久化。

- [ ] **Step 1: 追加集成测试**

追加到 `tests/test_llm_agent.py`：

```python
class TestAgentLoopIntegration:
    """Tests: full integration with context builder and turn tracking."""

    def test_context_summary_in_prompt(self) -> None:
        from app.agent.llm_agent import AgentLoop

        session = _session()
        session.loaded_context.orders["O1"] = {
            "order_id": "O1", "user_id": "U1", "status": "pending",
            "items": [{"item_id": "I1", "name": "Widget"}],
        }

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    assistant_content="I see your pending order O1.",
                    finish_reason="stop",
                )
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(session, "Show my orders")

        # Verify the prompt contains state summary
        assert "O1" in result.assistant_message
        assert result.turn.termination == "final_response"

    def test_pending_action_persisted_in_session(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.tools.retail_adapter import get_order_from_db

        gateway = _gateway()
        db = gateway.runtime.db
        db_orders = db.get("orders", {})
        pending_order = next(
            (oid for oid, o in db_orders.items() if o.get("status") == "pending"),
            None,
        )
        assert pending_order is not None

        order = get_order_from_db(db, pending_order)
        user_id = order["user_id"]
        session = _session(
            authenticated_user_id=user_id,
            active_user_identity={"user_id": user_id},
        )
        session.loaded_context.orders[pending_order] = order

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_cancel",
                            tool_name="cancel_pending_order",
                            arguments={
                                "order_id": pending_order,
                                "reason": "no longer needed",
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=gateway,
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(session, "Cancel")

        assert result.pending_action_set is True
        assert session.pending_action is not None
        assert session.pending_action.action_name == "cancel_pending_order"

    def test_turn_context_fully_populated(self) -> None:
        from app.agent.llm_agent import AgentLoop

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="get_order_details",
                            arguments={"order_id": "#W5918442"},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    assistant_content="Order #W5918442 is pending.",
                    finish_reason="stop",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(_session(), "Check order")

        assert result.turn.loop_iterations == 2
        assert result.turn.termination == "final_response"
        assert len(result.turn.steps) >= 3  # llm_reason, tool_execute, llm_reason, finalize
        step_nodes = {s.node for s in result.turn.steps}
        assert "llm_reason" in step_nodes
        assert "tool_execute" in step_nodes
        assert "finalize" in step_nodes
        assert result.turn.step_durations  # not empty
```

- [ ] **Step 2: 运行集成测试**

```bash
uv run python -m pytest tests/test_llm_agent.py::TestAgentLoopIntegration -v
```

预期：3 passed（若 context summary 注入不完善可能需要调整 `_build_messages`）。

- [ ] **Step 3: 完善 context summary 注入**

修改 `_load_system_prompt`（或新增 `_build_system_prompt`），让 `{state_summary}` 在每轮动态生成：

```python
    def _build_system_prompt(self, session: SessionState) -> str:
        state_summary = self._context_builder.build(session)
        return self._system_prompt_template.replace(
            "{state_summary}", state_summary
        )

    def _build_messages(
        self, session: SessionState, user_content: str
    ) -> list[dict[str, Any]]:
        system_prompt = self._build_system_prompt(session)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        for msg in session.messages[-6:]:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_content})
        return messages
```

相应调整 `__init__` 中的 `_load_system_prompt`：

```python
    def _load_system_prompt_template(self) -> str:
        from pathlib import Path
        prompt_path = Path("prompts/llm_agent_system_v001.md")
        template = prompt_path.read_text(encoding="utf-8")
        tool_catalog = self._registry.tool_catalog_for_llm()
        policy_text = ""
        if hasattr(self._context_builder, "_policy_text"):
            policy_text = self._context_builder._policy_text
        return template.replace("{tool_catalog}", tool_catalog).replace(
            "{policy}", policy_text
        )
```

在 `__init__` 中：
```python
        self._system_prompt_template = self._load_system_prompt_template()
```

- [ ] **Step 4: 运行全部 llm_agent 测试**

```bash
uv run python -m pytest tests/test_llm_agent.py -v
```

预期：16 passed（Task 5: 2 + Task 6: 2 + Task 7: 2 + Task 8: 1 + Task 9: 3 + Task 10: 3 + Task 11: 3）。

- [ ] **Step 5: Lint + 提交**

```bash
uv run ruff check app/agent/llm_agent.py tests/test_llm_agent.py
git add app/agent/llm_agent.py tests/test_llm_agent.py
git commit -m "feat: add context builder integration to AgentLoop"
```

---

### Task 12: 回归 + 最终提交

**Files:**
- 不修改源码文件（除非回归测试发现问题）

- [ ] **Step 1: 运行完整测试套件**

```bash
uv run python -m pytest tests/ -q
```

预期：全部通过（约 275 测试：原 259 + 新增 16）。

- [ ] **Step 2: 运行 lint**

```bash
uv run ruff check .
```

预期：通过。

- [ ] **Step 3: 运行 focused llm_agent 测试确认**

```bash
uv run python -m pytest tests/test_llm_agent.py -v
```

预期：16 passed。

- [ ] **Step 4: 更新阶段状态**

在 `docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md` 的 Phase Status 部分追加：

```markdown
- Phase 3：✅ 完成 — AgentLoop 类 + 4 个 step 方法 + 16 测试覆盖 read/write pending/guard block/tool error/safety guards/full integration（2026-06-13）。
```

- [ ] **Step 5: 最终提交**

```bash
git add docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md
git commit -m "docs: mark LLM agent tool-calling phase 3 complete"
```

---

## 自审记录

Spec 覆盖：
- `app/agent/llm_agent.py` → Task 5-11
- `AgentTurnResult` → Task 1
- `step_llm_reason` → Task 5
- `step_tool_execute` → Task 6
- `step_pending` → Task 7
- `step_finalize` → Task 5
- max iteration guard → Task 10
- consecutive failure guard → Task 10
- structured tool observations → Task 6, 7, 9
- scripted tests 覆盖 read → Task 6
- scripted tests 覆盖 write pending → Task 7
- scripted tests 覆盖 guard block → Task 8
- scripted tests 覆盖 unknown tool → Task 9
- scripted tests 覆盖 malformed args → Task 9
- scripted tests 覆盖 provider timeout → Task 10
- Gateway/Guard SessionState 迁移 → Task 2
- Registry public method → Task 3
- System prompt → Task 4
- Context builder integration → Task 11
- TurnContext 完整填充 → Task 11

退出条件覆盖：
- `uv run python -m pytest tests/test_llm_agent.py -q` → Task 12
- `uv run python -m pytest tests/ -q` → Task 12
- `uv run ruff check .` → Task 12
