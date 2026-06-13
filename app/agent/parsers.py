from __future__ import annotations

import re
from typing import Any, Optional

# ── Module-level regex constants ──

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
NAME_ZIP_RE = re.compile(
    r"(?:my name is|i am|i'm)\s+([A-Za-z]+)\s+([A-Za-z]+).*?\bzip(?:[ -]?code)? is\s+(\d{5}(?:-\d{4})?)",
    re.IGNORECASE,
)
SUPPORTED_INTENTS = {
    "lookup",
    "cancel_order",
    "modify_order_address",
    "modify_order_items",
    "modify_order_payment",
    "modify_shipping_method",
    "modify_user_address",
    "return_items",
    "exchange_items",
    "transfer",
    "unknown",
}


# ── Pure parser / utility functions ──


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
