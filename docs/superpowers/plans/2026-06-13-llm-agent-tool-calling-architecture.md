# LLM Agent Tool-Calling Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the retail support agent toward a single LLM tool-calling runtime while preserving deterministic testability through harnesses instead of a parallel deterministic runtime.

**Architecture:** This is a multi-phase path. Phase 1 adds tool-calling contracts, JSON schemas, and deterministic harnesses without changing the current runtime. Later phases split state, add context building, introduce the LLM loop, switch `AgentRuntime`, remove the old pipeline, and adapt eval/live benchmark reporting.

**Tech Stack:** Python, Pydantic compatibility layer, pytest, OpenAI-compatible chat completions through the existing `openai` package, existing retail tool registry/gateway/guard/eval modules.

---

## Source Spec

Primary spec:

`docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md`

Architecture discussion:

`docs/design-llm-agent-tool-calling.md`

## Long-Term Phases

This work should not be treated as one session. Each phase must leave the repository in a working, testable state.

| Phase | Name | Runtime impact | Exit condition |
|-------|------|----------------|----------------|
| 1 | Tool-calling contract, schema, harness | No runtime switch | Existing tests pass; provider/harness/schema tests pass |
| 2 | State split and context builder | Current runtime still works through compatibility | Trace and summary tests pass; existing eval still runs |
| 3 | LLM agent loop in isolation | New loop exists, not yet primary runtime | Scripted loop tests pass for read, write pending, guard block, failures |
| 4 | Runtime switch and old pipeline removal | `AgentRuntime` uses LLM runtime only | Scripted curated/generalized/synthetic smoke pass; no deterministic runtime mode |
| 5 | Eval adaptation and live benchmark | Eval supports scripted/live split | Reports include backend, token/tool metrics, failure categories |
| 6 | Deferred replay/debugging | Adds replay harness | Trace replay can reproduce a recorded turn |

Phase 1 is fully expanded below. Before starting Phase 2, create a new phase-specific plan from the same spec and the state of the code after Phase 1.

---

## File Structure

Phase 1 creates the stable contracts other phases will depend on.

```
app/agent/
  models.py              ← add ToolCallRequest, ToolCallResponse, ToolExecutionError
  providers.py           ← add chat_with_tools protocol method and provider/harness implementations

app/tools/
  registry.py            ← add tool_schemas_for_llm()

tests/
  test_tool_calling_provider.py  ← new provider/harness tests
  test_tool_schema.py            ← new registry JSON schema tests
```

Phase 2 and beyond will use these files:

```
app/agent/
  context_builder.py     ← new in Phase 2
  llm_agent.py           ← new in Phase 3
  runtime.py             ← switched in Phase 4
  guard.py               ← block_context in Phase 3 or 4

app/tools/
  gateway.py             ← structured tool errors in Phase 3 or 4

app/eval/
  cases.py               ← required_tools / forbidden_tools in Phase 5
  runner.py              ← eval_backend and live/scripted reporting in Phase 5
```

---

## Phase 1: Tool-Calling Contract, Schema, Harness

### Task 1: Add Tool-Calling Models

**Files:**
- Modify: `app/agent/models.py`
- Create: `tests/test_tool_calling_provider.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/test_tool_calling_provider.py`:

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

- [ ] **Step 2: Run model tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_tool_calling_provider.py -q
```

Expected: FAIL with import errors for `ToolCallRequest`, `ToolCallResponse`, and `ToolExecutionError`.

- [ ] **Step 3: Add models**

Modify `app/agent/models.py` by adding these models after `ToolCall`:

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

- [ ] **Step 4: Run model tests**

Run:

```bash
uv run python -m pytest tests/test_tool_calling_provider.py -q
```

Expected: PASS.

- [ ] **Step 5: Run focused lint**

Run:

```bash
uv run ruff check app/agent/models.py tests/test_tool_calling_provider.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add app/agent/models.py tests/test_tool_calling_provider.py
git commit -m "feat: add tool-calling response models"
```

Expected: commit succeeds.

### Task 2: Add Scripted and Failing Tool-Calling Providers

**Files:**
- Modify: `app/agent/providers.py`
- Modify: `tests/test_tool_calling_provider.py`

- [ ] **Step 1: Extend provider tests**

Append to `tests/test_tool_calling_provider.py`:

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

- [ ] **Step 2: Run provider tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_tool_calling_provider.py -q
```

Expected: FAIL with import errors for `ScriptedToolCallingProvider` and `FakeFailingProvider`.

- [ ] **Step 3: Update provider protocol and add harness providers**

Modify imports in `app/agent/providers.py`:

```python
from app.agent.models import ToolCallRequest, ToolCallResponse
```

Modify `LLMProvider`:

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

Add these classes near `DeterministicProvider`:

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

- [ ] **Step 4: Add deterministic provider tool-calling compatibility**

Modify `DeterministicProvider` in `app/agent/providers.py`:

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

- [ ] **Step 5: Run provider tests**

Run:

```bash
uv run python -m pytest tests/test_tool_calling_provider.py -q
```

Expected: PASS.

- [ ] **Step 6: Run focused lint**

Run:

```bash
uv run ruff check app/agent/providers.py tests/test_tool_calling_provider.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add app/agent/providers.py tests/test_tool_calling_provider.py
git commit -m "feat: add deterministic tool-calling harness providers"
```

Expected: commit succeeds.

### Task 3: Add DeepSeek Tool-Calling Adapter

**Files:**
- Modify: `app/agent/providers.py`
- Modify: `tests/test_tool_calling_provider.py`

- [ ] **Step 1: Add response normalization tests**

Append to `tests/test_tool_calling_provider.py`:

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

- [ ] **Step 2: Run normalization tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_tool_calling_provider.py -q
```

Expected: FAIL with import error for `normalize_tool_calling_message`.

- [ ] **Step 3: Add normalization helper**

Keep the existing typing imports in `app/agent/providers.py`:

```python
from typing import Any, Dict, List, Optional, Protocol
```

Add below `_extract_json_block`:

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

- [ ] **Step 4: Implement DeepSeekProvider.chat_with_tools**

Add this method to `DeepSeekProvider`:

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

- [ ] **Step 5: Run provider tests**

Run:

```bash
uv run python -m pytest tests/test_tool_calling_provider.py -q
```

Expected: PASS.

- [ ] **Step 6: Run focused lint**

Run:

```bash
uv run ruff check app/agent/providers.py tests/test_tool_calling_provider.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add app/agent/providers.py tests/test_tool_calling_provider.py
git commit -m "feat: add DeepSeek tool-calling adapter"
```

Expected: commit succeeds.

### Task 4: Generate Tool Schemas From Registry

**Files:**
- Modify: `app/tools/registry.py`
- Create: `tests/test_tool_schema.py`

- [ ] **Step 1: Write failing schema tests**

Create `tests/test_tool_schema.py`:

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

- [ ] **Step 2: Run schema tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_tool_schema.py -q
```

Expected: FAIL because `tool_schemas_for_llm` does not exist.

- [ ] **Step 3: Add schema generation helpers**

Modify `app/tools/registry.py` by adding imports:

```python
import inspect
```

Add these methods to `ToolRegistry`:

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

- [ ] **Step 4: Run schema tests**

Run:

```bash
uv run python -m pytest tests/test_tool_schema.py -q
```

Expected: PASS.

- [ ] **Step 5: Run focused lint**

Run:

```bash
uv run ruff check app/tools/registry.py tests/test_tool_schema.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add app/tools/registry.py tests/test_tool_schema.py
git commit -m "feat: generate LLM tool schemas from registry"
```

Expected: commit succeeds.

### Task 5: Phase 1 Regression Check

**Files:**
- No source file changes expected.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run python -m pytest tests/test_tool_calling_provider.py tests/test_tool_schema.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full tests**

Run:

```bash
uv run python -m pytest tests/ -q
```

Expected: PASS.

- [ ] **Step 3: Run lint**

Run:

```bash
uv run ruff check .
```

Expected: PASS.

- [ ] **Step 4: Record phase status**

Append this section to the top of `docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md` under the long-term phase table:

```markdown
## Phase Status

- Phase 1: complete after provider/harness/schema tests, full pytest, and ruff pass.
- Phase 2: ready to plan after Phase 1 completion.
```

- [ ] **Step 5: Commit status update**

Run:

```bash
git add docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md
git commit -m "docs: mark LLM tool-calling phase 1 complete"
```

Expected: commit succeeds.

---

## Phase 2 Planning Brief: State Split and Context Builder

Do not start Phase 2 until Phase 1 is complete. Generate a dedicated Phase 2 plan before touching code.

Phase 2 must cover:

- `ConversationState` compatibility strategy while introducing `SessionState` and `TurnContext`
- trace serialization updates
- `app/agent/context_builder.py`
- tests for auth summary, loaded order summary, pending action summary, write lock summary, and token budget behavior
- preservation of existing runtime behavior until Phase 4

Exit condition:

```bash
uv run python -m pytest tests/ -q
uv run ruff check .
```

Both commands pass, and existing eval commands still run with the current runtime.

## Phase 3 Planning Brief: LLM Agent Loop in Isolation

Do not start Phase 3 until Phase 2 is complete. Generate a dedicated Phase 3 plan before touching code.

Phase 3 must cover:

- `app/agent/llm_agent.py`
- `AgentTurnResult`
- `step_llm_reason`
- `step_tool_execute`
- `step_pending`
- `step_finalize`
- max iteration guard
- consecutive failure guard
- structured tool observations
- scripted tests for read, write pending, guard block, unknown tool, malformed args, provider timeout

Exit condition:

```bash
uv run python -m pytest tests/test_llm_agent.py -q
uv run python -m pytest tests/ -q
uv run ruff check .
```

All commands pass.

## Phase 4 Planning Brief: Runtime Switch and Old Runtime Removal

Do not start Phase 4 until Phase 3 is complete. Generate a dedicated Phase 4 plan before touching code.

Phase 4 must cover:

- switching `AgentRuntime.handle_user_message()` to pre-flight → LLM loop → post-processing
- removing `--mode deterministic`
- deleting `pipeline.py`, `plan_handlers.py`, and `graph.py`
- pruning parser/builder functions that only supported old intent/slot routing
- safe failure when provider is unavailable
- scripted smoke coverage for curated, generalized, synthetic, and pending confirmation flows

Exit condition:

```bash
uv run python -m pytest tests/ -q
uv run ruff check .
```

All commands pass, and no runtime code path imports the deleted pipeline modules.

## Phase 5 Planning Brief: Eval and Live Benchmark

Do not start Phase 5 until Phase 4 is complete. Generate a dedicated Phase 5 plan before touching code.

Phase 5 must cover:

- `required_tools`
- `forbidden_tools`
- `eval_backend`
- LLM token/tool/loop metrics
- scripted/live report split
- failure category reporting
- live LLM eval as manual or nightly, not regular CI

Exit condition:

```bash
uv run python -m pytest tests/test_eval_runner.py -q
uv run python -m pytest tests/ -q
uv run ruff check .
```

All commands pass, and live reports clearly label backend and failure category.

## Phase 6 Planning Brief: Trace Replay Harness

Do not start Phase 6 until Phase 5 is complete. Generate a dedicated Phase 6 plan before touching code.

Phase 6 must cover:

- trace artifact input format
- replaying rendered messages and tool observations
- reproduction of one recorded turn using a scripted provider
- replay test fixtures

Exit condition:

```bash
uv run python -m pytest tests/test_trace_replay_harness.py -q
uv run python -m pytest tests/ -q
uv run ruff check .
```

All commands pass.

---

## Self-Review

Spec coverage:

- Runtime single path is planned across Phases 1-4.
- Harness-first determinism is implemented in Phase 1.
- Tool schema generation is implemented in Phase 1.
- State split and context builder are isolated into Phase 2.
- LLM loop is isolated into Phase 3.
- Runtime switch and old pipeline deletion are isolated into Phase 4.
- Eval adaptation and live benchmark split are isolated into Phase 5.
- Trace replay remains deferred to Phase 6, matching the spec.

Ambiguity resolution:

- Phase 1 does not change runtime behavior.
- Later phases require fresh phase-specific plans before code edits.
- Live LLM eval is never part of regular CI.
- Old deterministic runtime is removed only in Phase 4, after the new loop has scripted coverage.
