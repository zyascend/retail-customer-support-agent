from __future__ import annotations

import re
from typing import Any

from app.agent.extraction import extract_order_id
from app.agent.models import ActionCandidate, SessionState

_HUMAN_RE = re.compile(r"\b(?:human|agent|representative|person)\b", re.IGNORECASE)
# 英文 intent patterns（原有）+ 中文等价 pattern（P2 多语言）。
# 中文意图泛化的主路径仍是主 LLM 的 tool-call；此处 HINT 正则仅在命中时
# 给主 LLM 一个 nudge（见 spec §5），miss 时主 LLM 自行决策。
_CANCEL_RE = re.compile(
    r"\bcancel\b.{0,40}\border\b|\border\b.{0,40}\bcancel\b"
    r"|取消.{0,40}订单|订单.{0,40}取消",
    re.IGNORECASE,
)
_RETURN_RE = re.compile(
    r"\breturn\b.{0,40}\b(?:item|items|order)\b"
    r"|退货|退还",
    re.IGNORECASE,
)
_EXCHANGE_RE = re.compile(
    r"\bexchange\b.{0,40}\b(?:item|items|order)\b"
    r"|换货",
    re.IGNORECASE,
)
_ORDER_ADDRESS_RE = re.compile(
    r"\b(?:change|modify|update)\b.{0,40}\border\b.{0,40}\baddress\b"
    r"|(?:修改|改|更改).{0,40}订单.{0,40}地址",
    re.IGNORECASE,
)
_USER_ADDRESS_RE = re.compile(
    r"\b(?:change|modify|update)\b.{0,40}\b(?:my|account|profile)\b.{0,40}\baddress\b"
    r"|(?:改|修改|更改).{0,20}(?:我的)?(?:默认)?地址",
    re.IGNORECASE,
)
_NEGATED_WRITE_RE = re.compile(
    r"\b(?:do not|don't|dont|not)\b.{0,20}\b(?:change|modify|update|cancel|return|exchange|replace|switch|remove|add)\b"
    r"|(?:不|别|不要)(?:要|改|退|换|取消|修改)",
    re.IGNORECASE,
)
_PAYMENT_RE = re.compile(
    r"\b(?:change|modify|update)\b.{0,40}\bpayment\b"
    r"|(?:修改|改|更改).{0,40}支付",
    re.IGNORECASE,
)
_SHIPPING_RE = re.compile(
    r"\b(?:change|modify|update)\b.{0,40}\b(?:shipping|delivery)\b"
    r"|(?:修改|改|更改).{0,40}(?:配送|运送|快递)",
    re.IGNORECASE,
)
_ITEM_CHANGE_RE = re.compile(
    r"\b(?:replace|switch|change|modify|update|remove|add)\b.{0,40}\b(?:item|items|product|products)\b"
    r"|(?:换|改|替换).{0,40}商品|商品.{0,40}(?:换成|改为|替换)",
    re.IGNORECASE,
)


def detect_action_candidate(
    session: SessionState,
    user_content: str,
) -> ActionCandidate | None:
    if _HUMAN_RE.search(user_content) and not _has_write_signal(user_content):
        return None
    if _NEGATED_WRITE_RE.search(user_content):
        return None

    tool_name = _detect_tool_name(user_content)
    if tool_name is None:
        return None

    order_id = extract_order_id(user_content)
    if order_id is None and _allows_loaded_order_fallback(tool_name, user_content):
        order_id = _best_loaded_order_id(session)

    if _requires_order_context(tool_name) and order_id is None:
        return None

    return ActionCandidate(
        tool_name=tool_name,
        confidence="high" if order_id else "medium",
        reason=_reason_for(tool_name),
        order_id=order_id,
        item_ids=_selected_item_ids(session, order_id, user_content),
        required_read_tools=_required_read_tools(tool_name, order_id),
    )


def _has_write_signal(text: str) -> bool:
    return any(
        pattern.search(text)
        for pattern in (
            _CANCEL_RE,
            _RETURN_RE,
            _EXCHANGE_RE,
            _ORDER_ADDRESS_RE,
            _USER_ADDRESS_RE,
            _PAYMENT_RE,
            _SHIPPING_RE,
            _ITEM_CHANGE_RE,
        )
    )


def _detect_tool_name(text: str) -> str | None:
    if _CANCEL_RE.search(text):
        return "cancel_pending_order"
    if _RETURN_RE.search(text):
        return "return_delivered_order_items"
    if _EXCHANGE_RE.search(text):
        return "exchange_delivered_order_items"
    if _PAYMENT_RE.search(text):
        return "modify_pending_order_payment"
    if _SHIPPING_RE.search(text):
        return "modify_pending_order_shipping_method"
    if _ORDER_ADDRESS_RE.search(text):
        return "modify_pending_order_address"
    if _USER_ADDRESS_RE.search(text):
        return "modify_user_address"
    if _ITEM_CHANGE_RE.search(text):
        return "modify_pending_order_items"
    return None


def _allows_loaded_order_fallback(tool_name: str, text: str) -> bool:
    if tool_name == "modify_user_address":
        return False
    return bool(
        re.search(r"\b(?:this|that|the|my)\s+order\b", text, re.IGNORECASE)
        or re.search(r"\b(?:cheaper|cheapest|expensive|priciest|costliest)\b", text, re.IGNORECASE)
    )


def _requires_order_context(tool_name: str) -> bool:
    return tool_name != "modify_user_address"


def _best_loaded_order_id(session: SessionState) -> str | None:
    if not session.loaded_context.orders:
        return None
    return next(reversed(session.loaded_context.orders.keys()))


def _selected_item_ids(
    session: SessionState,
    order_id: str | None,
    text: str,
) -> list[str]:
    if not order_id:
        return []
    order = session.loaded_context.orders.get(order_id) or {}
    items = order.get("items") or []
    if not isinstance(items, list):
        return []
    normalized = [_item_summary(item) for item in items]
    normalized = [item for item in normalized if item.get("item_id")]
    if not normalized:
        return []
    if re.search(r"\b(?:cheaper|cheapest|least expensive)\b", text, re.IGNORECASE):
        return [min(normalized, key=lambda item: item.get("price", 0))["item_id"]]
    if re.search(r"\b(?:expensive|priciest|costliest)\b", text, re.IGNORECASE):
        return [max(normalized, key=lambda item: item.get("price", 0))["item_id"]]
    if len(normalized) == 1:
        return [normalized[0]["item_id"]]
    return []


def _item_summary(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    item_id = item.get("item_id") or item.get("id")
    price = item.get("price") or item.get("unit_price") or 0
    return {"item_id": str(item_id) if item_id else "", "price": float(price or 0)}


def _required_read_tools(tool_name: str, order_id: str | None) -> list[str]:
    if tool_name == "modify_user_address":
        return ["get_user_details"]
    if order_id:
        return ["get_order_details"]
    return []


def _reason_for(tool_name: str) -> str:
    return {
        "cancel_pending_order": "User asked to cancel an order.",
        "return_delivered_order_items": "User asked to return delivered order items.",
        "exchange_delivered_order_items": "User asked to exchange delivered order items.",
        "modify_pending_order_address": "User asked to change an order address.",
        "modify_pending_order_items": "User asked to change order items.",
        "modify_pending_order_payment": "User asked to change payment.",
        "modify_pending_order_shipping_method": "User asked to change shipping.",
        "modify_user_address": "User asked to change account address.",
    }.get(tool_name, "User request matches a write action.")
