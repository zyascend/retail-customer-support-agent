from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

try:
    from openai import OpenAI
except ModuleNotFoundError:
    OpenAI = None


class LLMProvider(Protocol):
    def json(
        self, messages: List[Dict[str, str]], schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        ...

    def chat(self, messages: List[Dict[str, str]]) -> str:
        ...


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
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)

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
