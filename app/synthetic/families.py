# app/synthetic/families.py
"""Scenario family definitions and variant generation for Phase 8a generalization eval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from app.eval.cases import EvalCase
from app.synthetic.generator import SyntheticDBGenerator
from app.synthetic.oracle import (
    derive_oracle,
    select_entity_for_variant,
)


@dataclass
class FamilyVariant:
    """A single test variant within a scenario family."""

    variant_id: str
    variant_type: str
    seed: int
    capability: str
    policy_area: str
    category: str
    max_turns: int = 8

    def build_messages(self, entities: dict) -> List[Dict[str, str]]:
        """Assemble conversation messages based on variant type and selected entities."""
        user = entities["user"]
        order = entities.get("order")
        email = user["email"]
        variant_type = self.variant_type

        # ── cancel family ──
        if variant_type == "cancel_success":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. Cancel order {order['order_id']} "
                        f"because no longer needed."
                    ),
                },
                {"role": "user", "content": "yes"},
            ]
        if variant_type == "cancel_block_nonpending":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. Cancel order {order['order_id']} "
                        f"because no longer needed."
                    ),
                },
                {"role": "user", "content": "yes"},
            ]
        if variant_type == "cancel_block_wrong_user":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. Cancel order {order['order_id']} "
                        f"because ordered by mistake."
                    ),
                },
            ]

        # ── shipping family ──
        if variant_type == "shipping_success_express":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. I want to upgrade the shipping "
                        f"on my order {order['order_id']} to express."
                    ),
                },
                {"role": "user", "content": "yes"},
            ]
        if variant_type == "shipping_success_overnight":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. Change shipping on "
                        f"{order['order_id']} to overnight. Use my credit card."
                    ),
                },
                {"role": "user", "content": "yes"},
            ]
        if variant_type == "shipping_block_same_method":
            current_method = order.get("shipping_method", "standard")
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. Change shipping on "
                        f"{order['order_id']} to {current_method}."
                    ),
                },
                {"role": "user", "content": "yes"},
            ]
        if variant_type == "shipping_block_nonpending":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. Change shipping on "
                        f"{order['order_id']} to express."
                    ),
                },
                {"role": "user", "content": "yes"},
            ]
        if variant_type == "shipping_block_unknown_method":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. I need drone delivery "
                        f"for order {order['order_id']}."
                    ),
                },
                {"role": "user", "content": "confirm"},
            ]

        # ── coupon family ──
        if variant_type == "coupon_transfer_no_write":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. Can you give me a discount "
                        f"coupon for my next order?"
                    ),
                },
            ]

        raise ValueError(f"Unknown variant_type: {variant_type}")

    def to_eval_case(self) -> EvalCase:
        """Generate synthetic world, select entities, build messages, derive oracle -> EvalCase."""
        world = SyntheticDBGenerator.from_seed(self.seed)
        entities = select_entity_for_variant(world, self.variant_type)
        messages = self.build_messages(entities)
        oracle = derive_oracle(world, entities, self.variant_type)

        return EvalCase(
            case_id=self.variant_id,
            category=self.category,
            messages=messages,
            expected_user_id=oracle.expected_user_id,
            expected_intent=oracle.expected_intent,
            order_id=oracle.order_id,
            expected_write_lock=oracle.expected_write_lock,
            expected_order_status=oracle.expected_order_status,
            expected_confirmation_status=oracle.expected_confirmation_status,
            expected_guard_block_reason=oracle.expected_guard_block_reason,
            expected_no_write=oracle.expected_no_write,
            expected_tool_names=oracle.expected_tool_names,
            expected_tool_sequence=oracle.expected_tool_sequence,
            expected_db_assertions=oracle.expected_db_assertions,
            max_turns=self.max_turns,
            subset="generalization",
            capability=self.capability,
            policy_area=self.policy_area,
            seed=self.seed,
        )


@dataclass
class ScenarioFamily:
    """A named group of related scenario variants (e.g., cancel, modify_shipping)."""

    name: str
    variants: List[FamilyVariant]


# ── Three Family Definitions ──

CANCEL_FAMILY = ScenarioFamily(
    name="cancel",
    variants=[
        FamilyVariant(
            "cancel_success_s100",
            "cancel_success",
            100,
            "cancel_order",
            "order_lifecycle",
            "cancel",
        ),
        FamilyVariant(
            "cancel_success_s101",
            "cancel_success",
            101,
            "cancel_order",
            "order_lifecycle",
            "cancel",
        ),
        FamilyVariant(
            "cancel_success_s102",
            "cancel_success",
            102,
            "cancel_order",
            "order_lifecycle",
            "cancel",
        ),
        FamilyVariant(
            "cancel_block_nonpending_s103",
            "cancel_block_nonpending",
            103,
            "cancel_order",
            "order_status",
            "guard",
        ),
        FamilyVariant(
            "cancel_block_wrong_user_s104",
            "cancel_block_wrong_user",
            104,
            "cancel_order",
            "authentication",
            "guard",
        ),
    ],
)

MODIFY_SHIPPING_FAMILY = ScenarioFamily(
    name="modify_shipping",
    variants=[
        FamilyVariant(
            "shipping_express_s200",
            "shipping_success_express",
            200,
            "modify_shipping_method",
            "shipping",
            "modify_shipping",
        ),
        FamilyVariant(
            "shipping_overnight_s201",
            "shipping_success_overnight",
            201,
            "modify_shipping_method",
            "shipping",
            "modify_shipping",
        ),
        FamilyVariant(
            "shipping_block_same_s202",
            "shipping_block_same_method",
            202,
            "modify_shipping_method",
            "shipping",
            "modify_shipping",
        ),
        FamilyVariant(
            "shipping_block_nonpending_s203",
            "shipping_block_nonpending",
            203,
            "modify_shipping_method",
            "order_status",
            "modify_shipping",
        ),
        FamilyVariant(
            "shipping_block_unknown_s204",
            "shipping_block_unknown_method",
            204,
            "modify_shipping_method",
            "shipping",
            "modify_shipping",
        ),
    ],
)

COUPON_REFUSAL_FAMILY = ScenarioFamily(
    name="coupon_refusal",
    variants=[
        FamilyVariant(
            "coupon_transfer_s300",
            "coupon_transfer_no_write",
            300,
            "transfer",
            "coupon",
            "transfer",
        ),
        FamilyVariant(
            "coupon_transfer_s301",
            "coupon_transfer_no_write",
            301,
            "transfer",
            "coupon",
            "transfer",
        ),
        FamilyVariant(
            "coupon_transfer_s302",
            "coupon_transfer_no_write",
            302,
            "transfer",
            "coupon",
            "transfer",
        ),
        FamilyVariant(
            "coupon_transfer_s303",
            "coupon_transfer_no_write",
            303,
            "transfer",
            "coupon",
            "transfer",
        ),
        FamilyVariant(
            "coupon_transfer_s304",
            "coupon_transfer_no_write",
            304,
            "transfer",
            "coupon",
            "transfer",
        ),
    ],
)

ALL_FAMILIES = [CANCEL_FAMILY, MODIFY_SHIPPING_FAMILY, COUPON_REFUSAL_FAMILY]


def build_generalization_cases() -> List[EvalCase]:
    """Build EvalCase instances for all families and all variants."""
    cases: List[EvalCase] = []
    for family in ALL_FAMILIES:
        for variant in family.variants:
            cases.append(variant.to_eval_case())
    return cases
