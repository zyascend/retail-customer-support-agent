from __future__ import annotations

import re
from typing import Any, Dict, Optional

from app.agent.action_specs import WRITE_ACTION_BY_INTENT
from app.agent.models import ConversationState

# ── Module-level regex constants ──

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
NAME_ZIP_RE = re.compile(
    r"(?:my name is|i am|i'm)\s+([A-Za-z]+)\s+([A-Za-z]+).*?\bzip(?: code)? is\s+(\d{5}(?:-\d{4})?)",
    re.IGNORECASE,
)
ORDER_RE = re.compile(r"#W\d+")
ITEM_RE = re.compile(r"\b\d{8,}\b")
PAYMENT_RE = re.compile(r"\b(?:gift_card|credit_card|paypal)_\d+\b")
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


def infer_intent(lowered: str) -> str:
    # Policy questions are lookups, not operations
    if re.search(r"\b(return|exchange|cancel|refund)\s+policy\b", lowered):
        return "lookup"

    # Coupon / discount / compensation → transfer (unsupported, no write)
    if re.search(r"\b(coupon|discount|compensation)\b", lowered):
        return "transfer"
    if re.search(r"\brefund\b", lowered) and not re.search(r"\breturn\b", lowered):
        return "transfer"

    # Explicit human transfer request — multiple patterns
    # Pattern 1: verb + human/agent/representative
    if re.search(
        r"\b(?:talk|speak|connect|transfer|want|need|get|like|"
        r"speak)\s+(?:to|with|a|an)?\s*"
        r"(?:human|agent|representative|person)\b",
        lowered,
    ):
        return "transfer"
    # Pattern 2: standalone unambiguous transfer signals
    if re.search(
        r"\b(?:customer\s+service|support\s+agent|real\s+person"
        r"|human\s+agent|human\s+representative)\b",
        lowered,
    ):
        return "transfer"
    # Pattern 3: unsupported request types
    if "discount" in lowered:
        return "transfer"

    # Cancel — must mention order
    if re.search(r"\bcancel\b", lowered):
        if re.search(r"\border\b", lowered) or ORDER_RE.search(lowered):
            return "cancel_order"
        return "cancel_order"

    # Exchange — exclude "exchange rate" and "exchange policy"
    if re.search(r"\bexchange\b", lowered):
        if not re.search(r"\bexchange\s+(?:rate|policy)\b", lowered):
            if re.search(r"\bitems?\b", lowered) or ITEM_RE.search(lowered):
                return "exchange_items"
            return "exchange_items"

    # Return — must mention item or order, not "return policy"
    if re.search(r"\breturn\b", lowered):
        if re.search(r"\breturn\s+policy\b", lowered):
            pass
        elif re.search(r"\bitems?\b", lowered) or ORDER_RE.search(lowered):
            return "return_items"

    # Shipping method modification
    if "shipping" in lowered and re.search(
        r"\b(change|modify|update|upgrade|switch)\b", lowered
    ):
        return "modify_shipping_method"
    if re.search(r"\b(upgrade|expedite)\b.*\bshipping\b", lowered):
        return "modify_shipping_method"
    if re.search(r"\b(overnight|express|standard)\b", lowered) and (
        "shipping" in lowered or "delivery" in lowered
    ):
        return "modify_shipping_method"

    # Payment modification
    if "payment" in lowered and re.search(
        r"\b(change|modify|update|switch)\b", lowered
    ):
        return "modify_order_payment"

    # Item modification (pending order)
    if re.search(r"\b(items?|products?)\b", lowered) and re.search(
        r"\b(change|modify|replace|switch|swap)\b", lowered
    ):
        return "modify_order_items"

    # User default address
    if re.search(r"\bmy\b.*\bdefault\b.*\baddress\b", lowered):
        return "modify_user_address"
    if "default address" in lowered:
        return "modify_user_address"

    # Order address modification
    if "address" in lowered and re.search(r"\b(change|modify|update)\b", lowered):
        if "my" in lowered and "default" in lowered:
            return "modify_user_address"
        return "modify_order_address"

    # Order mention → lookup
    if "order" in lowered or ORDER_RE.search(lowered):
        return "lookup"

    return "unknown"


def parse_address(content: str) -> Optional[Dict[str, str]]:
    marker = re.search(r"(?:default )?address to\s+(.+)$", content, re.IGNORECASE)
    if not marker:
        return None
    parts = [part.strip().rstrip(".") for part in marker.group(1).split(",")]
    if len(parts) == 5:
        address1, city, state, country, zip_code = parts
        address2 = ""
    elif len(parts) >= 6:
        address1, address2, city, state, country, zip_code = parts[:6]
    else:
        return None
    return {
        "address1": address1,
        "address2": address2,
        "city": city,
        "state": state,
        "country": country,
        "zip": zip_code,
    }


def parse_item_replacement_pairs(lowered: str) -> list[tuple[str, str]]:
    pairs = re.findall(r"\b(\d{8,})\s+(?:to|for|instead)\s+(\d{8,})\b", lowered)
    if pairs:
        return pairs
    return re.findall(
        r"\bitem\s+(\d{8,}).*?\b(?:new item|instead)\s+(\d{8,})\b",
        lowered,
    )


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


def merge_policy_decisions(
    *,
    code_decision: str,
    llm_decision: Optional[str],
) -> str:
    """Conservative dual-track merge.
    Any deny → deny. Any ask → ask. Transfer needs both to agree.
    Only allow when both allow.
    """
    if llm_decision is None:
        return code_decision
    # Code-level transfer (unsupported requests) overrides LLM deny
    if code_decision == "transfer" and llm_decision == "deny":
        return "transfer"
    if "deny" in (code_decision, llm_decision):
        return "deny"
    if "ask_clarification" in (code_decision, llm_decision):
        return "ask_clarification"
    if code_decision == "transfer" and llm_decision == "transfer":
        return "transfer"
    if code_decision == "transfer" or llm_decision == "transfer":
        return "ask_clarification"
    return "allow"


def has_assistant_response(state: ConversationState) -> bool:
    return bool(state.messages and state.messages[-1].role == "assistant")


def last_assistant_message(state: ConversationState) -> str:
    for message in reversed(state.messages):
        if message.role == "assistant":
            return message.content
    return ""


def code_missing_slots(state: ConversationState) -> list[str]:
    """Code-side check for missing required slots per intent."""
    spec = WRITE_ACTION_BY_INTENT.get(state.current_intent)
    if spec is None:
        return []
    required = spec.required_slots
    return [key for key in required if not state.slots.get(key)]


SHIPPING_ALIASES = {
    "standard": "standard",
    "regular": "standard",
    "normal": "standard",
    "free": "standard",
    "express": "express",
    "expedited": "express",
    "overnight": "overnight",
    "next day": "overnight",
    "next-day": "overnight",
}


def parse_shipping_method(content: str) -> Optional[str]:
    """Extract canonical shipping method from user text."""
    lowered = content.lower()
    for alias, canonical in SHIPPING_ALIASES.items():
        pattern = alias.replace(" ", r"\s+")
        if re.search(rf"\b{pattern}\b", lowered):
            return canonical
    return None
