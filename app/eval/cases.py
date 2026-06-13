from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: str
    messages: List[Dict[str, str]]
    expected_user_id: str
    expected_intent: str
    order_id: Optional[str] = None
    expected_write_lock: Optional[str] = None
    expected_order_status: Optional[str] = None
    expected_confirmation_status: Optional[str] = None
    expected_guard_block_reason: Optional[str] = None
    expected_no_write: bool = False
    expected_tool_names: List[str] = field(default_factory=list)
    expected_assistant_contains: Optional[str] = None
    max_turns: int = 8
    subset: str = "curated_mvp"
    capability: Optional[str] = None
    policy_area: Optional[str] = None
    scenario_family: Optional[str] = None
    variant_type: Optional[str] = None
    language_variation_level: Optional[str] = None
    expected_db_assertions: Dict[str, object] = field(default_factory=dict)
    expected_tool_sequence: List[str] = field(default_factory=list)
    seed: Optional[int] = None
    # ── Phase 5: tool-calling 语义断言 ──
    required_tools: set = field(default_factory=set)
    forbidden_tools: set = field(default_factory=set)


CURATED_MVP_CASES: List[EvalCase] = [
    EvalCase(
        case_id="lookup_pending_order",
        category="lookup",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. "
                    "What is the status of order #W5918442?"
                ),
            }
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="lookup",
        order_id="#W5918442",
        expected_tool_names=["find_user_id_by_email", "get_order_details"],
        expected_assistant_contains="pending",
    ),
    EvalCase(
        case_id="cancel_pending_order",
        category="cancel",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. "
                    "Cancel order #W5918442 because no longer needed."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="cancel_order",
        order_id="#W5918442",
        expected_write_lock="order:#W5918442:cancel",
        expected_order_status="cancelled",
        expected_confirmation_status="confirmed",
        expected_tool_names=["cancel_pending_order"],
    ),
    EvalCase(
        case_id="modify_pending_order_address",
        category="modify_address",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Change address "
                    "for order #W5918442 address to 1 Main St, Apt 2, "
                    "Boston, MA, USA, 02108."
                ),
            },
            {"role": "user", "content": "confirm"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="modify_order_address",
        order_id="#W5918442",
        expected_write_lock="order:#W5918442:modify_address",
        expected_order_status="pending",
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_pending_order_address"],
    ),
    EvalCase(
        case_id="return_delivered_order_item",
        category="return",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is ava.moore6020@example.com. Return item "
                    "6777246137 from order #W4817420 to gift_card_8168843."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="ava_moore_2033",
        expected_intent="return_items",
        order_id="#W4817420",
        expected_write_lock="item:6777246137:return",
        expected_order_status="return requested",
        expected_confirmation_status="confirmed",
        expected_tool_names=["return_delivered_order_items"],
    ),
    EvalCase(
        case_id="exchange_delivered_order_item",
        category="exchange",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is ava.moore6020@example.com. Exchange item "
                    "6777246137 from order #W4817420 instead 4579334072 "
                    "using gift_card_8168843."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="ava_moore_2033",
        expected_intent="exchange_items",
        order_id="#W4817420",
        expected_write_lock="item:6777246137:exchange",
        expected_order_status="exchange requested",
        expected_confirmation_status="confirmed",
        expected_tool_names=["exchange_delivered_order_items"],
    ),
    EvalCase(
        case_id="transfer_to_human",
        category="transfer",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. I want a human agent."
                ),
            }
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="transfer",
        expected_tool_names=["transfer_to_human_agents"],
        expected_assistant_contains=(
            "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
        ),
    ),
    EvalCase(
        case_id="deny_cancel_confirmation",
        category="confirmation",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. "
                    "Cancel order #W5918442 because ordered by mistake."
                ),
            },
            {"role": "user", "content": "no"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="cancel_order",
        order_id="#W5918442",
        expected_order_status="pending",
        expected_confirmation_status="denied",
        expected_no_write=True,
        expected_assistant_contains="No changes were made",
    ),
    EvalCase(
        case_id="changed_confirmation_discards_pending_action",
        category="confirmation",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. "
                    "Cancel order #W5918442 because no longer needed."
                ),
            },
            {"role": "user", "content": "No, use item 1234567890 instead."},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="cancel_order",
        order_id="#W5918442",
        expected_order_status="pending",
        expected_confirmation_status="changed",
        expected_no_write=True,
        expected_assistant_contains="discarded",
    ),
    EvalCase(
        case_id="block_cancel_processed_order",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is james.li4495@example.com. Cancel order "
                    "#W2611340 because no longer needed."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="james_li_5688",
        expected_intent="cancel_order",
        order_id="#W2611340",
        expected_order_status="processed",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="non_pending_order_cannot_be_cancelled",
        expected_no_write=True,
        expected_tool_names=["cancel_pending_order"],
    ),
    EvalCase(
        case_id="block_return_pending_order",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Return item "
                    "1725100896 from order #W5918442 to credit_card_5051208."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="return_items",
        order_id="#W5918442",
        expected_order_status="pending",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="non_delivered_order_cannot_be_returned",
        expected_no_write=True,
        expected_tool_names=["return_delivered_order_items"],
    ),
    EvalCase(
        case_id="block_wrong_user_order_access",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is ava.moore6020@example.com. Cancel order "
                    "#W5918442 because no longer needed."
                ),
            }
        ],
        expected_user_id="ava_moore_2033",
        expected_intent="cancel_order",
        order_id="#W5918442",
        expected_order_status="pending",
        expected_no_write=True,
        expected_assistant_contains="another account",
    ),
]


def _case_for_subset(case: EvalCase, subset: str) -> EvalCase:
    return EvalCase(
        case_id=case.case_id,
        category=case.category,
        messages=[dict(message) for message in case.messages],
        expected_user_id=case.expected_user_id,
        expected_intent=case.expected_intent,
        order_id=case.order_id,
        expected_write_lock=case.expected_write_lock,
        expected_order_status=case.expected_order_status,
        expected_confirmation_status=case.expected_confirmation_status,
        expected_guard_block_reason=case.expected_guard_block_reason,
        expected_no_write=case.expected_no_write,
        expected_tool_names=list(case.expected_tool_names),
        expected_assistant_contains=case.expected_assistant_contains,
        max_turns=case.max_turns,
        subset=subset,
        capability=case.capability,
        policy_area=case.policy_area,
        scenario_family=case.scenario_family,
        variant_type=case.variant_type,
        language_variation_level=case.language_variation_level,
        expected_db_assertions=dict(case.expected_db_assertions),
        expected_tool_sequence=list(case.expected_tool_sequence),
        seed=case.seed,
        required_tools=set(case.required_tools),
        forbidden_tools=set(case.forbidden_tools),
    )


PHASE5_NEW_CASES: List[EvalCase] = [
    EvalCase(
        case_id="auth_name_zip_lookup_order",
        category="auth",
        messages=[
            {
                "role": "user",
                "content": (
                    "My name is Sofia Rossi and my zip is 78784. "
                    "What is the status of order #W5918442?"
                ),
            }
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="lookup",
        order_id="#W5918442",
        expected_tool_names=["find_user_id_by_name_zip", "get_order_details"],
        expected_assistant_contains="pending",
        subset="generalized_mvp",
        capability="auth_name_zip",
        policy_area="authentication",
    ),
    EvalCase(
        case_id="modify_pending_order_items_success",
        category="modify_items",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Change item "
                    "1586641416 in order #W5918442 to new item 5925362855."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="modify_order_items",
        order_id="#W5918442",
        expected_write_lock="order:#W5918442:modify_items",
        expected_order_status="pending (item modified)",
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_pending_order_items"],
        subset="generalized_mvp",
        capability="modify_items",
        policy_area="inventory",
    ),
    EvalCase(
        case_id="modify_pending_order_payment_success",
        category="modify_payment",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.li7352@example.com. Change payment for "
                    "order #W8855135 to credit_card_8105988."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_li_9219",
        expected_intent="modify_order_payment",
        order_id="#W8855135",
        expected_write_lock="order:#W8855135:modify_payment",
        expected_order_status="pending",
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_pending_order_payment"],
        subset="generalized_mvp",
        capability="modify_payment",
        policy_area="payment_method",
    ),
    EvalCase(
        case_id="modify_user_default_address_success",
        category="modify_address",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Change my default "
                    "address to 12 Oak St, Unit 4, Austin, TX, USA, 78701."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="modify_user_address",
        expected_write_lock="user:sofia_rossi_8776:modify_address",
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_user_address"],
        subset="generalized_mvp",
        capability="modify_user_address",
        policy_area="user_profile",
        expected_db_assertions={
            "user_id": "sofia_rossi_8776",
            "address": {
                "address1": "12 Oak St",
                "address2": "Unit 4",
                "city": "Austin",
                "state": "TX",
                "country": "USA",
                "zip": "78701",
            },
        },
    ),
    EvalCase(
        case_id="multi_item_return_success",
        category="return",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is ava.moore6020@example.com. Return items "
                    "6777246137 and 4900661478 from order #W4817420 "
                    "to gift_card_8168843."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="ava_moore_2033",
        expected_intent="return_items",
        order_id="#W4817420",
        expected_write_lock="item:4900661478,6777246137:return",
        expected_order_status="return requested",
        expected_confirmation_status="confirmed",
        expected_tool_names=["return_delivered_order_items"],
        subset="generalized_mvp",
        capability="multi_item_return",
        policy_area="return_items",
    ),
    EvalCase(
        case_id="multi_item_exchange_success",
        category="exchange",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is ava.moore6020@example.com. Exchange items "
                    "6777246137 to 4579334072 and 6700049080 to 5925362855 "
                    "from order #W4817420 using gift_card_8168843."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="ava_moore_2033",
        expected_intent="exchange_items",
        order_id="#W4817420",
        expected_write_lock="item:6700049080,6777246137:exchange",
        expected_order_status="exchange requested",
        expected_confirmation_status="confirmed",
        expected_tool_names=["exchange_delivered_order_items"],
        subset="generalized_mvp",
        capability="multi_item_exchange",
        policy_area="exchange_items",
    ),
    EvalCase(
        case_id="deny_modify_payment_confirmation",
        category="confirmation",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.li7352@example.com. Change payment for "
                    "order #W8855135 to credit_card_8105988."
                ),
            },
            {"role": "user", "content": "no"},
        ],
        expected_user_id="sofia_li_9219",
        expected_intent="modify_order_payment",
        order_id="#W8855135",
        expected_order_status="pending",
        expected_confirmation_status="denied",
        expected_no_write=True,
        expected_assistant_contains="No changes were made",
        subset="generalized_mvp",
        capability="modify_payment",
        policy_area="confirmation",
    ),
    EvalCase(
        case_id="changed_modify_items_confirmation",
        category="confirmation",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Change item "
                    "1586641416 in order #W5918442 to new item 5925362855."
                ),
            },
            {"role": "user", "content": "No, use item 7523669277 instead."},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="modify_order_items",
        order_id="#W5918442",
        expected_order_status="pending",
        expected_confirmation_status="changed",
        expected_no_write=True,
        subset="generalized_mvp",
        capability="modify_items",
        policy_area="confirmation",
    ),
    EvalCase(
        case_id="block_item_product_mismatch",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Change item "
                    "1586641416 in order #W5918442 to new item 9612497925."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="modify_order_items",
        order_id="#W5918442",
        expected_order_status="pending",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="replacement_item_product_mismatch",
        expected_no_write=True,
        expected_tool_names=["modify_pending_order_items"],
        subset="generalized_mvp",
        capability="modify_items",
        policy_area="inventory",
    ),
    EvalCase(
        case_id="block_item_unavailable",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Change item "
                    "6117189161 in order #W5918442 to new item 4859937227."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="modify_order_items",
        order_id="#W5918442",
        expected_order_status="pending",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="replacement_item_unavailable",
        expected_no_write=True,
        expected_tool_names=["modify_pending_order_items"],
        subset="generalized_mvp",
        capability="modify_items",
        policy_area="inventory",
    ),
    EvalCase(
        case_id="block_payment_not_owned",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Change payment for "
                    "order #W5918442 to gift_card_8168843."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="modify_order_payment",
        order_id="#W5918442",
        expected_order_status="pending",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="payment_method_not_owned",
        expected_no_write=True,
        expected_tool_names=["modify_pending_order_payment"],
        subset="generalized_mvp",
        capability="modify_payment",
        policy_area="payment_method",
    ),
    EvalCase(
        case_id="block_payment_insufficient_gift_card",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is raj.sanchez2046@example.com. Change payment for "
                    "order #W4566809 to gift_card_2259499."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="raj_sanchez_2970",
        expected_intent="modify_order_payment",
        order_id="#W4566809",
        expected_order_status="pending",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="gift_card_balance_insufficient",
        expected_no_write=True,
        expected_tool_names=["modify_pending_order_payment"],
        subset="generalized_mvp",
        capability="modify_payment",
        policy_area="payment_method",
    ),
    EvalCase(
        case_id="block_same_payment_method",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Change payment for "
                    "order #W5918442 to credit_card_5051208."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="modify_order_payment",
        order_id="#W5918442",
        expected_order_status="pending",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="same_payment_method",
        expected_no_write=True,
        expected_tool_names=["modify_pending_order_payment"],
        subset="generalized_mvp",
        capability="modify_payment",
        policy_area="payment_method",
    ),
    EvalCase(
        case_id="block_modify_items_non_pending_order",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is james.li4495@example.com. Change item "
                    "6469567736 in order #W2611340 to new item 6777246137."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="james_li_5688",
        expected_intent="modify_order_items",
        order_id="#W2611340",
        expected_order_status="processed",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="non_pending_order_cannot_be_modified",
        expected_no_write=True,
        expected_tool_names=["modify_pending_order_items"],
        subset="generalized_mvp",
        capability="modify_items",
        policy_area="order_status",
    ),
    EvalCase(
        case_id="block_modify_payment_processed_order",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is james.li4495@example.com. Change payment for "
                    "order #W2611340 to credit_card_5051208."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="james_li_5688",
        expected_intent="modify_order_payment",
        order_id="#W2611340",
        expected_order_status="processed",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="non_pending_order_cannot_be_modified",
        expected_no_write=True,
        expected_tool_names=["modify_pending_order_payment"],
        subset="generalized_mvp",
        capability="modify_payment",
        policy_area="order_status",
    ),
    EvalCase(
        case_id="block_exchange_product_mismatch",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is ava.moore6020@example.com. Exchange item "
                    "6777246137 from order #W4817420 for new item 5925362855 "
                    "using gift_card_8168843."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="ava_moore_2033",
        expected_intent="exchange_items",
        order_id="#W4817420",
        expected_order_status="delivered",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="replacement_item_product_mismatch",
        expected_no_write=True,
        expected_tool_names=["exchange_delivered_order_items"],
        subset="generalized_mvp",
        capability="exchange_items",
        policy_area="inventory",
    ),
    EvalCase(
        case_id="block_exchange_unavailable_replacement",
        category="guard",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is ava.moore6020@example.com. Exchange item "
                    "6777246137 from order #W4817420 for new item 1434748144 "
                    "using gift_card_8168843."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="ava_moore_2033",
        expected_intent="exchange_items",
        order_id="#W4817420",
        expected_order_status="delivered",
        expected_confirmation_status="confirmed",
        expected_guard_block_reason="replacement_item_unavailable",
        expected_no_write=True,
        expected_tool_names=["exchange_delivered_order_items"],
        subset="generalized_mvp",
        capability="exchange_items",
        policy_area="inventory",
    ),
    EvalCase(
        case_id="transfer_unsupported_discount_request",
        category="transfer",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. I want a 20% "
                    "goodwill discount on order #W5918442."
                ),
            },
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="transfer",
        expected_tool_names=["transfer_to_human_agents"],
        expected_assistant_contains="YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.",
        subset="generalized_mvp",
        capability="unsupported_request",
        policy_area="transfer",
    ),
    EvalCase(
        case_id="deny_modify_address_confirmation",
        category="confirmation",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is sofia.rossi2645@example.com. Change my default "
                    "address to 12 Oak St, Austin, TX, USA, 78701."
                ),
            },
            {"role": "user", "content": "no"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="modify_user_address",
        expected_confirmation_status="denied",
        expected_no_write=True,
        expected_assistant_contains="No changes were made",
        subset="generalized_mvp",
        capability="modify_user_address",
        policy_area="confirmation",
    ),
]

GENERALIZED_MVP_CASES: List[EvalCase] = [
    *[_case_for_subset(case, "generalized_mvp") for case in CURATED_MVP_CASES],
    *PHASE5_NEW_CASES,
]


SYNTHETIC_SEEDED_V1_CASES: List[EvalCase] = [
    EvalCase(
        case_id="synthetic_shipping_express_success",
        category="modify_shipping",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is ruth.williams2@example.com. "
                    "I want to upgrade the shipping on my order "
                    "#W1004 to express."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="U2",
        expected_intent="modify_shipping_method",
        order_id="#W1004",
        expected_write_lock="order:#W1004:modify_shipping_method",
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_pending_order_shipping_method"],
        subset="synthetic_seeded_v1",
        capability="modify_shipping_method",
        policy_area="shipping",
    ),
    EvalCase(
        case_id="synthetic_shipping_overnight_gift_card_insufficient",
        category="modify_shipping",
        messages=[
            {
                "role": "user",
                "content": (
                    "My name is Ruth Williams and my zip is 80855. "
                    "I want overnight shipping for my order #W1004. "
                    "Use my gift card to pay."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="U2",
        expected_intent="modify_shipping_method",
        order_id="#W1004",
        expected_write_lock="order:#W1004:modify_shipping_method",
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_pending_order_shipping_method"],
        subset="synthetic_seeded_v1",
        capability="modify_shipping_method",
        policy_area="shipping",
    ),
    EvalCase(
        case_id="synthetic_shipping_processed_order_block",
        category="modify_shipping",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is ruth.williams2@example.com. "
                    "Change shipping on order #W1028 to express."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="U2",
        expected_intent="modify_shipping_method",
        order_id="#W1028",
        expected_guard_block_reason="non_pending_order_cannot_be_modified",
        expected_no_write=True,
        expected_confirmation_status="confirmed",
        subset="synthetic_seeded_v1",
        capability="modify_shipping_method",
        policy_area="shipping",
    ),
    EvalCase(
        case_id="synthetic_shipping_same_method_block",
        category="modify_shipping",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is ruth.williams2@example.com. "
                    "Change shipping on #W1004 to standard."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="U2",
        expected_intent="modify_shipping_method",
        order_id="#W1004",
        expected_guard_block_reason="same_shipping_method",
        expected_no_write=True,
        expected_confirmation_status="confirmed",
        subset="synthetic_seeded_v1",
        capability="modify_shipping_method",
        policy_area="shipping",
    ),
    EvalCase(
        case_id="synthetic_shipping_unknown_method_block",
        category="modify_shipping",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is ruth.williams2@example.com. "
                    "I need drone delivery for order #W1004."
                ),
            },
            {"role": "user", "content": "confirm"},
        ],
        expected_user_id="U2",
        expected_intent="modify_shipping_method",
        order_id="#W1004",
        expected_guard_block_reason="unknown_shipping_method",
        expected_no_write=True,
        expected_confirmation_status="confirmed",
        subset="synthetic_seeded_v1",
        capability="modify_shipping_method",
        policy_area="shipping",
    ),
    EvalCase(
        case_id="synthetic_coupon_refusal_no_write",
        category="transfer",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is ruth.williams2@example.com. "
                    "Can you give me a discount coupon for my next order?"
                ),
            },
        ],
        expected_user_id="U2",
        expected_intent="transfer",
        expected_no_write=True,
        expected_tool_names=["transfer_to_human_agents"],
        subset="synthetic_seeded_v1",
        capability="transfer",
        policy_area="coupon",
    ),
    EvalCase(
        case_id="synthetic_compensation_then_shipping_success",
        category="modify_shipping",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is ruth.williams2@example.com. "
                    "My order #W1004 arrived damaged. "
                    "I want compensation for this."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Fine, then at least upgrade my shipping on #W1004 "
                    "to express so the replacement comes faster."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="U2",
        expected_intent="modify_shipping_method",
        order_id="#W1004",
        expected_write_lock="order:#W1004:modify_shipping_method",
        expected_confirmation_status="confirmed",
        expected_tool_names=[
            "transfer_to_human_agents",
            "modify_pending_order_shipping_method",
        ],
        subset="synthetic_seeded_v1",
        capability="modify_shipping_method",
        policy_area="shipping",
        max_turns=12,
    ),
]


def get_cases(subset: str) -> List[EvalCase]:
    if subset == "curated_mvp":
        return list(CURATED_MVP_CASES)
    if subset == "generalized_mvp":
        return list(GENERALIZED_MVP_CASES)
    if subset == "synthetic_seeded_v1":
        return list(SYNTHETIC_SEEDED_V1_CASES)
    if subset == "generalization":
        from app.synthetic.families import build_generalization_cases

        return build_generalization_cases()
    if subset == "generalization_exploratory":
        from app.synthetic.families import build_generalization_exploratory_cases

        return build_generalization_exploratory_cases()
    if subset == "tau_retail_smoke":
        from app.config import resolve_config
        from app.eval.tau_loader import get_tau_smoke_cases

        return get_tau_smoke_cases(resolve_config())
    if subset == "tau_retail_supported":
        from app.config import resolve_config
        from app.eval.tau_loader import get_tau_supported_cases

        return get_tau_supported_cases(resolve_config())
    if subset == "tau_retail_train":
        from app.config import resolve_config
        from app.eval.tau_loader import get_tau_train_cases

        return get_tau_train_cases(resolve_config())
    if subset == "tau_retail_test":
        from app.config import resolve_config
        from app.eval.tau_loader import get_tau_test_cases

        return get_tau_test_cases(resolve_config())
    raise ValueError("unsupported subset: " + subset)
