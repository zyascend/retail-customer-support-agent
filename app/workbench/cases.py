from __future__ import annotations

from typing import Any, Dict

from app.eval.cases import EvalCase, get_cases

DEMO_CASE_IDS = [
    "cancel_pending_order",
    "return_delivered_order_item",
    "block_wrong_user_order_access",
    "transfer_to_human",
    "deny_cancel_confirmation",
]

CASE_TITLES = {
    "lookup_pending_order": "查询待处理订单",
    "cancel_pending_order": "取消待处理订单",
    "modify_pending_order_address": "修改待处理订单地址",
    "return_delivered_order_item": "退回已送达商品",
    "exchange_delivered_order_item": "换货已送达商品",
    "transfer_to_human": "转接人工客服",
    "deny_cancel_confirmation": "拒绝取消确认",
    "changed_confirmation_discards_pending_action": (
        "变更确认并丢弃待处理操作"
    ),
    "block_cancel_processed_order": "阻止取消已处理订单",
    "block_return_pending_order": "阻止退回待处理订单",
    "block_wrong_user_order_access": "阻止访问他人订单",
}


def build_case_catalog(subset: str = "curated_mvp") -> Dict[str, Any]:
    cases = get_cases(subset)
    serialized = [_serialize_case(case) for case in cases]
    by_id = {case["case_id"]: case for case in serialized}
    demo_cases = [by_id[case_id] for case_id in DEMO_CASE_IDS if case_id in by_id]
    return {
        "subset": subset,
        "demo_case_ids": list(DEMO_CASE_IDS),
        "demo_cases": demo_cases,
        "all_cases": serialized,
    }


def get_case_by_id(case_id: str, subset: str = "curated_mvp") -> EvalCase:
    for case in get_cases(subset):
        if case.case_id == case_id:
            return case
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
    }
