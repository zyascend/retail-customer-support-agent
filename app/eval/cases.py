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
    expected_db_assertions: Dict[str, object] = field(default_factory=dict)
    expected_tool_sequence: List[str] = field(default_factory=list)


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
                    "My email is sofia.rossi2645@example.com. "
                    "I want a human agent."
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
        expected_db_assertions=dict(case.expected_db_assertions),
        expected_tool_sequence=list(case.expected_tool_sequence),
    )


GENERALIZED_MVP_CASES: List[EvalCase] = [
    _case_for_subset(case, "generalized_mvp") for case in CURATED_MVP_CASES
]


def get_cases(subset: str) -> List[EvalCase]:
    if subset == "curated_mvp":
        return list(CURATED_MVP_CASES)
    if subset == "generalized_mvp":
        return list(GENERALIZED_MVP_CASES)
    raise ValueError("unsupported subset: " + subset)
