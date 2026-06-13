from __future__ import annotations

import re
from typing import Any, Callable, Dict

from app.agent.models import ConversationState, PolicyDecision


def receive_message(state: ConversationState, content: str) -> None:
    state.add_step("receive_message", content=content)


def conversation_gate(
    state: ConversationState,
    content: str,
    confirmation_resolver: Any,
    gateway: Any,
    assistant_fn: Callable,
    map_guard_error_fn: Callable,
) -> None:
    if state.pending_action:
        resolution = confirmation_resolver.resolve(content)
        state.confirmation_status = {
            "confirm": "confirmed",
            "deny": "denied",
            "changed": "changed",
            "unknown": "unknown",
        }[resolution]
        state.add_step("conversation_gate", confirmation=resolution)
        if resolution == "confirm":
            action = state.pending_action
            record = gateway.execute(
                state=state,
                tool_name=action.action_name,
                arguments=action.arguments,
                confirmed=True,
            )
            state.pending_action = None
            if record.status == "success":
                assistant_fn(
                    state,
                    "Done. I have completed the requested update.",
                )
            else:
                assistant_fn(
                    state,
                    map_guard_error_fn(str(record.error)),
                )
        elif resolution == "deny":
            state.pending_action = None
            assistant_fn(state, "No changes were made.")
        elif resolution == "changed":
            state.pending_action = None
            state.slots = {}
            assistant_fn(
                state,
                "I discarded the previous request. Please provide updated details.",
            )
        else:
            assistant_fn(
                state,
                f"Please confirm yes or no: {state.pending_action.user_facing_summary}",
            )
        return
    state.add_step(
        "conversation_gate",
        authenticated=bool(state.authenticated_user_id),
    )


def identity_resolver(
    state: ConversationState,
    content: str,
    has_assistant_fn: Callable,
    assistant_fn: Callable,
    gateway: Any,
    identity_resolver_name_zip_fn: Callable,
) -> None:
    if state.authenticated_user_id or has_assistant_fn(state):
        return
    from app.agent.parsers import EMAIL_RE  # noqa: PLC0415

    email_match = EMAIL_RE.search(content)
    if not email_match:
        if identity_resolver_name_zip_fn(state, content):
            return
        assistant_fn(
            state,
            "Please provide the email address on your account so I can verify you.",
        )
        state.add_step("identity_resolver", status="need_user_info")
        return
    email = email_match.group(0)
    record = gateway.execute(
        state=state,
        tool_name="find_user_id_by_email",
        arguments={"email": email},
    )
    if record.status != "success":
        assistant_fn(state, "I could not verify that email address.")
        return
    user_id = str(record.observation)
    state.authenticated_user_id = user_id
    state.auth_method = "email"
    state.active_user_identity = {"email": email, "user_id": user_id}
    user_record = gateway.execute(
        state=state,
        tool_name="get_user_details",
        arguments={"user_id": user_id},
    )
    if user_record.status == "success":
        state.loaded_context.users[user_id] = user_record.observation
    state.add_step("identity_resolver", status="authenticated", user_id=user_id)


def intent_and_slot_extractor(
    state: ConversationState,
    content: str,
    has_assistant_fn: Callable,
    infer_intent_fn: Callable,
    llm_json_fn: Callable,
    INTENT_SLOT_SYSTEM: str,
    apply_llm_intent_slots_fn: Callable,
    parse_address_fn: Callable,
    parse_item_replacement_pairs_fn: Callable,
    parse_shipping_method_fn: Callable,
    merge_slots_fn: Callable,
) -> None:
    if has_assistant_fn(state):
        return
    from app.agent.parsers import ITEM_RE, ORDER_RE, PAYMENT_RE  # noqa: PLC0415


    lowered = content.lower()
    # Preserve existing intent when message is a bare confirmation/denial
    bare_response = lowered.strip() in {
        "yes",
        "no",
        "confirm",
        "ok",
        "y",
        "n",
        "go ahead",
        "proceed",
        "sure",
        "yeah",
        "yep",
        "nope",
        "cancel",
    }
    if bare_response and state.current_intent and state.current_intent != "unknown":
        pass  # keep prior intent rather than resetting to unknown
    else:
        state.current_intent = infer_intent_fn(lowered)
    llm_payload = llm_json_fn(
        state,
        "intent_and_slot_extractor",
        INTENT_SLOT_SYSTEM,
        {
            "user_message": content,
            "known_slots": state.slots,
            "authenticated_user_id": state.authenticated_user_id,
        },
        {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "slots": {"type": "object"},
            },
        },
    )
    if llm_payload:
        llm_intent = str(llm_payload.get("intent") or "").strip()
        if llm_intent and llm_intent != state.current_intent:
            state.add_step(
                "intent_and_slot_extractor_divergence",
                code_intent=state.current_intent,
                llm_intent=llm_intent,
                resolved=state.current_intent,
            )
        apply_llm_intent_slots_fn(state, llm_payload)
    llm_slots = (llm_payload.get("slots") or {}) if llm_payload else {}
    code_slots: Dict[str, Any] = dict(state.slots)

    order_match = ORDER_RE.search(content)
    if order_match:
        code_slots["order_id"] = order_match.group(0)
    payment_match = PAYMENT_RE.search(content)
    if payment_match:
        code_slots["payment_method_id"] = payment_match.group(0)
    item_ids = [
        item
        for item in ITEM_RE.findall(content)
        if not item.startswith("000") and len(item) >= 8
    ]
    if item_ids:
        code_slots["item_ids"] = item_ids
    if "ordered by mistake" in lowered:
        code_slots["reason"] = "ordered by mistake"
    elif "no longer needed" in lowered or "don't need" in lowered:
        code_slots["reason"] = "no longer needed"
    address = parse_address_fn(content)
    if address:
        code_slots["address"] = address
    item_pairs = parse_item_replacement_pairs_fn(lowered)
    if item_pairs:
        code_slots["item_ids"] = [old for old, _new in item_pairs]
        code_slots["new_item_ids"] = [new for _old, new in item_pairs]

    new_item_marker = re.search(
        r"(?:new items?|exchange for|instead|to new item|"
        r"for new items?)\s+(\d{8,})",
        lowered,
    )
    if new_item_marker:
        new_item_id = new_item_marker.group(1)
        code_slots["new_item_ids"] = [new_item_id]
        if "item_ids" in code_slots:
            code_slots["item_ids"] = [
                iid for iid in code_slots["item_ids"] if iid != new_item_id
            ]

    shipping_method = parse_shipping_method_fn(content)
    if shipping_method:
        code_slots["shipping_method"] = shipping_method

    state.slots = merge_slots_fn(
        code_slots=code_slots,
        llm_slots=llm_slots,
    )


def context_loader(
    state: ConversationState,
    content: str,
    has_assistant_fn: Callable,
    gateway: Any,
    assistant_fn: Callable,
) -> None:
    if has_assistant_fn(state):
        return
    order_id = state.slots.get("order_id")
    if order_id and order_id not in state.loaded_context.orders:
        record = gateway.execute(
            state=state,
            tool_name="get_order_details",
            arguments={"order_id": order_id},
        )
        if record.status == "success":
            order = record.observation
            state.loaded_context.orders[order_id] = order
            if order.get("user_id") != state.authenticated_user_id:
                assistant_fn(
                    state,
                    "I cannot access or modify orders for another account.",
                )
        else:
            assistant_fn(state, f"I could not find order {order_id}.")
    state.add_step(
        "context_loader",
        loaded_orders=list(state.loaded_context.orders),
    )


def policy_reasoner(
    state: ConversationState,
    content: str,
    has_assistant_fn: Callable,
    WRITE_INTENTS: set,
    code_missing_slots_fn: Callable,
    llm_policy_decision_fn: Callable,
    merge_policy_decisions_fn: Callable,
    clean_llm_scalar_fn: Callable,
) -> None:
    if has_assistant_fn(state):
        return
    write_intents = WRITE_INTENTS

    # ── Code track ──
    if state.current_intent == "transfer":
        code_decision = "transfer"
    elif state.current_intent == "lookup":
        code_decision = "allow"
    elif state.current_intent in write_intents:
        if code_missing_slots_fn(state):
            code_decision = "ask_clarification"
        else:
            code_decision = "allow"
    else:
        code_decision = "ask_clarification"

    # ── LLM track ──
    llm_payload = llm_policy_decision_fn(state, content, code_decision)
    llm_decision = llm_payload.get("decision") if llm_payload else None

    # ── Conservative merge ──
    final_decision = merge_policy_decisions_fn(
        code_decision=code_decision,
        llm_decision=llm_decision,
    )

    # Log divergence for audit
    if llm_decision and llm_decision != code_decision:
        state.add_step(
            "policy_reasoner_divergence",
            code=code_decision,
            llm=llm_decision,
            merged=final_decision,
        )

    explanation = ""
    if llm_payload and final_decision == "deny":
        explanation = clean_llm_scalar_fn(llm_payload.get("explanation_for_user")) or ""

    state.policy_decision = PolicyDecision(
        decision=final_decision,
        intent=(
            llm_payload.get("intent", state.current_intent)
            if llm_payload
            else state.current_intent
        ),
        missing_slots=(
            llm_payload.get("missing_slots")
            if llm_payload and isinstance(llm_payload.get("missing_slots"), list)
            else []
        ),
        user_confirmation_required=(
            llm_payload.get("user_confirmation_required", False)
            if llm_payload
            else state.current_intent in write_intents
        ),
        explanation_for_user=explanation,
        internal_reasoning_summary=(
            llm_payload.get("internal_reasoning_summary", "") if llm_payload else ""
        ),
    )
    state.add_step(
        "policy_reasoner",
        decision=final_decision,
        llm_used=bool(llm_payload),
        code_decision=code_decision,
    )


def action_planner(
    state: ConversationState,
    content: str,
    has_assistant_fn: Callable,
    assistant_fn: Callable,
    transfer_to_human_fn: Callable,
    apply_llm_action_plan_fn: Callable,
    respond_with_order_lookup_fn: Callable,
    plan_cancel_fn: Callable,
    plan_address_change_fn: Callable,
    plan_modify_items_fn: Callable,
    plan_modify_payment_fn: Callable,
    plan_user_address_fn: Callable,
    plan_return_fn: Callable,
    plan_exchange_fn: Callable,
    plan_shipping_method_fn: Callable,
) -> None:
    if has_assistant_fn(state):
        return
    if state.policy_decision and state.policy_decision.decision == "deny":
        assistant_fn(
            state,
            state.policy_decision.explanation_for_user
            or "I cannot complete that request under the retail policy.",
        )
        return
    if state.policy_decision and state.policy_decision.decision == "transfer":
        transfer_to_human_fn(state, content)
        return
    if apply_llm_action_plan_fn(state, content):
        return
    intent = state.current_intent
    if intent == "transfer":
        transfer_to_human_fn(state, content)
        return
    if intent == "lookup":
        respond_with_order_lookup_fn(state)
        return
    if intent == "cancel_order":
        plan_cancel_fn(state)
        return
    if intent == "modify_order_address":
        plan_address_change_fn(state)
        return
    if intent == "modify_order_items":
        plan_modify_items_fn(state)
        return
    if intent == "modify_order_payment":
        plan_modify_payment_fn(state)
        return
    if intent == "modify_user_address":
        plan_user_address_fn(state)
        return
    if intent == "return_items":
        plan_return_fn(state)
        return
    if intent == "exchange_items":
        plan_exchange_fn(state)
        return
    if intent == "modify_shipping_method":
        plan_shipping_method_fn(state)
        return
    assistant_fn(
        state,
        "Please tell me which order or retail support action you need help with.",
    )


def write_action_guard(state: ConversationState, content: str) -> None:
    state.add_step(
        "write_action_guard",
        pending_action=(
            state.pending_action.model_dump() if state.pending_action else None
        ),
    )


def tool_executor(state: ConversationState, content: str) -> None:
    state.add_step(
        "tool_executor",
        deferred_pending_write=bool(state.pending_action),
    )


def observation_reducer(state: ConversationState, content: str) -> None:
    state.add_step("observation_reducer", tool_result_count=len(state.tool_results))


def response_generator(
    state: ConversationState,
    content: str,
    has_assistant_fn: Callable,
    assistant_fn: Callable,
) -> None:
    if not has_assistant_fn(state):
        assistant_fn(state, "I need a bit more information to help with that.")
    state.add_step("response_generator", last_message=state.messages[-1].content)


def run_logger(state: ConversationState, content: str) -> None:
    state.add_step("run_logger", message_count=len(state.messages))
