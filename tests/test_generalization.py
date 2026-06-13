# tests/test_generalization.py
import pytest

from app.synthetic.generator import SyntheticDBGenerator
from app.synthetic.oracle import derive_oracle


def test_derive_cancel_success_oracle():
    world = SyntheticDBGenerator.from_seed(100)
    pending_order = None
    for oid, order in world["orders"].items():
        if order["status"] == "pending":
            pending_order = order
            break
    assert pending_order is not None, "seed 100 must have at least one pending order"

    entities = {
        "order": pending_order,
        "user": world["users"][pending_order["user_id"]],
    }
    oracle = derive_oracle(world, entities, "cancel_success")

    assert oracle.expected_intent == "cancel_order"
    assert oracle.order_id == pending_order["order_id"]
    assert oracle.expected_user_id == pending_order["user_id"]
    assert oracle.expected_order_status == "cancelled"
    assert oracle.expected_write_lock == f"order:{pending_order['order_id']}:cancel"
    assert oracle.expected_confirmation_status == "confirmed"
    assert oracle.expected_no_write is False
    assert "cancel_pending_order" in oracle.expected_tool_names


def test_derive_cancel_block_nonpending_oracle():
    world = SyntheticDBGenerator.from_seed(103)
    non_pending = None
    for oid, order in world["orders"].items():
        if order["status"] != "pending":
            non_pending = order
            break
    assert non_pending is not None

    entities = {"order": non_pending, "user": world["users"][non_pending["user_id"]]}
    oracle = derive_oracle(world, entities, "cancel_block_nonpending")

    assert oracle.expected_intent == "cancel_order"
    assert oracle.expected_guard_block_reason == "non_pending_order_cannot_be_cancelled"
    assert oracle.expected_no_write is True
    assert oracle.expected_confirmation_status == "confirmed"


def test_derive_coupon_transfer_oracle():
    world = SyntheticDBGenerator.from_seed(300)
    user = list(world["users"].values())[0]
    entities = {"user": user}
    oracle = derive_oracle(world, entities, "coupon_transfer_no_write")

    assert oracle.expected_intent == "transfer"
    assert oracle.expected_no_write is True
    assert "transfer_to_human_agents" in oracle.expected_tool_names


def test_derive_shipping_success_express_oracle():
    world = SyntheticDBGenerator.from_seed(200)
    pending_order = None
    for oid, order in world["orders"].items():
        if order["status"] == "pending" and order.get("shipping_method") != "express":
            pending_order = order
            break
    assert pending_order is not None

    entities = {
        "order": pending_order,
        "user": world["users"][pending_order["user_id"]],
        "target_method": "express",
    }
    oracle = derive_oracle(world, entities, "shipping_success_express")

    assert oracle.expected_intent == "modify_shipping_method"
    assert (
        oracle.expected_write_lock
        == f"order:{pending_order['order_id']}:modify_shipping_method"
    )
    assert oracle.expected_no_write is False


def test_derive_unknown_variant_raises():
    world = SyntheticDBGenerator.from_seed(42)
    with pytest.raises(ValueError, match="Unknown variant_type"):
        derive_oracle(world, {}, "nonexistent_variant")


def test_language_variants_include_reproducible_base_l1_l2_and_l3():
    from app.synthetic.language_variation import build_language_variants
    from app.synthetic.oracle import select_entity_for_variant

    world = SyntheticDBGenerator.from_seed(100)
    entities = select_entity_for_variant(world, "cancel_success")
    base_messages = [
        {
            "role": "user",
            "content": (
                f"My email is {entities['user']['email']}. Cancel order "
                f"{entities['order']['order_id']} because no longer needed."
            ),
        },
        {"role": "user", "content": "yes"},
    ]

    first = build_language_variants(base_messages, "cancel_success", entities)
    second = build_language_variants(base_messages, "cancel_success", entities)

    assert first == second
    assert [variant.level for variant in first] == ["base", "L1", "L2", "L3"]
    assert [variant.suffix for variant in first] == ["", "_l1", "_l2", "_l3"]
    assert first[0].gate is True
    assert first[1].gate is True
    assert first[2].gate is True
    assert first[3].gate is False
    assert "Cancel order" not in first[1].messages[0]["content"]
    assert entities["user"]["email"] in first[2].messages[0]["content"]
    assert entities["order"]["order_id"] in first[3].messages[-2]["content"]


def test_select_pending_order_for_cancel():
    world = SyntheticDBGenerator.from_seed(100)
    from app.synthetic.oracle import select_entity_for_variant

    entities = select_entity_for_variant(world, "cancel_success")
    assert entities["order"]["status"] == "pending"
    assert entities["user"]["user_id"] == entities["order"]["user_id"]


def test_select_non_pending_order():
    world = SyntheticDBGenerator.from_seed(103)
    from app.synthetic.oracle import select_entity_for_variant

    entities = select_entity_for_variant(world, "cancel_block_nonpending")
    assert entities["order"]["status"] != "pending"


def test_select_wrong_user_order():
    world = SyntheticDBGenerator.from_seed(104)
    from app.synthetic.oracle import select_entity_for_variant

    entities = select_entity_for_variant(world, "cancel_block_wrong_user")
    # user and order should belong to different people
    assert entities["user"]["user_id"] != entities["order"]["user_id"]


def test_select_any_user_with_valid_email():
    world = SyntheticDBGenerator.from_seed(300)
    from app.synthetic.oracle import select_entity_for_variant

    entities = select_entity_for_variant(world, "coupon_transfer_no_write")
    assert "@" in entities["user"]["email"]


def test_select_pending_order_for_shipping():
    world = SyntheticDBGenerator.from_seed(200)
    from app.synthetic.oracle import select_entity_for_variant

    entities = select_entity_for_variant(world, "shipping_success_express")
    assert entities["order"]["status"] == "pending"
    assert entities["order"].get("shipping_method") != "express"


def test_select_shipping_block_nonpending():
    world = SyntheticDBGenerator.from_seed(203)
    from app.synthetic.oracle import select_entity_for_variant

    entities = select_entity_for_variant(world, "shipping_block_nonpending")
    assert entities["order"]["status"] != "pending"


# ── Family / build_generalization_cases tests ──


def test_all_15_variants_generate_without_error():
    from app.synthetic.families import ALL_FAMILIES

    for family in ALL_FAMILIES:
        for variant in family.variants:
            case = variant.to_eval_case()
            assert case.case_id == variant.variant_id
            assert case.subset == "generalization"
            assert case.expected_user_id
            assert case.expected_intent
            assert len(case.messages) >= 1


def test_cancel_family_has_5_variants():
    from app.synthetic.families import CANCEL_FAMILY

    assert len(CANCEL_FAMILY.variants) == 5


def test_all_families_total_15_variants():
    from app.synthetic.families import ALL_FAMILIES

    total = sum(len(f.variants) for f in ALL_FAMILIES)
    assert total == 15


def test_generated_case_is_reproducible():
    from app.synthetic.families import FamilyVariant

    v = FamilyVariant(
        "test_s100", "cancel_success", 100, "cancel_order", "order_lifecycle", "cancel"
    )
    case1 = v.to_eval_case()
    case2 = v.to_eval_case()
    assert case1.messages == case2.messages
    assert case1.expected_user_id == case2.expected_user_id
    assert case1.order_id == case2.order_id


def test_no_write_cases_have_no_write_flag():
    from app.synthetic.families import COUPON_REFUSAL_FAMILY

    for variant in COUPON_REFUSAL_FAMILY.variants:
        case = variant.to_eval_case()
        assert case.expected_no_write is True, (
            f"{variant.variant_id} should be no-write"
        )


def test_cancel_success_cases_expect_cancelled():
    from app.synthetic.families import CANCEL_FAMILY

    for variant in CANCEL_FAMILY.variants:
        if "success" in variant.variant_type:
            case = variant.to_eval_case()
            assert case.expected_order_status == "cancelled"


def test_generalization_cases_include_base_l1_l2_gate_variants():
    from app.eval.cases import get_cases

    cases = get_cases("generalization")
    levels = {case.language_variation_level for case in cases}

    assert len(cases) == 45
    assert levels == {"base", "L1", "L2"}
    assert all(case.scenario_family for case in cases)
    assert all(case.variant_type for case in cases)
    assert all(case.seed is not None for case in cases)


def test_l3_variants_are_exploratory_only():
    from app.eval.cases import get_cases

    gate_ids = {case.case_id for case in get_cases("generalization")}
    exploratory = get_cases("generalization_exploratory")

    assert exploratory
    assert {case.language_variation_level for case in exploratory} == {"L3"}
    assert all(case.subset == "generalization_exploratory" for case in exploratory)
    assert not gate_ids.intersection({case.case_id for case in exploratory})
