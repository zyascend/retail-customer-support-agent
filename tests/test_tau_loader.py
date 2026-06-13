"""Tests for tau3 task loader and EvalCase converter."""

from app.eval.cases import EvalCase
from app.eval.runner import classify_failure
from app.eval.tau_loader import (
    _build_user_message,
    _derive_db_assertions,
    convert_task_to_eval_case,
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
        assert "don't remember my email" in msg

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


class TestTauLooseEvaluation:
    def test_tau_subset_skips_user_id_check(self):
        """For tau subsets, auth mismatch does not trigger auth_failure."""
        result = classify_failure(
            case=_make_tau_case(expected_user_id=""),
            authenticated_user_id="some_other_user",
            final_intent="lookup",
            write_locks=[],
            actual_order_status=None,
            assistant_messages=["Here is your order status."],
            tool_names=["find_user_id_by_email", "get_order_details"],
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="",
            db_assertion_failures=None,
        )
        # Should NOT be auth_failure for tau subsets
        assert result != "auth_failure"

    def test_tau_subset_still_checks_tools(self):
        """For tau subsets, missing core tools still triggers wrong_tool."""
        result = classify_failure(
            case=_make_tau_case(expected_tool_names=["get_order_details"]),
            authenticated_user_id="",
            final_intent="lookup",
            write_locks=[],
            actual_order_status=None,
            assistant_messages=["Sorry, I cannot help."],
            tool_names=[],  # nothing called
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="",
            db_assertion_failures=None,
        )
        assert result == "wrong_tool"

    def test_tau_subset_still_checks_unexpected_mutation(self):
        """For tau subsets, no-write tasks with write locks trigger unexpected_mutation."""
        result = classify_failure(
            case=_make_tau_case(expected_no_write=True),
            authenticated_user_id="",
            final_intent="lookup",
            actual_order_status=None,
            write_locks=["order:123:cancel"],  # unexpected write!
            assistant_messages=["Done."],
            tool_names=["cancel_pending_order"],
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="",
            db_assertion_failures=None,
        )
        assert result == "unexpected_mutation"


def _make_tau_case(**overrides) -> EvalCase:
    """Helper to create a minimal tau EvalCase for testing."""
    from dataclasses import replace

    base = EvalCase(
        case_id="tau_test",
        category="lookup",
        messages=[{"role": "user", "content": "test"}],
        expected_user_id="",
        expected_intent="lookup",
        subset="tau_retail_smoke",
    )
    return replace(base, **overrides)
