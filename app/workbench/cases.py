from __future__ import annotations

from typing import Any, Dict

from app.eval.cases import EvalCase, get_cases

DEMO_CASE_IDS = [
    "auth_name_zip_lookup_order",
    "cancel_pending_order",
    "return_delivered_order_item",
    "modify_pending_order_items_success",
    "modify_pending_order_payment_success",
    "synthetic_shipping_express_success",
    "block_wrong_user_order_access",
    "block_item_product_mismatch",
    "block_payment_insufficient_gift_card",
    "deny_cancel_confirmation",
    "transfer_to_human",
]

CASE_GROUPS = [
    {
        "key": "auth",
        "label": "身份认证",
        "emoji": "🔐",
        "case_ids": ["auth_name_zip_lookup_order"],
    },
    {
        "key": "success",
        "label": "成功写操作",
        "emoji": "✅",
        "case_ids": [
            "cancel_pending_order",
            "return_delivered_order_item",
            "modify_pending_order_items_success",
            "modify_pending_order_payment_success",
        ],
    },
    {
        "key": "blocked",
        "label": "写保护阻止",
        "emoji": "🛡️",
        "case_ids": [
            "block_wrong_user_order_access",
            "block_item_product_mismatch",
            "block_payment_insufficient_gift_card",
        ],
    },
    {
        "key": "confirmation",
        "label": "用户确认流程",
        "emoji": "🔄",
        "case_ids": ["deny_cancel_confirmation"],
    },
    {
        "key": "transfer",
        "label": "边界能力",
        "emoji": "📞",
        "case_ids": ["transfer_to_human"],
    },
    {
        "key": "synthetic",
        "label": "Synthetic 世界",
        "emoji": "🧪",
        "case_ids": ["synthetic_shipping_express_success"],
    },
]

CASE_TITLES = {
    "lookup_pending_order": "查询待处理订单",
    "cancel_pending_order": "取消待处理订单",
    "modify_pending_order_address": "修改待处理订单地址",
    "return_delivered_order_item": "退回已送达商品",
    "exchange_delivered_order_item": "换货已送达商品",
    "transfer_to_human": "转接人工客服",
    "deny_cancel_confirmation": "拒绝取消确认",
    "changed_confirmation_discards_pending_action": ("变更确认并丢弃待处理操作"),
    "block_cancel_processed_order": "阻止取消已处理订单",
    "block_return_pending_order": "阻止退回待处理订单",
    "block_wrong_user_order_access": "阻止访问他人订单",
    "auth_name_zip_lookup_order": "姓名加邮编认证查询订单",
    "modify_pending_order_items_success": "修改待处理订单商品",
    "modify_pending_order_payment_success": "修改待处理订单支付方式",
    "modify_user_default_address_success": "修改用户默认地址",
    "multi_item_return_success": "多件商品退货",
    "block_item_product_mismatch": "阻止跨商品替换",
    "block_item_unavailable": "阻止替换缺货商品",
    "block_payment_not_owned": "阻止使用他人支付方式",
    "block_payment_insufficient_gift_card": "阻止余额不足礼品卡支付",
    "block_same_payment_method": "阻止重复支付方式",
    "block_modify_items_non_pending_order": "阻止修改非待处理订单商品",
    "block_modify_payment_processed_order": "阻止修改已处理订单支付",
    "block_exchange_product_mismatch": "阻止跨商品换货",
    "block_exchange_unavailable_replacement": "阻止换货缺货商品",
    "transfer_unsupported_discount_request": "转接折扣请求至人工",
    "deny_modify_payment_confirmation": "拒绝支付方式修改确认",
    "changed_modify_items_confirmation": "变更商品修改确认",
    "deny_modify_address_confirmation": "拒绝地址修改确认",
    "synthetic_shipping_express_success": "Synthetic 世界：升级配送方式",
}


def build_case_catalog(subset: str = "curated_mvp") -> Dict[str, Any]:
    cases = get_cases(subset)
    # Also load synthetic cases
    try:
        synthetic_cases = get_cases("synthetic_seeded_v1")
    except Exception:
        synthetic_cases = []
    all_cases_list = list(cases) + list(synthetic_cases)
    serialized = [_serialize_case(case) for case in all_cases_list]
    by_id = {case["case_id"]: case for case in serialized}
    demo_cases = [by_id[case_id] for case_id in DEMO_CASE_IDS if case_id in by_id]
    return {
        "subset": subset,
        "demo_case_ids": list(DEMO_CASE_IDS),
        "demo_cases": demo_cases,
        "all_cases": serialized,
        "groups": CASE_GROUPS,
    }


def get_case_by_id(case_id: str, subset: str = "curated_mvp") -> EvalCase:
    # Try primary subset first
    for case in get_cases(subset):
        if case.case_id == case_id:
            return case
    # Fall back to synthetic subset
    try:
        for case in get_cases("synthetic_seeded_v1"):
            if case.case_id == case_id:
                return case
    except Exception:
        pass
    raise ValueError(f"unknown case: {case_id}")


def _serialize_case(case: EvalCase) -> Dict[str, Any]:
    return {
        "case_id": case.case_id,
        "title": CASE_TITLES.get(case.case_id, case.case_id.replace("_", " ").title()),
        "category": case.category,
        "message_count": len(case.messages),
        "messages": [dict(message) for message in case.messages],
        "expected_user_id": case.expected_user_id,
        "expected_intent": case.expected_intent,
        "expected_order_status": case.expected_order_status,
        "expected_confirmation_status": case.expected_confirmation_status,
        "expected_guard_block_reason": case.expected_guard_block_reason,
        "expected_no_write": case.expected_no_write,
        "expected_tool_names": list(case.expected_tool_names),
        "expected_assistant_contains": case.expected_assistant_contains,
        "subset": case.subset,
        "capability": case.capability,
        "policy_area": case.policy_area,
        "expected_db_assertions": dict(case.expected_db_assertions),
        "expected_tool_sequence": list(case.expected_tool_sequence),
    }
