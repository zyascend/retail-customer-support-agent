from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from app.agent.action_specs import WRITE_ACTION_NAMES
from app.agent.models import ConversationState
from app.agent.parsers import SUPPORTED_INTENTS, clean_llm_list, clean_llm_scalar
from app.agent.prompts import (
    ACTION_PLANNER_SYSTEM,
    POLICY_SYSTEM,
    RESPONSE_SYSTEM,
    user_json_prompt,
)


def llm_json(
    state: ConversationState,
    node_name: str,
    system_prompt: str,
    payload: Dict[str, Any],
    schema: Dict[str, Any],
    provider: Optional[Any],
) -> Dict[str, Any]:
    if provider is None:
        return {}
    t0 = time.perf_counter()
    status = "ok"
    try:
        result = provider.json(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_json_prompt(node_name, payload),
                },
            ],
            schema,
        )
    except Exception as exc:
        status = "error"
        state.add_step(
            f"{node_name}_llm",
            status="error",
            error_type=type(exc).__name__,
        )
        return {}
    finally:
        elapsed = (time.perf_counter() - t0) * 1000
        state.llm_call_durations.append(
            {
                "node": node_name,
                "call_type": "json",
                "duration_ms": round(elapsed, 1),
                "status": status,
            }
        )
    if not isinstance(result, dict):
        state.add_step(
            f"{node_name}_llm",
            status="error",
            error="provider returned non-object JSON",
        )
        return {}
    state.add_step(f"{node_name}_llm", status="ok", result=result)
    return result


def llm_chat(
    state: ConversationState,
    node_name: str,
    draft: str,
    provider: Optional[Any],
) -> str:
    if provider is None:
        return ""
    t0 = time.perf_counter()
    status = "ok"
    try:
        response = provider.chat(
            [
                {"role": "system", "content": RESPONSE_SYSTEM},
                {"role": "user", "content": f"Draft response:\n{draft}"},
            ]
        )
    except Exception as exc:
        status = "error"
        state.add_step(
            f"{node_name}_llm",
            status="error",
            error_type=type(exc).__name__,
        )
        return ""
    finally:
        elapsed = (time.perf_counter() - t0) * 1000
        state.llm_call_durations.append(
            {
                "node": node_name,
                "call_type": "chat",
                "duration_ms": round(elapsed, 1),
                "status": status,
            }
        )
    response = response.strip()
    if response:
        state.add_step(f"{node_name}_llm", status="ok")
    return response


def apply_llm_intent_slots(
    state: ConversationState,
    payload: Dict[str, Any],
) -> None:
    intent = str(payload.get("intent") or "").strip()
    if intent in SUPPORTED_INTENTS and (
        intent != "unknown" or state.current_intent == "unknown"
    ):
        state.current_intent = intent
    slots = payload.get("slots") or {}
    if not isinstance(slots, dict):
        return
    for key in (
        "order_id",
        "payment_method_id",
        "reason",
    ):
        value = clean_llm_scalar(slots.get(key))
        if value:
            state.slots[key] = value
    for key in ("item_ids", "new_item_ids"):
        values = clean_llm_list(slots.get(key))
        if values:
            state.slots[key] = values
    address = slots.get("address")
    if isinstance(address, dict):
        cleaned_address = {
            key: clean_llm_scalar(address.get(key)) or ""
            for key in ("address1", "address2", "city", "state", "country", "zip")
        }
        if cleaned_address["address1"] and cleaned_address["zip"]:
            state.slots["address"] = cleaned_address


def llm_policy_decision(
    state: ConversationState,
    content: str,
    fallback_decision: str,
    policy_excerpt: str,
    llm_json_fn: Callable,
) -> Dict[str, Any]:
    payload = llm_json_fn(
        state,
        "policy_reasoner",
        POLICY_SYSTEM,
        {
            "user_message": content,
            "policy_excerpt": policy_excerpt[:6000],
            "current_intent": state.current_intent,
            "slots": state.slots,
            "loaded_context": state.loaded_context.model_dump(),
            "authenticated_user_id": state.authenticated_user_id,
            "fallback_decision": fallback_decision,
        },
        {
            "type": "object",
            "properties": {
                "decision": {"type": "string"},
                "intent": {"type": "string"},
                "missing_slots": {"type": "array"},
                "user_confirmation_required": {"type": "boolean"},
                "explanation_for_user": {"type": "string"},
                "internal_reasoning_summary": {"type": "string"},
            },
        },
    )
    decision = payload.get("decision")
    if decision not in {"allow", "ask_clarification", "deny", "transfer"}:
        return {}
    if payload.get("intent") not in SUPPORTED_INTENTS:
        payload["intent"] = state.current_intent
    missing_slots = payload.get("missing_slots")
    if not isinstance(missing_slots, list):
        payload["missing_slots"] = []
    return payload


def apply_llm_action_plan(
    state: ConversationState,
    content: str,
    llm_json_fn: Callable,
    clean_llm_scalar_fn: Callable,
    normalize_fn: Callable,
    has_required_args_fn: Callable,
    pending_prompt_fn: Callable,
    set_pending_fn: Callable,
    transfer_fn: Callable,
    order_lookup_fn: Callable,
    assistant_fn: Callable,
    tool_catalog: str,
) -> bool:
    plan = llm_json_fn(
        state,
        "action_planner",
        ACTION_PLANNER_SYSTEM,
        {
            "user_message": content,
            "policy_decision": (
                state.policy_decision.model_dump() if state.policy_decision else None
            ),
            "current_intent": state.current_intent,
            "slots": state.slots,
            "loaded_context": state.loaded_context.model_dump(),
            "tool_catalog": tool_catalog,
        },
        {
            "type": "object",
            "properties": {
                "plan_type": {"type": "string"},
                "action_name": {"type": "string"},
                "arguments": {"type": "object"},
                "response": {"type": "string"},
            },
        },
    )
    if not plan:
        return False
    plan_type = plan.get("plan_type") or plan.get("type")
    response = clean_llm_scalar_fn(plan.get("response")) or ""
    if plan_type == "lookup_order":
        order_lookup_fn(state)
        return True
    if plan_type == "transfer":
        transfer_fn(state, content)
        return True
    if plan_type in {"ask_clarification", "respond"} and response:
        assistant_fn(state, response)
        return True
    if plan_type != "pending_write":
        return False
    action_name = clean_llm_scalar_fn(plan.get("action_name")) or ""
    arguments = plan.get("arguments") or {}
    if action_name not in WRITE_ACTION_NAMES:
        return False
    if not isinstance(arguments, dict):
        return False
    arguments = normalize_fn(action_name, arguments)
    if not has_required_args_fn(action_name, arguments):
        return False
    prompt = response or pending_prompt_fn(action_name, arguments)
    if "confirm" not in prompt.lower():
        prompt = prompt.rstrip(".") + ". Please confirm yes or no."
    set_pending_fn(state, action_name, arguments, prompt)
    return True
