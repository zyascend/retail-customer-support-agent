# LLM Agent Tool-Calling 架构实现计划

> **给 agentic workers：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐步执行本计划。步骤使用 checkbox（`- [ ]`）语法跟踪进度。

**目标：** 将 retail support agent 逐步迁移到单一 LLM tool-calling runtime，同时用 harness 保留确定性测试能力，而不是维护一套并行 deterministic runtime。

**架构：** 这是一个多阶段长期路径。Phase 1 先增加 tool-calling contract、JSON Schema 和 deterministic harness，不切换当前 runtime；后续阶段依次拆分 state、增加 context builder、实现 LLM loop、切换 `AgentRuntime`、删除旧 pipeline，并适配 eval/live benchmark。

**技术栈：** Python、项目现有 Pydantic 兼容层、pytest、现有 OpenAI-compatible `openai` package、现有 retail tool registry/gateway/guard/eval 模块。

---

## 来源文档

主 spec：

`docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md`

架构讨论文档：

`docs/design-llm-agent-tool-calling.md`

## 长期阶段

这项工作不要当成一个 session 内完成。每个阶段结束时，仓库都必须保持可运行、可测试、可继续接手。

| 阶段 | 名称 | Runtime 影响 | 退出条件 |
|------|------|--------------|----------|
| Phase 1 | Tool-calling contract、schema、harness | 不切换 runtime | 现有测试通过；provider/harness/schema 测试通过 |
| Phase 2 | State 拆分与 context builder | 当前 runtime 通过兼容层继续工作 | trace 和 summary 测试通过；现有 eval 仍可运行 |
| Phase 3 | 独立 LLM agent loop | 新 loop 存在，但还不是主 runtime | scripted loop 测试覆盖 read、write pending、guard block、失败路径 |
| Phase 4 | Runtime 切换与旧 pipeline 删除 | `AgentRuntime` 只走 LLM runtime | scripted curated/generalized/synthetic smoke 通过；无 deterministic runtime mode |
| Phase 5 | Eval 适配与 live benchmark | Eval 支持 scripted/live 分层 | report 包含 backend、token/tool 指标、failure category |
| Phase 6 | 延后 replay/debugging | 新增 replay harness | trace replay 能复现一次已记录 turn |

下面只把 **Phase 1** 展开到可直接执行的粒度。开始 Phase 2 前，必须基于 Phase 1 完成后的代码状态重新生成阶段专用计划。

## Phase Status

- Phase 1：✅ 完成 — provider/harness/schema 测试（15 新增）、完整 pytest（243 existing + 15 new = 258 passed）、ruff 全部通过（2026-06-13）。
- Phase 2：✅ 完成 — SessionState/TurnContext 模型、ContextBuilder、259 测试通过、eval 11/11 通过（2026-06-13）。
- Phase 3：✅ 完成 — AgentLoop 类 + 4 个 step 方法、SessionState/Gateway/Guard 迁移、16 测试覆盖 read/write pending/guard block/tool error/safety guards/integration、278 测试通过、ruff 全部通过（2026-06-13）。
- Phase 4：✅ 完成 — runtime 切换 pre-flight + AgentLoop + post-process、删除 pipeline/plan_handlers/graph（784 行）、精简 parsers（-196 行）、删除 builders.py、240 测试通过、ruff 通过、eval smoke 不崩溃（2026-06-14）。

---

## 文件结构

Phase 1 创建后续阶段依赖的稳定契约。

```
app/agent/
  models.py              ← 新增 ToolCallRequest、ToolCallResponse、ToolExecutionError
  providers.py           ← 新增 chat_with_tools protocol method 和 provider/harness 实现

app/tools/
  registry.py            ← 新增 tool_schemas_for_llm()

tests/
  test_tool_calling_provider.py  ← 新增 provider/harness 测试
  test_tool_schema.py            ← 新增 registry JSON Schema 测试
```

Phase 2 以后会涉及这些文件：

```
app/agent/
  context_builder.py     ← Phase 2 新增
  llm_agent.py           ← Phase 3 新增
  runtime.py             ← Phase 4 切换
  guard.py               ← Phase 3 或 Phase 4 增加 block_context

app/tools/
  gateway.py             ← Phase 3 或 Phase 4 增加结构化 tool error

app/eval/
  cases.py               ← Phase 5 增加 required_tools / forbidden_tools
  runner.py              ← Phase 5 增加 eval_backend 和 scripted/live report
```

---

## Phase 1：Tool-Calling Contract、Schema、Harness

### Task 1：新增 Tool-Calling Models

**文件：**
- 修改：`app/agent/models.py`
- 新增：`tests/test_tool_calling_provider.py`

- [ ] **Step 1：编写失败测试**

创建 `tests/test_tool_calling_provider.py`：

```python
from __future__ import annotations

from app.agent.models import ToolCallRequest, ToolCallResponse, ToolExecutionError


def test_tool_call_response_defaults_to_no_tool_calls() -> None:
    response = ToolCallResponse()

    assert response.assistant_content is None
    assert response.tool_calls == []
    assert response.finish_reason is None
    assert response.token_usage is None


def test_tool_call_request_preserves_raw_arguments() -> None:
    request = ToolCallRequest(
        id="call_1",
        tool_name="get_order_details",
        arguments={"order_id": "ORDER-1"},
        raw_arguments='{"order_id":"ORDER-1"}',
    )

    assert request.id == "call_1"
    assert request.tool_name == "get_order_details"
    assert request.arguments == {"order_id": "ORDER-1"}
    assert request.raw_arguments == '{"order_id":"ORDER-1"}'


def test_tool_execution_error_has_retry_metadata() -> None:
    error = ToolExecutionError(
        error_type="missing_required_args",
        message_for_llm="The tool call is missing order_id.",
        retryable=True,
        missing_args=["order_id"],
    )

    assert error.status == "error"
    assert error.retryable is True
    assert error.missing_args == ["order_id"]
```

- [ ] **Step 2：运行测试，确认失败**

运行：

```bash
uv run python -m pytest tests/test_tool_calling_provider.py -q
```

预期：失败，报 `ToolCallRequest`、`ToolCallResponse`、`ToolExecutionError` import error。

- [ ] **Step 3：新增 models**

在 `app/agent/models.py` 的 `ToolCall` 后增加：

```python
class ToolCallRequest(BaseModel):
    id: str
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    raw_arguments: Optional[str] = None


class ToolCallResponse(BaseModel):
    assistant_content: Optional[str] = None
    tool_calls: List[ToolCallRequest] = Field(default_factory=list)
    finish_reason: Optional[str] = None
    token_usage: Optional[Dict[str, Any]] = None
    raw: Optional[Dict[str, Any]] = None


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
    missing_args: List[str] = Field(default_factory=list)
    allowed_tools: Optional[List[str]] = None
```

- [ ] **Step 4：运行 model 测试**

运行：

```bash
uv run python -m pytest tests/test_tool_calling_provider.py -q
```

预期：通过。

- [ ] **Step 5：运行 focused lint**

运行：

```bash
uv run ruff check app/agent/models.py tests/test_tool_calling_provider.py
```

预期：通过。

- [ ] **Step 6：提交**

运行：

```bash
git add app/agent/models.py tests/test_tool_calling_provider.py
git commit -m "feat: add tool-calling response models"
```

预期：提交成功。

### Task 2：新增 Scripted 和 Failing Tool-Calling Providers

**文件：**
- 修改：`app/agent/providers.py`
- 修改：`tests/test_tool_calling_provider.py`

- [ ] **Step 1：扩展 provider 测试**

追加到 `tests/test_tool_calling_provider.py`：

```python
import pytest

from app.agent.providers import (
    FakeFailingProvider,
    ScriptedToolCallingProvider,
)


def test_scripted_provider_returns_scripted_tool_call() -> None:
    provider = ScriptedToolCallingProvider(
        responses=[
            ToolCallResponse(
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        tool_name="get_order_details",
                        arguments={"order_id": "ORDER-1"},
                    )
                ],
                finish_reason="tool_calls",
            )
        ]
    )

    response = provider.chat_with_tools(messages=[], tools=[])

    assert response.tool_calls[0].tool_name == "get_order_details"
    assert response.finish_reason == "tool_calls"


def test_scripted_provider_returns_final_text() -> None:
    provider = ScriptedToolCallingProvider(
        responses=[
            ToolCallResponse(
                assistant_content="I found your order.",
                finish_reason="stop",
            )
        ]
    )

    response = provider.chat_with_tools(messages=[], tools=[])

    assert response.assistant_content == "I found your order."
    assert response.tool_calls == []


def test_scripted_provider_raises_when_script_exhausted() -> None:
    provider = ScriptedToolCallingProvider(responses=[])

    with pytest.raises(RuntimeError, match="No scripted tool-calling responses remain"):
        provider.chat_with_tools(messages=[], tools=[])


def test_fake_failing_provider_timeout() -> None:
    provider = FakeFailingProvider(error_type="timeout")

    with pytest.raises(TimeoutError):
        provider.chat_with_tools(messages=[], tools=[])


def test_fake_failing_provider_malformed_arguments_response() -> None:
    provider = FakeFailingProvider(error_type="malformed_arguments")

    response = provider.chat_with_tools(messages=[], tools=[])

    assert response.tool_calls[0].tool_name == "get_order_details"
    assert response.tool_calls[0].arguments == {}
    assert response.tool_calls[0].raw_arguments == "{not-json"
```

- [ ] **Step 2：运行 provider 测试，确认失败**

运行：

```bash
uv run python -m pytest tests/test_tool_calling_provider.py -q
```

预期：失败，报 `ScriptedToolCallingProvider` 和 `FakeFailingProvider` import error。

- [ ] **Step 3：更新 provider protocol 并新增 harness providers**

在 `app/agent/providers.py` 中增加 import：

```python
from app.agent.models import ToolCallRequest, ToolCallResponse
```

修改 `LLMProvider`：

```python
class LLMProvider(Protocol):
    def json(
        self, messages: List[Dict[str, str]], schema: Dict[str, Any]
    ) -> Dict[str, Any]: ...

    def chat(self, messages: List[Dict[str, str]]) -> str: ...

    def chat_with_tools(
        self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> ToolCallResponse: ...
```

在 `DeterministicProvider` 附近新增：

```python
class ScriptedToolCallingProvider:
    def __init__(self, responses: List[ToolCallResponse]) -> None:
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def json(
        self, messages: List[Dict[str, str]], schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {}

    def chat(self, messages: List[Dict[str, str]]) -> str:
        if not self._responses:
            raise RuntimeError("No scripted tool-calling responses remain")
        response = self._responses.pop(0)
        return response.assistant_content or ""

    def chat_with_tools(
        self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> ToolCallResponse:
        self.calls.append({"messages": messages, "tools": tools})
        if not self._responses:
            raise RuntimeError("No scripted tool-calling responses remain")
        return self._responses.pop(0)


class FakeFailingProvider:
    def __init__(self, error_type: str) -> None:
        self.error_type = error_type

    def json(
        self, messages: List[Dict[str, str]], schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {}

    def chat(self, messages: List[Dict[str, str]]) -> str:
        if self.error_type == "timeout":
            raise TimeoutError("simulated provider timeout")
        return ""

    def chat_with_tools(
        self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> ToolCallResponse:
        if self.error_type == "timeout":
            raise TimeoutError("simulated provider timeout")
        if self.error_type == "unknown_tool":
            return ToolCallResponse(
                tool_calls=[
                    ToolCallRequest(
                        id="call_unknown",
                        tool_name="hallucinated_tool",
                        arguments={},
                    )
                ],
                finish_reason="tool_calls",
            )
        if self.error_type == "malformed_arguments":
            return ToolCallResponse(
                tool_calls=[
                    ToolCallRequest(
                        id="call_malformed",
                        tool_name="get_order_details",
                        arguments={},
                        raw_arguments="{not-json",
                    )
                ],
                finish_reason="tool_calls",
            )
        if self.error_type == "missing_args":
            return ToolCallResponse(
                tool_calls=[
                    ToolCallRequest(
                        id="call_missing",
                        tool_name="get_order_details",
                        arguments={},
                    )
                ],
                finish_reason="tool_calls",
            )
        raise RuntimeError(f"Unsupported fake failure type: {self.error_type}")
```

- [ ] **Step 4：给 DeterministicProvider 增加 tool-calling 兼容方法**

修改 `app/agent/providers.py` 中的 `DeterministicProvider`：

```python
class DeterministicProvider:
    def json(
        self, messages: List[Dict[str, str]], schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {}

    def chat(self, messages: List[Dict[str, str]]) -> str:
        if not messages:
            return ""
        return messages[-1].get("content", "")

    def chat_with_tools(
        self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> ToolCallResponse:
        return ToolCallResponse(
            assistant_content=self.chat(messages), finish_reason="stop"
        )
```

- [ ] **Step 5：运行 provider 测试**

运行：

```bash
uv run python -m pytest tests/test_tool_calling_provider.py -q
```

预期：通过。

- [ ] **Step 6：运行 focused lint**

运行：

```bash
uv run ruff check app/agent/providers.py tests/test_tool_calling_provider.py
```

预期：通过。

- [ ] **Step 7：提交**

运行：

```bash
git add app/agent/providers.py tests/test_tool_calling_provider.py
git commit -m "feat: add deterministic tool-calling harness providers"
```

预期：提交成功。

### Task 3：新增 DeepSeek Tool-Calling Adapter

**文件：**
- 修改：`app/agent/providers.py`
- 修改：`tests/test_tool_calling_provider.py`

- [ ] **Step 1：新增 response normalization 测试**

追加到 `tests/test_tool_calling_provider.py`：

```python
from app.agent.providers import normalize_tool_calling_message


def test_normalize_openai_style_tool_call_message() -> None:
    message = {
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "function": {
                    "name": "get_order_details",
                    "arguments": '{"order_id":"ORDER-1"}',
                },
            }
        ],
    }

    response = normalize_tool_calling_message(
        message=message,
        finish_reason="tool_calls",
        token_usage={"prompt_tokens": 10, "completion_tokens": 5},
        raw={"id": "chatcmpl_1"},
    )

    assert response.tool_calls[0].id == "call_1"
    assert response.tool_calls[0].tool_name == "get_order_details"
    assert response.tool_calls[0].arguments == {"order_id": "ORDER-1"}
    assert response.tool_calls[0].raw_arguments == '{"order_id":"ORDER-1"}'
    assert response.finish_reason == "tool_calls"
    assert response.token_usage == {"prompt_tokens": 10, "completion_tokens": 5}


def test_normalize_malformed_tool_arguments_preserves_raw() -> None:
    message = {
        "content": None,
        "tool_calls": [
            {
                "id": "call_bad",
                "function": {
                    "name": "get_order_details",
                    "arguments": "{not-json",
                },
            }
        ],
    }

    response = normalize_tool_calling_message(
        message=message,
        finish_reason="tool_calls",
        token_usage=None,
        raw={},
    )

    assert response.tool_calls[0].arguments == {}
    assert response.tool_calls[0].raw_arguments == "{not-json"


def test_normalize_final_assistant_message() -> None:
    response = normalize_tool_calling_message(
        message={"content": "Done.", "tool_calls": []},
        finish_reason="stop",
        token_usage=None,
        raw={},
    )

    assert response.assistant_content == "Done."
    assert response.tool_calls == []
```

- [ ] **Step 2：运行 normalization 测试，确认失败**

运行：

```bash
uv run python -m pytest tests/test_tool_calling_provider.py -q
```

预期：失败，报 `normalize_tool_calling_message` import error。

- [ ] **Step 3：新增 normalization helper**

保持 `app/agent/providers.py` 现有 typing imports：

```python
from typing import Any, Dict, List, Optional, Protocol
```

在 `_extract_json_block` 下方新增：

```python
def normalize_tool_calling_message(
    *,
    message: Dict[str, Any],
    finish_reason: Optional[str],
    token_usage: Optional[Dict[str, Any]],
    raw: Optional[Dict[str, Any]],
) -> ToolCallResponse:
    tool_calls: List[ToolCallRequest] = []
    for index, raw_call in enumerate(message.get("tool_calls") or []):
        function = raw_call.get("function") or {}
        raw_arguments = function.get("arguments")
        arguments: Dict[str, Any] = {}
        if isinstance(raw_arguments, str) and raw_arguments.strip():
            try:
                parsed = json.loads(raw_arguments)
                if isinstance(parsed, dict):
                    arguments = parsed
            except json.JSONDecodeError:
                arguments = {}
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        tool_calls.append(
            ToolCallRequest(
                id=str(raw_call.get("id") or f"call_{index}"),
                tool_name=str(function.get("name") or ""),
                arguments=arguments,
                raw_arguments=raw_arguments if isinstance(raw_arguments, str) else None,
            )
        )
    return ToolCallResponse(
        assistant_content=message.get("content"),
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        token_usage=token_usage,
        raw=raw,
    )
```

- [ ] **Step 4：实现 DeepSeekProvider.chat_with_tools**

在 `DeepSeekProvider` 中新增：

```python
def chat_with_tools(
    self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
) -> ToolCallResponse:
    response = self.client.chat.completions.create(
        model=self.model,
        messages=messages,
        tools=tools,
    )
    choice = response.choices[0]
    message = choice.message
    message_dict = {
        "content": getattr(message, "content", None),
        "tool_calls": [],
    }
    for tool_call in getattr(message, "tool_calls", None) or []:
        function = getattr(tool_call, "function", None)
        message_dict["tool_calls"].append(
            {
                "id": getattr(tool_call, "id", ""),
                "function": {
                    "name": getattr(function, "name", ""),
                    "arguments": getattr(function, "arguments", ""),
                },
            }
        )
    usage = getattr(response, "usage", None)
    token_usage = None
    if usage is not None:
        token_usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
        }
    return normalize_tool_calling_message(
        message=message_dict,
        finish_reason=getattr(choice, "finish_reason", None),
        token_usage=token_usage,
        raw=None,
    )
```

- [ ] **Step 5：运行 provider 测试**

运行：

```bash
uv run python -m pytest tests/test_tool_calling_provider.py -q
```

预期：通过。

- [ ] **Step 6：运行 focused lint**

运行：

```bash
uv run ruff check app/agent/providers.py tests/test_tool_calling_provider.py
```

预期：通过。

- [ ] **Step 7：提交**

运行：

```bash
git add app/agent/providers.py tests/test_tool_calling_provider.py
git commit -m "feat: add DeepSeek tool-calling adapter"
```

预期：提交成功。

### Task 4：从 Registry 生成 Tool Schemas

**文件：**
- 修改：`app/tools/registry.py`
- 新增：`tests/test_tool_schema.py`

- [ ] **Step 1：编写失败 schema 测试**

创建 `tests/test_tool_schema.py`：

```python
from __future__ import annotations

from app.config import AppConfig
from app.tools.registry import ToolRegistry
from app.tools.retail_adapter import RetailAdapter


def _registry() -> ToolRegistry:
    runtime = RetailAdapter(AppConfig()).create_runtime()
    return ToolRegistry(runtime.tools)


def test_tool_schemas_cover_all_registry_tools() -> None:
    registry = _registry()

    schemas = registry.tool_schemas_for_llm()
    schema_names = {
        schema["function"]["name"]
        for schema in schemas
        if schema.get("type") == "function"
    }

    assert schema_names == set(registry.tools)


def test_cancel_order_schema_has_reason_enum() -> None:
    registry = _registry()

    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "cancel_pending_order"
    )
    params = schema["function"]["parameters"]

    assert params["required"] == ["order_id", "reason"]
    assert params["properties"]["reason"]["enum"] == [
        "no longer needed",
        "ordered by mistake",
    ]
    assert params["additionalProperties"] is False


def test_item_array_schema_declares_string_items() -> None:
    registry = _registry()

    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "modify_pending_order_items"
    )
    params = schema["function"]["parameters"]

    assert params["properties"]["item_ids"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert params["properties"]["new_item_ids"] == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_shipping_method_schema_has_enum() -> None:
    registry = _registry()

    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "modify_pending_order_shipping_method"
    )
    params = schema["function"]["parameters"]

    assert params["properties"]["shipping_method"]["enum"] == [
        "standard",
        "express",
        "overnight",
    ]
```

- [ ] **Step 2：运行 schema 测试，确认失败**

运行：

```bash
uv run python -m pytest tests/test_tool_schema.py -q
```

预期：失败，因为 `tool_schemas_for_llm` 尚不存在。

- [ ] **Step 3：新增 schema 生成 helpers**

在 `app/tools/registry.py` 增加 import：

```python
import inspect
```

在 `ToolRegistry` 中新增：

```python
def tool_schemas_for_llm(self) -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    for name in sorted(self._tools):
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": self._tool_description_for_llm(name),
                    "parameters": self._json_schema_for_tool(name),
                },
            }
        )
    return schemas

def _tool_description_for_llm(self, name: str) -> str:
    constraints = self._tool_constraints_for_llm(name, self.kind(name))
    return f"{name}. {constraints}"

def _json_schema_for_tool(self, name: str) -> dict[str, Any]:
    required = self._required_args_for_tool(name)
    properties = {arg: self._property_schema(name, arg) for arg in required}
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }

def _required_args_for_tool(self, name: str) -> list[str]:
    explicit: dict[str, list[str]] = {
        "find_user_id_by_email": ["email"],
        "find_user_id_by_name_zip": ["first_name", "last_name", "zip"],
        "get_user_details": ["user_id"],
        "get_order_details": ["order_id"],
        "get_product_details": ["product_id"],
        "get_item_details": ["item_id"],
        "calculate": ["expression"],
        "transfer_to_human_agents": ["summary"],
    }
    if name in explicit:
        return explicit[name]
    params_text = self._tool_params_for_llm(name)
    if params_text == "(none)":
        return []
    if params_text != "(see function signature)":
        return [part.strip().split(" ")[0] for part in params_text.split(",")]
    signature = inspect.signature(self.get(name).func)
    return [
        param_name
        for param_name, param in signature.parameters.items()
        if param.default is inspect.Parameter.empty
    ]

def _property_schema(self, tool_name: str, arg_name: str) -> dict[str, Any]:
    if arg_name in {"item_ids", "new_item_ids"}:
        return {"type": "array", "items": {"type": "string"}}
    if tool_name == "cancel_pending_order" and arg_name == "reason":
        return {
            "type": "string",
            "enum": ["no longer needed", "ordered by mistake"],
        }
    if tool_name == "modify_pending_order_shipping_method" and arg_name == "shipping_method":
        return {"type": "string", "enum": ["standard", "express", "overnight"]}
    return {"type": "string"}
```

- [ ] **Step 4：运行 schema 测试**

运行：

```bash
uv run python -m pytest tests/test_tool_schema.py -q
```

预期：通过。

- [ ] **Step 5：运行 focused lint**

运行：

```bash
uv run ruff check app/tools/registry.py tests/test_tool_schema.py
```

预期：通过。

- [ ] **Step 6：提交**

运行：

```bash
git add app/tools/registry.py tests/test_tool_schema.py
git commit -m "feat: generate LLM tool schemas from registry"
```

预期：提交成功。

### Task 5：Phase 1 回归检查

**文件：**
- 预期不修改源码文件。

- [ ] **Step 1：运行 focused tests**

运行：

```bash
uv run python -m pytest tests/test_tool_calling_provider.py tests/test_tool_schema.py -q
```

预期：通过。

- [ ] **Step 2：运行完整测试**

运行：

```bash
uv run python -m pytest tests/ -q
```

预期：通过。

- [ ] **Step 3：运行 lint**

运行：

```bash
uv run ruff check .
```

预期：通过。

- [ ] **Step 4：记录阶段状态**

在 `docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md` 的长期阶段表格下方追加：

```markdown
## Phase Status

- Phase 1：provider/harness/schema 测试、完整 pytest、ruff 全部通过后完成。
- Phase 2：Phase 1 完成后可以开始单独规划。
```

- [ ] **Step 5：提交状态更新**

运行：

```bash
git add docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md
git commit -m "docs: mark LLM tool-calling phase 1 complete"
```

预期：提交成功。

---

## Phase 2 规划摘要：State 拆分与 Context Builder

Phase 1 完成前不要开始 Phase 2。动代码前必须先生成 Phase 2 专用计划。

Phase 2 必须覆盖：

- 引入 `SessionState` 和 `TurnContext` 时的 `ConversationState` 兼容策略
- trace serialization 更新
- `app/agent/context_builder.py`
- auth summary、loaded order summary、pending action summary、write lock summary、token budget 行为测试
- 在 Phase 4 前保持现有 runtime 行为不变

退出条件：

```bash
uv run python -m pytest tests/ -q
uv run ruff check .
```

两个命令都通过，且现有 eval 命令仍能用当前 runtime 运行。

## Phase 3 规划摘要：独立 LLM Agent Loop

Phase 2 完成前不要开始 Phase 3。动代码前必须先生成 Phase 3 专用计划。

Phase 3 必须覆盖：

- `app/agent/llm_agent.py`
- `AgentTurnResult`
- `step_llm_reason`
- `step_tool_execute`
- `step_pending`
- `step_finalize`
- max iteration guard
- consecutive failure guard
- structured tool observations
- scripted tests 覆盖 read、write pending、guard block、unknown tool、malformed args、provider timeout

退出条件：

```bash
uv run python -m pytest tests/test_llm_agent.py -q
uv run python -m pytest tests/ -q
uv run ruff check .
```

所有命令都通过。

## Phase 4 规划摘要：Runtime 切换与旧 Runtime 删除

Phase 3 完成前不要开始 Phase 4。动代码前必须先生成 Phase 4 专用计划。

Phase 4 必须覆盖：

- 将 `AgentRuntime.handle_user_message()` 切到 pre-flight → LLM loop → post-processing
- 删除 `--mode deterministic`
- 删除 `pipeline.py`、`plan_handlers.py`、`graph.py`
- 裁剪只服务旧 intent/slot routing 的 parser/builder 函数
- provider 不可用时安全失败
- scripted smoke 覆盖 curated、generalized、synthetic、pending confirmation flows

退出条件：

```bash
uv run python -m pytest tests/ -q
uv run ruff check .
```

所有命令都通过，并且 runtime code path 不再 import 被删除的 pipeline 模块。

## Phase 5 规划摘要：Eval 与 Live Benchmark

Phase 4 完成前不要开始 Phase 5。动代码前必须先生成 Phase 5 专用计划。

Phase 5 必须覆盖：

- `required_tools`
- `forbidden_tools`
- `eval_backend`
- LLM token/tool/loop metrics
- scripted/live report 分层
- failure category reporting
- live LLM eval 作为手动或 nightly，不进入常规 CI

退出条件：

```bash
uv run python -m pytest tests/test_eval_runner.py -q
uv run python -m pytest tests/ -q
uv run ruff check .
```

所有命令都通过，且 live report 清楚标记 backend 和 failure category。

## Phase 6 规划摘要：Trace Replay Harness

Phase 5 完成前不要开始 Phase 6。动代码前必须先生成 Phase 6 专用计划。

Phase 6 必须覆盖：

- trace artifact 输入格式
- 回放 rendered messages 和 tool observations
- 使用 scripted provider 复现一次已记录 turn
- replay test fixtures

退出条件：

```bash
uv run python -m pytest tests/test_trace_replay_harness.py -q
uv run python -m pytest tests/ -q
uv run ruff check .
```

所有命令都通过。

---

## 自审记录

Spec 覆盖：

- 单 runtime 路线覆盖在 Phase 1-4。
- harness-first determinism 在 Phase 1 实现。
- tool schema generation 在 Phase 1 实现。
- state split 与 context builder 独立到 Phase 2。
- LLM loop 独立到 Phase 3。
- runtime switch 与旧 pipeline 删除独立到 Phase 4。
- eval adaptation 与 live benchmark 分层独立到 Phase 5。
- trace replay 延后到 Phase 6，符合 spec。

歧义处理：

- Phase 1 不改变 runtime 行为。
- 后续每个阶段动代码前都必须重新生成阶段专用计划。
- live LLM eval 永远不作为常规 CI。
- 旧 deterministic runtime 只在 Phase 4 删除，且必须等新 loop 已有 scripted coverage。
