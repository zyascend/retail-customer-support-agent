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
    """Sentinel used by tests and offline eval to force deterministic fallback."""


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
