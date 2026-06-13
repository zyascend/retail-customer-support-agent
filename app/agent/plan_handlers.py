from __future__ import annotations

from typing import Any, Callable, Dict

from app.agent.models import ConversationState, Message, PendingAction


def plan_cancel(
    state: ConversationState,
    assistant_fn: Callable,
    set_pending_fn: Callable,
) -> None:
    order_id = state.slots.get("order_id")
    reason = state.slots.get("reason")
    if not order_id:
        assistant_fn(state, "Which order would you like to cancel?")
        return
    if not reason:
        assistant_fn(
            state,
            "Please provide a cancellation reason: no longer needed "
            "or ordered by mistake.",
        )
        return
    set_pending_fn(
        state,
        "cancel_pending_order",
        {"order_id": order_id, "reason": reason},
        f"Cancel order {order_id} because {reason}. Please confirm yes or no.",
    )


def plan_address_change(
    state: ConversationState,
    assistant_fn: Callable,
    set_pending_fn: Callable,
) -> None:
    order_id = state.slots.get("order_id")
    address = state.slots.get("address")
    if not order_id:
        assistant_fn(
            state,
            "Which order should have its shipping address changed?",
        )
        return
    if not address:
        assistant_fn(
            state,
            "Please provide the new address as: address to line1, line2, "
            "city, state, country, zip.",
        )
        return
    args = {"order_id": order_id, **address}
    set_pending_fn(
        state,
        "modify_pending_order_address",
        args,
        f"Modify the shipping address for order {order_id}. Please confirm yes or no.",
    )


def plan_return(
    state: ConversationState,
    assistant_fn: Callable,
    set_pending_fn: Callable,
) -> None:
    required = ["order_id", "item_ids", "payment_method_id"]
    missing = [key for key in required if not state.slots.get(key)]
    if missing:
        assistant_fn(
            state,
            "Please provide return details: order id, item id, "
            "and refund payment method.",
        )
        return
    set_pending_fn(
        state,
        "return_delivered_order_items",
        {
            "order_id": state.slots["order_id"],
            "item_ids": state.slots["item_ids"],
            "payment_method_id": state.slots["payment_method_id"],
        },
        f"Request a return for order {state.slots['order_id']}. "
        "Please confirm yes or no.",
    )


def plan_exchange(
    state: ConversationState,
    assistant_fn: Callable,
    set_pending_fn: Callable,
) -> None:
    required = ["order_id", "item_ids", "new_item_ids", "payment_method_id"]
    missing = [key for key in required if not state.slots.get(key)]
    if missing:
        assistant_fn(
            state,
            "Please provide exchange details: order id, old item id, "
            "new item id, and payment method.",
        )
        return
    set_pending_fn(
        state,
        "exchange_delivered_order_items",
        {
            "order_id": state.slots["order_id"],
            "item_ids": state.slots["item_ids"],
            "new_item_ids": state.slots["new_item_ids"],
            "payment_method_id": state.slots["payment_method_id"],
        },
        f"Request an exchange for order {state.slots['order_id']}. "
        "Please confirm yes or no.",
    )


def plan_modify_items(
    state: ConversationState,
    assistant_fn: Callable,
    set_pending_fn: Callable,
) -> None:
    order_id = state.slots.get("order_id")
    item_ids = state.slots.get("item_ids")
    new_item_ids = state.slots.get("new_item_ids")
    if not order_id:
        assistant_fn(state, "Which order would you like to modify items for?")
        return
    if not item_ids:
        assistant_fn(state, "Which item would you like to replace?")
        return
    if not new_item_ids:
        assistant_fn(state, "Please provide the new item id for the replacement.")
        return
    set_pending_fn(
        state,
        "modify_pending_order_items",
        {
            "order_id": order_id,
            "item_ids": item_ids,
            "new_item_ids": new_item_ids,
        },
        f"Replace items in order {order_id}. Please confirm yes or no.",
    )


def plan_modify_payment(
    state: ConversationState,
    assistant_fn: Callable,
    set_pending_fn: Callable,
) -> None:
    order_id = state.slots.get("order_id")
    payment_method_id = state.slots.get("payment_method_id")
    if not order_id:
        assistant_fn(state, "Which order would you like to change payment for?")
        return
    if not payment_method_id:
        assistant_fn(state, "Which payment method would you like to use?")
        return
    set_pending_fn(
        state,
        "modify_pending_order_payment",
        {
            "order_id": order_id,
            "payment_method_id": payment_method_id,
        },
        f"Change payment for order {order_id}. Please confirm yes or no.",
    )


def plan_user_address(
    state: ConversationState,
    assistant_fn: Callable,
    set_pending_fn: Callable,
) -> None:
    address = state.slots.get("address")
    if not address:
        assistant_fn(
            state,
            "Please provide the new address as: address to line1, line2, "
            "city, state, country, zip.",
        )
        return
    user_id = state.authenticated_user_id
    if not user_id:
        assistant_fn(state, "Please verify your identity first.")
        return
    args = {"user_id": user_id, **address}
    set_pending_fn(
        state,
        "modify_user_address",
        args,
        "Modify your default address. Please confirm yes or no.",
    )


def respond_with_order_lookup(
    state: ConversationState,
    assistant_fn: Callable,
    get_order_fn: Callable,
) -> None:
    order_id = state.slots.get("order_id")
    if not order_id:
        assistant_fn(state, "Which order would you like me to look up?")
        return
    order = state.loaded_context.orders.get(order_id) or get_order_fn(order_id)
    if not order:
        assistant_fn(state, f"I could not find order {order_id}.")
        return
    assistant_fn(
        state,
        f"Order {order_id} is currently {order.get('status')}.",
    )


def transfer_to_human(
    state: ConversationState,
    content: str,
    gateway: Any,
) -> None:
    gateway.execute(
        state=state,
        tool_name="transfer_to_human_agents",
        arguments={"summary": content[:500]},
    )
    # Transfer message must NOT pass through LLM refinement
    state.messages.append(
        Message(
            role="assistant",
            content="YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.",
        )
    )


def set_pending(
    state: ConversationState,
    action_name: str,
    arguments: Dict[str, Any],
    prompt: str,
    assistant_fn: Callable,
) -> None:
    state.pending_action = PendingAction(
        action_name=action_name,
        arguments=arguments,
        user_facing_summary=prompt.replace(" Please confirm yes or no.", ""),
    )
    state.confirmation_status = "required"
    assistant_fn(state, prompt)
