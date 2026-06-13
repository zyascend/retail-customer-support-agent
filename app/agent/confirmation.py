from __future__ import annotations

import re
from typing import Literal

ConfirmationIntent = Literal["confirm", "deny", "changed", "unknown"]

# ── Weighted keyword dictionaries ──

_CONFIRM_KEYWORDS: dict[str, int] = {
    # Strong confirm (weight 3)
    "yes": 3, "confirm": 3, "proceed": 3, "go ahead": 3,
    "确认": 3, "可以": 3, "行": 3,
    "是的": 3, "同意": 3,
    "好的": 3, "没问题": 3, "继续": 3,
    # Medium confirm (weight 2)
    "好": 2,
    # Weak confirm (weight 1)
    "ok": 1, "okay": 1, "sure": 1, "yeah": 1, "yep": 1, "yup": 1,
    "是": 1, "嗯": 1, "对": 1,
}

_DENY_KEYWORDS: dict[str, int] = {
    "no": 3, "nope": 3, "cancel": 3, "deny": 3, "reject": 3, "stop": 3,
    "不": 3, "取消": 3, "拒绝": 3,
    "don't": 2, "not": 2, "never": 2, "never mind": 2,
    "不用": 2, "算了": 2,
    "先不要": 2, "别改了": 2,
}

_CHANGE_KEYWORDS: dict[str, int] = {
    "change": 3, "instead": 3, "different": 3, "replace": 3, "switch": 3,
    "改": 3, "换": 3, "换成": 3, "替代": 3,
    "modify": 2, "update": 2, "adjust": 2,
}

# ── Negation prefixes ──

_NEGATION_RE = re.compile(
    r"\b(?:don'?t|do not|not|never|won'?t|cannot|can'?t)\b",
    re.IGNORECASE,
)
_CN_NEGATION_RE = re.compile(
    r"(?:不|不要|别|不想|别要)",
)

_CHANGE_PATTERN = re.compile(
    r"(?:\b(?:change|instead|different|replace|switch|modify|update|adjust)\b"
    r"|改|换|换成|替代)",
    re.IGNORECASE,
)


def _score(text_lower: str, keywords: dict[str, int]) -> int:
    """Sum weights of keywords found in text.
    Uses word-boundary matching for English, substring for Chinese.
    Multi-word keys checked first; after a longer match, skip shorter substrings.
    """
    total = 0
    matched_spans: list[tuple[int, int]] = []

    # Sort by length descending so longer phrases match first
    for phrase, weight in sorted(keywords.items(), key=lambda x: -len(x[0])):
        # For English-only phrases, use word boundary matching
        if phrase.isascii() and phrase.isalpha():
            pattern = re.compile(r'\b' + re.escape(phrase) + r'\b', re.IGNORECASE)
            if pattern.search(text_lower):
                total += weight
        else:
            # For Chinese/mixed, find all occurrences
            idx = text_lower.find(phrase)
            if idx >= 0:
                # Check this match doesn't overlap with a previously-matched longer phrase
                span = (idx, idx + len(phrase))
                if not any(s[0] <= span[0] < s[1] or s[0] < span[1] <= s[1]
                          for s in matched_spans):
                    total += weight
                    matched_spans.append(span)
    return total


def _has_negated_change(text_lower: str) -> bool:
    """Detect patterns like 'don't change', '不想改'."""
    if _NEGATION_RE.search(text_lower) and _CHANGE_PATTERN.search(text_lower):
        return True
    if _CN_NEGATION_RE.search(text_lower) and _CHANGE_PATTERN.search(text_lower):
        return True
    return False


class ConfirmationResolver:
    def resolve(self, text: str) -> ConfirmationIntent:
        text_lower = text.lower().strip()

        # 1. Negated change gets highest priority: "don't change" → denied
        if _has_negated_change(text_lower):
            return "deny"

        # 2. Compute confidence scores
        confirm = _score(text_lower, _CONFIRM_KEYWORDS)
        deny = _score(text_lower, _DENY_KEYWORDS)
        change = _score(text_lower, _CHANGE_KEYWORDS)

        # 3. Clear deny signal
        if deny > confirm + change and deny >= 2:
            return "deny"

        # 4. User wants to change the request (even if "no" appears)
        if change > confirm and change >= 2:
            return "changed"

        # 5. Clear confirm signal
        if confirm > deny and confirm >= 2:
            return "confirm"

        # 6. Ambiguous — require clarification
        return "unknown"
