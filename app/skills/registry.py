"""Skill registry — single source of truth for the 8 write-operation skills.

Each SkillSpec bundles intent patterns, entry/required-read tools, guard
constraints, prompt guidance and few-shot examples that previously lived
scattered across ``action_specs.py``, ``prompts/llm_agent_system_v001.md``,
``registry.py`` and ``llm_agent.py``.

The registry exposes helpers consumed by:
  - ``llm_agent.py`` → :func:`build_skill_guidance_for_prompt` injects the
    prompt fragments into the system prompt template.
  - ``eval/cases.py`` → :data:`SKILL_BY_ACTION` derives ``skill_id`` for cases.
  - ``eval/baseline.py`` → :func:`skill_hashes` records per-skill change hash.
"""

from __future__ import annotations

from typing import Dict

from app.ops.serialization import stable_hash
from app.skills.spec import SkillSpec

# ──────────────────────────────────────────────────────────────────────────
# Skill definitions — extracted verbatim from the system prompt and llm_agent
# behaviour maps.  prompt_guidance/few_shot_examples render under the
# ``{skill_guidance}`` placeholder in ``llm_agent_system_v001.md``.
# ──────────────────────────────────────────────────────────────────────────

cancel_order = SkillSpec(
    skill_id="cancel_order",
    display_name="Cancel Order",
    version="1.0",
    description="Cancel a pending order with a valid reason.",
    intent_patterns=("cancel",),
    entry_tools=("get_order_details", "cancel_pending_order"),
    required_reads=("get_order_details",),
    guard_constraints=(
        "order_status=pending",
        "reason=no longer needed|ordered by mistake",
        "requires user confirmation",
    ),
    prompt_guidance=(
        "**Cancel Order** — load the order first, then call "
        "`cancel_pending_order(order_id, reason)`. "
        "Reason must be `no longer needed` or `ordered by mistake`. "
        "Order must be pending; if already processed, the guard blocks it."
    ),
    few_shot_examples=(
        "Example: Cancel order #W5918442 because no longer needed.\n"
        "→ call `get_order_details(order_id=\"#W5918442\")`\n"
        "→ call `cancel_pending_order(order_id=\"#W5918442\", reason=\"no longer needed\")`\n"
        "→ Tool succeeds → Reply: \"Order #W5918442 has been cancelled.\""
    ),
    risk="high",
    related_action_specs=("cancel_pending_order",),
    tags=("order_lifecycle", "pending_only"),
)

modify_address = SkillSpec(
    skill_id="modify_address",
    display_name="Modify Order Address",
    version="1.0",
    description="Modify a pending order's shipping address.",
    intent_patterns=("modify", "change", "update", "address"),
    entry_tools=("get_order_details", "modify_pending_order_address"),
    required_reads=("get_order_details",),
    guard_constraints=(
        "order_status=pending",
        "requires user confirmation",
        "full address (address1, city, state, country, zip)",
    ),
    prompt_guidance=(
        "**Modify Order Address** — load the order, then call "
        "`modify_pending_order_address(order_id, address1, city, state, country, zip)`. "
        "Requires a complete address. Do not ask for confirmation before the "
        "write tool call; the guard raises confirmation after that call."
    ),
    few_shot_examples=(
        "Example: Change address for order #W5918442 to 1 Main St, Apt 2, "
        "Boston, MA, USA, 02108.\n"
        "→ call `get_order_details(order_id=\"#W5918442\")`\n"
        "→ call `modify_pending_order_address(order_id=\"#W5918442\", address1=\"1 Main St\", "
        "address2=\"Apt 2\", city=\"Boston\", state=\"MA\", country=\"USA\", zip=\"02108\")`\n"
        "→ guard asks for confirmation → ask briefly and wait"
    ),
    risk="high",
    related_action_specs=("modify_pending_order_address",),
    tags=("order_lifecycle", "pending_only"),
)

modify_items = SkillSpec(
    skill_id="modify_items",
    display_name="Modify Order Items",
    version="1.0",
    description="Swap item variants in a pending order.",
    intent_patterns=("modify", "change", "update", "replace", "switch", "items"),
    entry_tools=("get_order_details", "get_item_details", "modify_pending_order_items"),
    required_reads=("get_order_details",),
    guard_constraints=(
        "order_status=pending",
        "new items must be same product as old",
        "new items must be available",
        "old and new item counts must match",
        "batch multiple item changes in one call (parallel arrays)",
        "requires user confirmation",
    ),
    prompt_guidance=(
        "**Modify Order Items** — load the order (and replacement items if "
        "needed), then call "
        "`modify_pending_order_items(order_id, item_ids, new_item_ids)`. "
        "Old/new arrays must be parallel and same length; new items must match "
        "the same product and be available. When changing multiple items in the "
        "same order, call once with parallel arrays. After success, use "
        "`calculate` for replacement charges / gift-card balance instead of "
        "calling modify_pending_order_payment."
    ),
    few_shot_examples=(
        "Example: Change item 1586641416 in order #W5918442 to new item 5925362855.\n"
        "→ call `get_order_details(order_id=\"#W5918442\")`\n"
        "→ call `modify_pending_order_items(order_id=\"#W5918442\", "
        "item_ids=[\"1586641416\"], new_item_ids=[\"5925362855\"])`\n"
        "→ Tool succeeds → call `calculate(...)` for the price difference"
    ),
    risk="high",
    related_action_specs=("modify_pending_order_items",),
    tags=("order_lifecycle", "pending_only", "inventory"),
)

modify_payment = SkillSpec(
    skill_id="modify_payment",
    display_name="Modify Order Payment",
    version="1.0",
    description="Change the payment method of a pending order.",
    intent_patterns=("modify", "change", "update", "payment"),
    entry_tools=("get_order_details", "modify_pending_order_payment"),
    required_reads=("get_order_details",),
    guard_constraints=(
        "order_status=pending",
        "payment method must belong to the user",
        "must differ from the current payment method",
        "gift card must have sufficient balance",
        "requires user confirmation",
    ),
    prompt_guidance=(
        "**Modify Order Payment** — load the order, then call "
        "`modify_pending_order_payment(order_id, payment_method_id)`. "
        "The payment method must belong to the user and differ from the current "
        "one. Do not call this after `modify_pending_order_items` just to cover "
        "replacement charges or answer balance questions — use `calculate`."
    ),
    few_shot_examples=(
        "Example: Change payment for order #W8855135 to credit_card_8105988.\n"
        "→ call `get_order_details(order_id=\"#W8855135\")`\n"
        "→ call `modify_pending_order_payment(order_id=\"#W8855135\", "
        "payment_method_id=\"credit_card_8105988\")`\n"
        "→ guard asks for confirmation → ask briefly and wait"
    ),
    risk="high",
    related_action_specs=("modify_pending_order_payment",),
    tags=("order_lifecycle", "pending_only", "payment_method"),
)

return_items = SkillSpec(
    skill_id="return_items",
    display_name="Return Items",
    version="1.0",
    description="Return delivered items for a refund.",
    intent_patterns=("return",),
    entry_tools=("get_order_details", "return_delivered_order_items"),
    required_reads=("get_order_details",),
    guard_constraints=(
        "order_status=delivered",
        "item_ids must be existing item IDs from that exact order",
        "payment method must belong to the user",
        "if exactly one eligible payment method is known, use it instead of asking",
        "requires user confirmation",
    ),
    prompt_guidance=(
        "**Return Items** — load the order, then call "
        "`return_delivered_order_items(order_id, item_ids, payment_method_id)`. "
        "Order must be delivered; item_ids must come from that exact order's "
        "loaded items. If exactly one eligible payment method is already known, "
        "use it instead of asking. After success, use `calculate` for the total "
        "refund."
    ),
    few_shot_examples=(
        "Example: Return the water bottle from order #W4817420 to "
        "gift_card_8168843.\n"
        "→ call `get_order_details(order_id=\"#W4817420\")`\n"
        "→ call `return_delivered_order_items(order_id=\"#W4817420\", "
        "item_ids=[\"6777246137\"], payment_method_id=\"gift_card_8168843\")`\n"
        "→ Tool succeeds → call `calculate(...)` for the total refund"
    ),
    risk="high",
    related_action_specs=("return_delivered_order_items",),
    tags=("order_lifecycle", "delivered_only", "return"),
)

exchange_items = SkillSpec(
    skill_id="exchange_items",
    display_name="Exchange Items",
    version="1.0",
    description="Exchange delivered items for different variants.",
    intent_patterns=("exchange",),
    entry_tools=("get_order_details", "get_item_details", "exchange_delivered_order_items"),
    required_reads=("get_order_details",),
    guard_constraints=(
        "order_status=delivered",
        "old and new item counts must match",
        "new items must be same product as old and available",
        "match all requested replacement options",
        "payment method must belong to the user",
        "if exactly one eligible payment method is known, use it instead of asking",
        "requires user confirmation",
    ),
    prompt_guidance=(
        "**Exchange Items** — load the order and replacement items, then call "
        "`exchange_delivered_order_items(order_id, item_ids, new_item_ids, "
        "payment_method_id)`. Order must be delivered; old/new counts must "
        "match; new items must be the same product and available. After success, "
        "use `calculate` for the price difference / gift-card balance."
    ),
    few_shot_examples=(
        "Example: Exchange item 6777246137 in order #W4817420 for item 4579334072 "
        "using gift_card_8168843.\n"
        "→ call `get_order_details(order_id=\"#W4817420\")`\n"
        "→ call `get_item_details(item_id=\"4579334072\")`\n"
        "→ call `exchange_delivered_order_items(order_id=\"#W4817420\", "
        "item_ids=[\"6777246137\"], new_item_ids=[\"4579334072\"], "
        "payment_method_id=\"gift_card_8168843\")`\n"
        "→ Tool succeeds → call `calculate(...)` for the price difference"
    ),
    risk="high",
    related_action_specs=("exchange_delivered_order_items",),
    tags=("order_lifecycle", "delivered_only", "exchange"),
)

modify_user_address = SkillSpec(
    skill_id="modify_user_address",
    display_name="Modify User Address",
    version="1.0",
    description="Modify the user's default address (no order_id).",
    intent_patterns=("modify", "change", "update", "address"),
    entry_tools=("get_user_details", "modify_user_address"),
    required_reads=("get_user_details",),
    guard_constraints=(
        "target user must be authenticated user",
        "address passed to user_id argument",
        "requires user confirmation",
    ),
    prompt_guidance=(
        "**Modify User Address** — load the user, then call "
        "`modify_user_address(user_id, address1, address2, city, state, country, zip)`. "
        "The user_id must be the authenticated user. If the user mentions an "
        "address change without an order_id, this is the right tool (not "
        "`modify_pending_order_address`)."
    ),
    few_shot_examples=(
        "Example: Change my default address to 12 Oak St, Unit 4, Austin, TX, "
        "USA, 78701.\n"
        "→ call `get_user_details(user_id=<authenticated_user_id>)`\n"
        "→ call `modify_user_address(user_id=<authenticated_user_id>, "
        "address1=\"12 Oak St\", address2=\"Unit 4\", city=\"Austin\", "
        "state=\"TX\", country=\"USA\", zip=\"78701\")`\n"
        "→ guard asks for confirmation → ask briefly and wait"
    ),
    risk="medium",
    related_action_specs=("modify_user_address",),
    tags=("user_profile", "address"),
)

modify_shipping = SkillSpec(
    skill_id="modify_shipping",
    display_name="Modify Shipping Method",
    version="1.0",
    description="Change the shipping method of a pending order.",
    intent_patterns=("modify", "change", "update", "shipping"),
    entry_tools=("get_order_details", "modify_pending_order_shipping_method"),
    required_reads=("get_order_details",),
    guard_constraints=(
        "order_status=pending",
        "new shipping method must differ from current",
        "valid method: standard|express|overnight",
        "paid upgrades require a valid payment method",
        "gift card must have sufficient balance for upgrade fee",
        "requires user confirmation",
    ),
    prompt_guidance=(
        "**Modify Shipping Method** — load the order, then call "
        "`modify_pending_order_shipping_method(order_id, shipping_method)`. "
        "Method must be `standard`, `express`, or `overnight` and differ from "
        "current. Paid upgrades (express/overnight) require a valid payment "
        "method with sufficient balance."
    ),
    few_shot_examples=(
        "Example: Upgrade the shipping on order #W1004 to express.\n"
        "→ call `get_order_details(order_id=\"#W1004\")`\n"
        "→ call `modify_pending_order_shipping_method(order_id=\"#W1004\", "
        "shipping_method=\"express\")`\n"
        "→ guard asks for confirmation → ask briefly and wait"
    ),
    risk="medium",
    related_action_specs=("modify_pending_order_shipping_method",),
    tags=("order_lifecycle", "pending_only", "shipping"),
)

# ──────────────────────────────────────────────────────────────────────────
# Registry tuples and lookup maps (mirrors action_specs convention)
# ──────────────────────────────────────────────────────────────────────────

SKILL_REGISTRY: tuple[SkillSpec, ...] = (
    cancel_order,
    modify_address,
    modify_items,
    modify_payment,
    return_items,
    exchange_items,
    modify_user_address,
    modify_shipping,
)

SKILL_BY_ID: Dict[str, SkillSpec] = {s.skill_id: s for s in SKILL_REGISTRY}
SKILL_BY_ACTION: Dict[str, SkillSpec] = {
    action: skill for skill in SKILL_REGISTRY for action in skill.related_action_specs
}


def build_skill_guidance_for_prompt() -> str:
    """Assemble every Skill's prompt guidance + few-shot into one prompt block.

    Rendered under the ``{skill_guidance}`` placeholder in
    ``prompts/llm_agent_system_v001.md``. Order matches SKILL_REGISTRY so the
    output is deterministic across runs (stable_hash friendly).
    """
    sections: list[str] = []
    for skill in SKILL_REGISTRY:
        section = f"### {skill.display_name}\n{skill.prompt_guidance}"
        if skill.few_shot_examples:
            section += f"\n\n{skill.few_shot_examples}"
        sections.append(section)
    return "\n\n".join(sections)


def skill_hashes() -> Dict[str, str]:
    """Per-skill stable hash of behaviour-relevant fields.

    Used by eval baseline metadata to detect whether a Skill's prompt or
    constraints changed between two eval runs.  Identity/version are excluded
    so that bumping a version alone (without touching behaviour) does not
    trigger a false-positive change signal.
    """
    return {
        skill.skill_id: stable_hash(
            {
                "intent_patterns": skill.intent_patterns,
                "entry_tools": skill.entry_tools,
                "required_reads": skill.required_reads,
                "guard_constraints": skill.guard_constraints,
                "prompt_guidance": skill.prompt_guidance,
                "few_shot_examples": skill.few_shot_examples,
            }
        )
        for skill in SKILL_REGISTRY
    }
