from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class LanguageVariant:
    level: str
    suffix: str
    messages: List[Dict[str, str]]
    gate: bool


def language_variant_levels_for_gate() -> tuple[str, ...]:
    return ("base", "L1", "L2")


def build_language_variants(
    base_messages: List[Dict[str, str]],
    variant_type: str,
    entities: dict,
) -> List[LanguageVariant]:
    """Build deterministic language variants for a generated scenario."""
    base = _copy_messages(base_messages)
    return [
        LanguageVariant("base", "", base, True),
        LanguageVariant("L1", "_l1", _l1_messages(base, variant_type), True),
        LanguageVariant("L2", "_l2", _l2_messages(base, variant_type, entities), True),
        LanguageVariant("L3", "_l3", _l3_messages(base, variant_type, entities), False),
    ]


def _copy_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [dict(message) for message in messages]


def _l1_messages(
    base_messages: List[Dict[str, str]], variant_type: str
) -> List[Dict[str, str]]:
    messages = _copy_messages(base_messages)
    if not messages:
        return messages

    content = messages[0].get("content", "")
    replacements = _l1_replacements_for(variant_type)
    for source, target in replacements:
        content = content.replace(source, target)
    messages[0]["content"] = content
    return messages


def _l1_replacements_for(variant_type: str) -> tuple[tuple[str, str], ...]:
    if variant_type.startswith("cancel_"):
        return (
            ("Cancel order", "Void order"),
            ("Cancel", "Void"),
            ("cancel", "void"),
        )
    if variant_type.startswith("shipping_"):
        return (
            ("Change shipping", "Update delivery"),
            ("upgrade the shipping", "switch the delivery"),
            ("Change", "Update"),
            ("shipping", "delivery"),
        )
    if variant_type == "coupon_transfer_no_write":
        return (
            ("discount coupon", "courtesy credit"),
            ("discount", "price adjustment"),
            ("coupon", "credit"),
        )
    return ()


def _l2_messages(
    base_messages: List[Dict[str, str]], variant_type: str, entities: dict
) -> List[Dict[str, str]]:
    messages = _copy_messages(base_messages)
    if not messages:
        return messages

    user = entities["user"]
    order = entities.get("order")
    email = user["email"]
    order_id = order["order_id"] if order else None

    if variant_type.startswith("cancel_") and order_id:
        messages[0]["content"] = (
            f"For order {order_id}, I need it cancelled because no longer needed. "
            f"You can identify me with {email}."
        )
    elif variant_type == "shipping_success_express" and order_id:
        messages[0]["content"] = (
            f"Order {order_id} should use express shipping. My email is {email}."
        )
    elif variant_type == "shipping_success_overnight" and order_id:
        messages[0]["content"] = (
            f"Use my credit card and set order {order_id} to overnight shipping. "
            f"My email is {email}."
        )
    elif variant_type == "shipping_block_same_method" and order_id:
        current_method = order.get("shipping_method", "standard")
        messages[0]["content"] = (
            f"Order {order_id} already uses {current_method}; please set it to "
            f"{current_method}. My email is {email}."
        )
    elif variant_type == "shipping_block_nonpending" and order_id:
        messages[0]["content"] = (
            f"Please set order {order_id} to express shipping. My email is {email}."
        )
    elif variant_type == "shipping_block_unknown_method" and order_id:
        messages[0]["content"] = (
            f"Order {order_id} needs drone delivery. My email is {email}."
        )
    elif variant_type == "coupon_transfer_no_write":
        messages[0]["content"] = (
            f"Because my email is {email}, can you add a courtesy credit for me?"
        )
    return messages


def _l3_messages(
    base_messages: List[Dict[str, str]], variant_type: str, entities: dict
) -> List[Dict[str, str]]:
    messages = _copy_messages(base_messages)
    if not messages:
        return messages

    user = entities["user"]
    order = entities.get("order")
    email = user["email"]
    order_id = order["order_id"] if order else None
    confirmation = [dict(message) for message in messages[1:]]

    if variant_type.startswith("cancel_") and order_id:
        return [
            {"role": "user", "content": f"My email is {email}. I need to cancel an order."},
            {"role": "user", "content": f"The order is {order_id}."},
            *confirmation,
        ]
    if variant_type.startswith("shipping_") and order_id:
        target = _shipping_target_for(variant_type, order)
        return [
            {"role": "user", "content": f"My email is {email}. I need to change shipping."},
            {"role": "user", "content": f"Use {target} for order {order_id}."},
            *confirmation,
        ]
    if variant_type == "coupon_transfer_no_write":
        return [
            {"role": "user", "content": "Can you give me a discount?"},
            {"role": "user", "content": f"My email is {email}."},
        ]
    return messages


def _shipping_target_for(variant_type: str, order: dict | None) -> str:
    if variant_type == "shipping_success_express":
        return "express shipping"
    if variant_type == "shipping_success_overnight":
        return "overnight shipping"
    if variant_type == "shipping_block_same_method" and order:
        return str(order.get("shipping_method", "standard"))
    if variant_type == "shipping_block_unknown_method":
        return "drone delivery"
    return "express shipping"
