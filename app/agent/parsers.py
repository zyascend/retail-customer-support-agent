from __future__ import annotations

from typing import Any, Optional

# ── 纯 parser / utility functions ──
# EMAIL_RE / NAME_ZIP_RE 已迁至 app.agent.extraction（Layer 0 格式提取）。


def clean_llm_scalar(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a"}:
        return None
    return text


def clean_llm_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        text = clean_llm_scalar(item)
        if text:
            cleaned.append(text)
    return cleaned
