"""Tests for tau3 task loader and EvalCase converter."""

from pathlib import Path

from app.eval.tau_loader import (
    convert_task_to_eval_case,
    load_tau_tasks_from_dir,
    get_tau_smoke_cases,
    _build_user_message,
    _derive_db_assertions,
    _primary_capability_from_actions,
)

# Sample tau3 task matching the real format
SAMPLE_TASK = {
    "id": 0,
    "user_scenario": {
        "persona": None,
        "instructions": {
            "task_instructions": "You are detail-oriented.",
            "domain": "retail",
            "reason_for_call": (
                "You received your order #W2378156 and wish to exchange "
                "the mechanical keyboard for the same one but with clicky switches."
            ),
            "known_info": "You are Yusuf Rossi in zip code 19122.",
            "unknown_info": "You do not remember your email address.",
        },
    },
    "initial_state": None,
    "evaluation_criteria": {
        "actions": [
            {
                "action_id": "0_0",
                "name": "find_user_id_by_name_zip",
                "arguments": {"first_name": "Yusuf", "last_name": "Rossi", "zip": "19122"},
                "info": None,
            },
            {
                "action_id": "0_1",
                "name": "get_order_details",
                "arguments": {"order_id": "#W2378156"},
                "info": None,
            },
            {
                "action_id": "0_2",
                "name": "exchange_delivered_order_items",
                "arguments": {
                    "order_id": "#W2378156",
                    "item_ids": ["1151293680", "4983901480"],
                    "new_item_ids": ["7706410293", "7747408585"],
                    "payment_method_id": "credit_card_9513926",
                },
                "info": None,
            },
        ],
        "communicate_info": [],
        "nl_assertions": None,
        "reward_basis": ["DB", "NL_ASSERTION"],
    },
}

SAMPLE_TASK_NO_WRITE = {
    "id": 10,
    "user_scenario": {
        "persona": None,
        "instructions": {
            "task_instructions": "",
            "domain": "retail",
            "reason_for_call": "You want to check the status of order #W1234567.",
            "known_info": "Your email is test@example.com.",
            "unknown_info": "",
        },
    },
    "initial_state": None,
    "evaluation_criteria": {
        "actions": [
            {
                "action_id": "10_0",
                "name": "find_user_id_by_email",
                "arguments": {"email": "test@example.com"},
                "info": None,
            },
            {
                "action_id": "10_1",
                "name": "get_order_details",
                "arguments": {"order_id": "#W1234567"},
                "info": None,
            },
        ],
        "communicate_info": [],
        "nl_assertions": None,
        "reward_basis": ["DB"],
    },
}


class TestBuildUserMessage:
    def test_builds_message_from_all_fields(self):
        """_build_user_message concatenates reason + known + unknown info."""
        msg = _build_user_message(SAMPLE_TASK)
        assert "exchange" in msg.lower()
        assert "Yusuf Rossi" in msg
        assert "do not remember your email" in msg

    def test_handles_empty_unknown_info(self):
        """_build_user_message works when unknown_info is empty."""
        msg = _build_user_message(SAMPLE_TASK_NO_WRITE)
        assert "check the status" in msg.lower()
        assert "test@example.com" in msg


class TestDeriveDbAssertions:
    def test_exchange_derives_item_assertion(self):
        """_derive_db_assertions for exchange returns expected item ids."""
        result = _derive_db_assertions(SAMPLE_TASK)
        assert result is not None  # exchange IS a write
        assert "new_item_ids" in result

    def test_no_write_task_returns_empty(self):
        """_derive_db_assertions returns empty for read-only tasks."""
        result = _derive_db_assertions(SAMPLE_TASK_NO_WRITE)
        assert result == {}


class TestConvertTaskToEvalCase:
    def test_converts_write_task(self):
        """convert_task_to_eval_case produces valid EvalCase for write task."""
        case = convert_task_to_eval_case(SAMPLE_TASK, "tau_retail_smoke")
        assert case is not None
        assert case.case_id == "tau_0"
        assert case.subset == "tau_retail_smoke"
        assert len(case.messages) == 1
        assert case.messages[0]["role"] == "user"
        assert any("exchange" in name for name in case.expected_tool_names)
        assert "get_order_details" in case.expected_tool_names
        assert case.expected_intent in ("exchange", "exchange_items")
        assert case.max_turns == 5

    def test_converts_read_only_task(self):
        """convert_task_to_eval_case sets expected_no_write for read-only tasks."""
        case = convert_task_to_eval_case(SAMPLE_TASK_NO_WRITE, "tau_retail_smoke")
        assert case is not None
        assert case.case_id == "tau_10"
        assert case.expected_no_write is True
        assert "get_order_details" in case.expected_tool_names
