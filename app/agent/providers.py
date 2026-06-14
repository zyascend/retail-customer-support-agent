from __future__ import annotations

import json
import re as _re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from app.agent.models import ToolCallRequest, ToolCallResponse

try:
    from openai import OpenAI
except ModuleNotFoundError:
    OpenAI = None


def _extract_json_block(text: str) -> str:
    """Extract JSON from LLM output, tolerating markdown fences."""
    match = _re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, _re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def normalize_tool_calling_message(
    *,
    message: Dict[str, Any],
    finish_reason: Optional[str],
    token_usage: Optional[Dict[str, Any]],
    reasoning_content: Optional[str] = None,
    raw: Optional[Dict[str, Any]] = None,
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
        reasoning_content=reasoning_content,
        raw=raw,
    )


class LLMProvider(Protocol):
    def json(
        self, messages: List[Dict[str, str]], schema: Dict[str, Any]
    ) -> Dict[str, Any]: ...

    def chat(self, messages: List[Dict[str, str]]) -> str: ...

    def chat_with_tools(
        self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> ToolCallResponse: ...


@dataclass
class DeepSeekProvider:
    api_key: str
    base_url: str
    model: str
    timeout: float = 30.0
    max_retries: int = 2

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is required for DeepSeekProvider")
        if OpenAI is None:
            raise ValueError("openai package is required for DeepSeekProvider")
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

    def json(
        self, messages: List[Dict[str, str]], schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content or "{}"
                content = _extract_json_block(content)
                return json.loads(content)
            except (json.JSONDecodeError, KeyError) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    raise
        raise last_error  # type: ignore[misc]

    def chat(self, messages: List[Dict[str, str]]) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        return response.choices[0].message.content or ""

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
        # DeepSeek reasoning_content must be passed back to the API
        reasoning_content = getattr(message, "reasoning_content", None) or None
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
            reasoning_content=reasoning_content,
            raw=None,
        )


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


class DisabledLLMProvider:
    """Sentinel used by offline demo harnesses to disable live LLM calls."""

    def chat_with_tools(
        self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> ToolCallResponse:
        return ToolCallResponse(
            assistant_content=(
                "I'm sorry, the agent is running in offline mode. "
                "Please configure an LLM provider to handle your request."
            ),
            finish_reason="stop",
        )


def build_default_provider(
    *,
    api_key: str,
    base_url: str,
    model: str,
    timeout: float = 30.0,
    max_retries: int = 2,
    require_llm: bool = False,
) -> Optional[LLMProvider]:
    if not api_key:
        if require_llm:
            raise ValueError("DEEPSEEK_API_KEY is required when LLM is required")
        return None
    return DeepSeekProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
        max_retries=max_retries,
    )
