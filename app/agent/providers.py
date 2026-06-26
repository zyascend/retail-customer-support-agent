from __future__ import annotations

import ast
import json
import random
import re as _re
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Protocol

from app.agent.models import ToolCallRequest, ToolCallResponse

try:
    from openai import APITimeoutError, OpenAI, RateLimitError
except ModuleNotFoundError:
    APITimeoutError = None
    OpenAI = None
    RateLimitError = None


_TRANSIENT_NETWORK_ERROR_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
}


def _extract_json_block(text: str) -> str:
    """Extract JSON from LLM output, tolerating markdown fences."""
    match = _re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, _re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _strip_trailing_commas(text: str) -> str:
    return _re.sub(r",\s*([}\]])", r"\1", text)


def _normalize_python_literals(text: str) -> str:
    text = _re.sub(r"\bTrue\b", "true", text)
    text = _re.sub(r"\bFalse\b", "false", text)
    text = _re.sub(r"\bNone\b", "null", text)
    return text


def _looks_like_python_literal_container(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[0] not in "[{" or stripped[-1] not in "]}":
        return False
    return '"' not in stripped and "'" in stripped


def _parse_json_maybe_repaired(raw_text: str) -> Any:
    text = _extract_json_block(raw_text)
    if not text:
        raise json.JSONDecodeError("Empty JSON payload", raw_text, 0)

    candidates = [text]

    normalized = _normalize_python_literals(text)
    if normalized != text:
        candidates.append(normalized)

    for candidate in list(candidates):
        trimmed = _strip_trailing_commas(candidate)
        if trimmed != candidate:
            candidates.append(trimmed)

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    literal_candidate = _strip_trailing_commas(text)
    if _looks_like_python_literal_container(literal_candidate):
        try:
            return ast.literal_eval(literal_candidate)
        except (ValueError, SyntaxError):
            pass

    raise json.JSONDecodeError("Unable to parse JSON payload", raw_text, 0)


def _coerce_retry_after_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return max(0.0, float(stripped))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(stripped)
            except (TypeError, ValueError, IndexError):
                return None
            delta = retry_at.timestamp() - time.time()
            return max(0.0, delta)
    return None


def _retry_after_from_exception(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).lower() == "retry-after":
                return _coerce_retry_after_seconds(value)
        return None
    for key in ("retry-after", "Retry-After"):
        try:
            value = headers.get(key)
        except AttributeError:
            value = None
        seconds = _coerce_retry_after_seconds(value)
        if seconds is not None:
            return seconds
    return None


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
                parsed = _parse_json_maybe_repaired(raw_arguments)
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


def _extract_token_usage(
    response: Any, raw_text: str | None = None
) -> dict[str, int] | None:
    token_usage: dict[str, int] = {}

    if raw_text:
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed = None
        raw_usage = parsed.get("usage") if isinstance(parsed, dict) else None
        if isinstance(raw_usage, dict):
            for key, value in raw_usage.items():
                if isinstance(value, int):
                    token_usage[key] = value

    usage = getattr(response, "usage", None)
    if usage is not None:
        for key, value in vars(usage).items():
            if isinstance(value, int) and key not in token_usage:
                token_usage[key] = value

    return token_usage or None


class LLMProvider(Protocol):
    def json(
        self,
        messages: List[Dict[str, str]],
        schema: Dict[str, Any],
        *,
        timeout: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]: ...

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        timeout: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str: ...

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

    def _is_rate_limit_error(self, exc: Exception) -> bool:
        return RateLimitError is not None and isinstance(exc, RateLimitError)

    def _is_timeout_error(self, exc: Exception) -> bool:
        return APITimeoutError is not None and isinstance(exc, APITimeoutError)

    def _is_transient_provider_error(self, exc: Exception) -> bool:
        return exc.__class__.__name__ in _TRANSIENT_NETWORK_ERROR_NAMES

    def _compute_backoff_seconds(self, attempt: int) -> float:
        base_delay = 0.5
        cap = 8.0
        jitter = random.uniform(0.0, 0.25)
        return min(cap, base_delay * (2 ** attempt)) + jitter

    def _sleep_for_retry(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))

    def _with_transient_retries(self, operation: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return operation()
            except Exception as exc:
                last_error = exc
                is_retryable = (
                    self._is_rate_limit_error(exc)
                    or self._is_timeout_error(exc)
                    or self._is_transient_provider_error(exc)
                )
                if not is_retryable or attempt >= self.max_retries:
                    raise
                retry_after = _retry_after_from_exception(exc)
                delay = (
                    retry_after
                    if retry_after is not None and self._is_rate_limit_error(exc)
                    else self._compute_backoff_seconds(attempt)
                )
                self._sleep_for_retry(delay)
        if last_error is not None:
            raise last_error
        raise RuntimeError("retry wrapper exited unexpectedly")

    def json(
        self,
        messages: List[Dict[str, str]],
        schema: Dict[str, Any],
        *,
        timeout: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._with_transient_retries(
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        response_format={"type": "json_object"},
                        timeout=timeout,
                        max_tokens=max_tokens,
                    )
                )
                content = response.choices[0].message.content or "{}"
                parsed = _parse_json_maybe_repaired(content)
                if isinstance(parsed, dict):
                    return parsed
                raise json.JSONDecodeError("JSON response was not an object", content, 0)
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    raise
        raise last_error  # type: ignore[misc]

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        timeout: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        response = self._with_transient_retries(
            lambda: self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        )
        return response.choices[0].message.content or ""

    def chat_with_tools(
        self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
    ) -> ToolCallResponse:
        raw_response = self._with_transient_retries(
            lambda: self.client.chat.completions.with_raw_response.create(
                model=self.model,
                messages=messages,
                tools=tools,
            )
        )
        response = raw_response.parse()
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
        reasoning_content = getattr(message, "reasoning_content", None) or None
        token_usage = _extract_token_usage(response, getattr(raw_response, "text", None))
        return normalize_tool_calling_message(
            message=message_dict,
            finish_reason=getattr(choice, "finish_reason", None),
            token_usage=token_usage,
            reasoning_content=reasoning_content,
            raw=None,
        )


def build_default_provider(
    *,
    api_key: str,
    base_url: str,
    model: str,
    timeout: float = 30.0,
    max_retries: int = 2,
    require_llm: bool = False,
    provider_type: str = "deepseek",
    ollama_model: str = "",
) -> Optional[LLMProvider]:
    return _build_provider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
        max_retries=max_retries,
        require_llm=require_llm,
        provider_type=provider_type,
        ollama_model=ollama_model,
    )


def _build_provider(
    *,
    api_key: str,
    base_url: str,
    model: str,
    timeout: float = 30.0,
    max_retries: int = 2,
    require_llm: bool = False,
    provider_type: str = "deepseek",
    ollama_model: str = "",
) -> Optional[LLMProvider]:
    if provider_type == "ollama":
        actual_model = ollama_model or model
        return DeepSeekProvider(
            api_key="ollama",
            base_url="http://localhost:11434/v1",
            model=actual_model,
            timeout=timeout,
            max_retries=max_retries,
        )
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
