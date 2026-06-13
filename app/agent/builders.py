from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from app.agent.action_specs import WRITE_ACTION_BY_NAME


def pending_action_has_required_args(
    action_name: str, arguments: Dict[str, Any]
) -> bool:
    spec = WRITE_ACTION_BY_NAME.get(action_name)
    if spec is None:
        return False
    return all(arguments.get(key) for key in spec.required_args)


def normalize_llm_action_arguments(
    action_name: str,
    arguments: Dict[str, Any],
    clean_llm_scalar_fn: Callable[[Any], Optional[str]],
) -> Dict[str, Any]:
    normalized = dict(arguments)
    if action_name == "modify_pending_order_address":
        address = normalized.pop("address", None)
        if isinstance(address, dict):
            for key in ("address1", "address2", "city", "state", "country", "zip"):
                if key not in normalized and address.get(key) is not None:
                    normalized[key] = address.get(key)
    for key in ("item_ids", "new_item_ids"):
        value = normalized.get(key)
        if isinstance(value, str):
            normalized[key] = [value]
    for key, value in list(normalized.items()):
        if isinstance(value, str):
            cleaned = clean_llm_scalar_fn(value)
            if cleaned is None:
                normalized.pop(key)
            else:
                normalized[key] = cleaned
    return normalized


def pending_prompt(action_name: str, arguments: Dict[str, Any]) -> str:
    order_id = arguments.get("order_id")
    if action_name == "cancel_pending_order":
        return (
            f"Cancel order {order_id} because {arguments.get('reason')}. "
            "Please confirm yes or no."
        )
    if action_name == "modify_pending_order_address":
        return (
            f"Modify the shipping address for order {order_id}. "
            "Please confirm yes or no."
        )
    if action_name == "modify_pending_order_items":
        return f"Replace items in order {order_id}. Please confirm yes or no."
    if action_name == "modify_pending_order_payment":
        return f"Change payment for order {order_id}. Please confirm yes or no."
    if action_name == "modify_user_address":
        return "Modify your default address. Please confirm yes or no."
    if action_name == "return_delivered_order_items":
        return f"Request a return for order {order_id}. Please confirm yes or no."
    return f"Request an exchange for order {order_id}. Please confirm yes or no."


def merge_slots(
    *,
    code_slots: Dict[str, Any],
    llm_slots: Optional[Dict[str, Any]],
    clean_llm_scalar_fn: Callable[[Any], Optional[str]],
) -> Dict[str, Any]:
    """Merge code and LLM slots. Code wins for ID formats; LLM for semantic."""
    if not llm_slots:
        return dict(code_slots)
    merged = dict(code_slots)
    for key, value in llm_slots.items():
        if key not in merged or not merged[key]:
            if value:
                merged[key] = value
            continue
        if key == "reason":
            cleaned = clean_llm_scalar_fn(value)
            if cleaned and cleaned.lower() in {
                "no longer needed",
                "ordered by mistake",
            }:
                merged[key] = cleaned.lower()
        if key == "address" and isinstance(value, dict):
            cleaned_address = {
                k: clean_llm_scalar_fn(value.get(k)) or ""
                for k in ("address1", "address2", "city", "state", "country", "zip")
            }
            if cleaned_address.get("address1") and cleaned_address.get("zip"):
                merged["address"] = cleaned_address
    return merged
