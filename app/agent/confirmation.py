from __future__ import annotations

import re
from typing import Literal

ConfirmationIntent = Literal["confirm", "deny", "changed", "unknown"]

CONFIRM_TERMS = {
    "yes",
    "yep",
    "yeah",
    "confirm",
    "go ahead",
    "proceed",
    "ok",
    "okay",
    "sure",
    "确认",
    "可以",
    "是的",
    "好的",
    "行",
    "没问题",
    "继续",
}
DENY_TERMS = {
    "no",
    "nope",
    "cancel",
    "stop",
    "never mind",
    "不",
    "不用",
    "取消",
    "算了",
    "先不要",
    "别改了",
}
CHANGE_PATTERNS = (
    r"#W\d+",
    r"\b\d{8,}\b",
    r"\b\d{5}(?:-\d{4})?\b",
    r"\b(address|item|payment|reason|instead|different|change)\b",
    r"(地址|商品|支付|原因|换成|改成)",
)


class ConfirmationResolver:
    def resolve(self, text: str) -> ConfirmationIntent:
        normalized = " ".join(text.lower().strip().split())
        if normalized in CONFIRM_TERMS:
            return "confirm"
        if normalized in DENY_TERMS:
            return "deny"
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in CHANGE_PATTERNS):
            return "changed"
        return "unknown"

