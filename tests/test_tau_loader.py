"""Tests for tau3 task loader and EvalCase converter."""

import json
from pathlib import Path

from app.config import AppConfig
from app.eval.cases import EvalCase
from app.eval.runner import classify_failure
from app.eval.tau_loader import (
    _build_user_message,
    _derive_db_assertions,
    convert_task_to_eval_case,
    get_phase12_candidate_cases,
    get_phase12_nl_evidence_cases,
    get_phase12_schema_ready_cases,
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
        assert "my zip code is 19122" in msg
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


def test_get_phase12_candidate_cases_returns_safe_partial_candidates(tmp_path):
    retail_dir = tmp_path / "domains" / "retail"
    retail_dir.mkdir(parents=True)
    tasks = [
        {
            "id": 1,
            "user_scenario": {
                "instructions": {
                    "reason_for_call": "You want to check the status of order #W123.",
                    "known_info": "Your email is test@example.com.",
                    "unknown_info": "",
                }
            },
            "evaluation_criteria": {
                "actions": [
                    {
                        "name": "get_order_details",
                        "arguments": {"order_id": "#W123"},
                    }
                ],
                "nl_assertions": ["Agent should tell the user the status."],
                "reward_basis": ["DB", "NL_ASSERTION"],
            },
        }
    ]
    (retail_dir / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
    (retail_dir / "split_tasks.json").write_text(
        json.dumps({"train": ["1"], "test": [], "base": ["1"]}),
        encoding="utf-8",
    )

    cases = get_phase12_candidate_cases(_config(tmp_path), limit=1)

    assert [case.case_id for case in cases] == ["tau_1"]
    assert cases[0].subset == "tau_phase12_candidates"


def test_get_phase12_schema_ready_cases_returns_auxiliary_only_candidates(tmp_path):
    retail_dir = tmp_path / "domains" / "retail"
    retail_dir.mkdir(parents=True)
    tasks = [
        {
            "id": 49,
            "user_scenario": {
                "instructions": {
                    "reason_for_call": "You want to exchange an item and know the price difference.",
                    "known_info": "Your email is test@example.com.",
                    "unknown_info": "",
                }
            },
            "evaluation_criteria": {
                "actions": [
                    {"name": "calculate", "arguments": {"expression": "12.00 - 10.00"}},
                    {
                        "name": "exchange_delivered_order_items",
                        "arguments": {
                            "order_id": "#W123",
                            "item_ids": ["111"],
                            "new_item_ids": ["222"],
                            "payment_method_id": "credit_card_123",
                        },
                    },
                ],
                "nl_assertions": None,
                "reward_basis": ["DB"],
            },
        },
        {
            "id": 50,
            "user_scenario": {
                "instructions": {
                    "reason_for_call": "You want to calculate a refund and hear the amount.",
                    "known_info": "Your email is test@example.com.",
                    "unknown_info": "",
                }
            },
            "evaluation_criteria": {
                "actions": [{"name": "calculate", "arguments": {"expression": "5 + 2"}}],
                "nl_assertions": ["Agent should tell the user the amount."],
                "reward_basis": ["DB", "NL_ASSERTION"],
            },
        },
    ]
    (retail_dir / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
    (retail_dir / "split_tasks.json").write_text(
        json.dumps({"train": ["49", "50"], "test": [], "base": ["49", "50"]}),
        encoding="utf-8",
    )

    cases = get_phase12_schema_ready_cases(_config(tmp_path), limit=10)

    assert [case.case_id for case in cases] == ["tau_49"]
    assert cases[0].subset == "tau_phase12_schema_ready"
    assert cases[0].expected_tool_names == [
        "calculate",
        "exchange_delivered_order_items",
    ]


def test_get_phase12_nl_evidence_cases_requires_extracted_response_fragment(tmp_path):
    retail_dir = tmp_path / "domains" / "retail"
    retail_dir.mkdir(parents=True)
    tasks = [
        {
            "id": 16,
            "user_scenario": {
                "instructions": {
                    "reason_for_call": (
                        "You want to return several items and know the total refund."
                    ),
                    "known_info": "You are Fatima Johnson in zipcode 78712.",
                    "unknown_info": "",
                }
            },
            "evaluation_criteria": {
                "actions": [
                    {"name": "calculate", "arguments": {"expression": "1 + 2"}},
                    {
                        "name": "return_delivered_order_items",
                        "arguments": {
                            "order_id": "#W123",
                            "item_ids": ["111"],
                            "payment_method_id": "paypal_123",
                        },
                    },
                ],
                "nl_assertions": [
                    "Agent should tell the user the total refund amount is $8,276.23."
                ],
                "reward_basis": ["DB", "NL_ASSERTION"],
            },
        },
        {
            "id": 17,
            "user_scenario": {
                "instructions": {
                    "reason_for_call": "You want to calculate something.",
                    "known_info": "Your email is test@example.com.",
                    "unknown_info": "",
                }
            },
            "evaluation_criteria": {
                "actions": [{"name": "calculate", "arguments": {"expression": "5 + 2"}}],
                "nl_assertions": ["Agent should answer politely."],
                "reward_basis": ["DB", "NL_ASSERTION"],
            },
        },
    ]
    (retail_dir / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
    (retail_dir / "split_tasks.json").write_text(
        json.dumps({"train": ["16", "17"], "test": [], "base": ["16", "17"]}),
        encoding="utf-8",
    )

    cases = get_phase12_nl_evidence_cases(_config(tmp_path), limit=10)

    assert [case.case_id for case in cases] == ["tau_16"]
    assert cases[0].subset == "tau_phase12_nl_evidence"
    assert cases[0].expected_assistant_contains == "$8,276.23"
    assert cases[0].max_turns == 10


def test_get_cases_supports_phase12_candidate_subset(monkeypatch):
    from app.eval.cases import get_cases

    sentinel_config = object()
    expected_cases = [
        EvalCase(
            case_id="tau_1",
            category="lookup",
            messages=[{"role": "user", "content": "test"}],
            expected_user_id="",
            expected_intent="lookup",
            subset="tau_phase12_candidates",
        )
    ]

    monkeypatch.setattr("app.config.resolve_config", lambda: sentinel_config)

    def fake_get_phase12_candidate_cases(config):
        assert config is sentinel_config
        return expected_cases

    monkeypatch.setattr(
        "app.eval.tau_loader.get_phase12_candidate_cases",
        fake_get_phase12_candidate_cases,
    )

    assert get_cases("tau_phase12_candidates") == expected_cases


def test_get_cases_supports_phase12_schema_ready_subset(monkeypatch):
    from app.eval.cases import get_cases

    sentinel_config = object()
    expected_cases = [
        EvalCase(
            case_id="tau_49",
            category="exchange_items",
            messages=[{"role": "user", "content": "test"}],
            expected_user_id="",
            expected_intent="exchange_items",
            subset="tau_phase12_schema_ready",
        )
    ]

    monkeypatch.setattr("app.config.resolve_config", lambda: sentinel_config)

    def fake_get_phase12_schema_ready_cases(config):
        assert config is sentinel_config
        return expected_cases

    monkeypatch.setattr(
        "app.eval.tau_loader.get_phase12_schema_ready_cases",
        fake_get_phase12_schema_ready_cases,
    )

    assert get_cases("tau_phase12_schema_ready") == expected_cases


def test_get_cases_supports_phase12_nl_evidence_subset(monkeypatch):
    from app.eval.cases import get_cases

    sentinel_config = object()
    expected_cases = [
        EvalCase(
            case_id="tau_16",
            category="return",
            messages=[{"role": "user", "content": "test"}],
            expected_user_id="",
            expected_intent="return_items",
            expected_assistant_contains="$8,276.23",
            subset="tau_phase12_nl_evidence",
        )
    ]

    monkeypatch.setattr("app.config.resolve_config", lambda: sentinel_config)

    def fake_get_phase12_nl_evidence_cases(config):
        assert config is sentinel_config
        return expected_cases

    monkeypatch.setattr(
        "app.eval.tau_loader.get_phase12_nl_evidence_cases",
        fake_get_phase12_nl_evidence_cases,
    )

    assert get_cases("tau_phase12_nl_evidence") == expected_cases


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

    def test_phase12_tau_subset_skips_user_id_check(self):
        """Phase 12 tau subsets use the same loose auth handling as tau retail."""
        result = classify_failure(
            case=_make_tau_case(
                expected_user_id="",
                subset="tau_phase12_schema_ready",
            ),
            authenticated_user_id="some_other_user",
            final_intent="lookup",
            write_locks=[],
            actual_order_status=None,
            assistant_messages=["Here is your order status."],
            tool_names=["calculate"],
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="",
            db_assertion_failures=None,
        )

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

    def test_phase12_nl_evidence_subset_checks_response_fragment(self):
        result = classify_failure(
            case=_make_tau_case(
                expected_tool_names=["calculate"],
                expected_assistant_contains="$8,276.23",
                subset="tau_phase12_nl_evidence",
            ),
            authenticated_user_id="",
            final_intent="return_items",
            actual_order_status=None,
            write_locks=[],
            assistant_messages=["The refund has been handled."],
            tool_names=["calculate"],
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="",
            db_assertion_failures=None,
        )
        assert result == "response_mismatch"


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


def _config(root: Path) -> AppConfig:
    return AppConfig(
        tau3_retail_root=root,
        tau2_bench_root=root,
        artifact_dir=root / "artifacts",
        deepseek_api_key="",
        deepseek_base_url="",
        default_agent_model="test",
        agent_llm_timeout_seconds=1.0,
        agent_llm_max_retries=0,
    )


class TestGetTauAllCases:
    """Tests for get_tau_all_cases() — loads all tau tasks including partial."""

    def test_loads_all_tasks_including_partial(self, tmp_path: Path):
        """get_tau_all_cases returns supported AND partial tasks."""
        from app.eval.tau_loader import get_tau_all_cases

        retail_dir = tmp_path / "domains" / "retail"
        retail_dir.mkdir(parents=True)

        tasks = [
            {
                "id": 0,
                "user_scenario": {
                    "instructions": {
                        "reason_for_call": "You want to check order #W123.",
                        "known_info": "Your name is Alice and you live in zip 12345.",
                        "unknown_info": "",
                    }
                },
                "evaluation_criteria": {
                    "actions": [
                        {
                            "action_id": "1",
                            "name": "find_user_id_by_name_zip",
                            "arguments": {"first_name": "Alice", "last_name": "Smith", "zip": "12345"},
                        },
                        {
                            "action_id": "2",
                            "name": "get_order_details",
                            "arguments": {"order_id": "#W123"},
                        },
                    ],
                    "nl_assertions": [],
                },
            },
            {
                "id": 1,
                "user_scenario": {
                    "instructions": {
                        "reason_for_call": "You want to check order #W456 and the agent should say $50.00.",
                        "known_info": "Your name is Bob and you live in zip 67890.",
                        "unknown_info": "",
                    }
                },
                "evaluation_criteria": {
                    "actions": [
                        {
                            "action_id": "1",
                            "name": "find_user_id_by_name_zip",
                            "arguments": {"first_name": "Bob", "last_name": "Jones", "zip": "67890"},
                        },
                        {
                            "action_id": "2",
                            "name": "get_order_details",
                            "arguments": {"order_id": "#W456"},
                        },
                    ],
                    "nl_assertions": ["Agent should tell the user the refund is $50.00."],
                },
            },
        ]

        (retail_dir / "tasks.json").write_text(json.dumps(tasks))
        (retail_dir / "split_tasks.json").write_text(
            json.dumps({"train": ["0", "1"], "test": [], "base": []})
        )

        config = _config(tmp_path)
        cases = get_tau_all_cases(config)

        # Should include both the supported and the partial (NL assertion) task
        assert len(cases) == 2
        case_ids = {c.case_id for c in cases}
        assert "tau_0" in case_ids
        assert "tau_1" in case_ids

        # Partial task should have expected_assistant_contains extracted
        partial_case = next(c for c in cases if c.case_id == "tau_1")
        assert partial_case.expected_assistant_contains == "$50.00"
        assert partial_case.max_turns == 10

    def test_handles_zero_action_task(self, tmp_path: Path):
        """get_tau_all_cases creates a minimal case for zero-action tasks."""
        from app.eval.tau_loader import get_tau_all_cases

        retail_dir = tmp_path / "domains" / "retail"
        retail_dir.mkdir(parents=True)

        tasks = [
            {
                "id": 24,
                "user_scenario": {
                    "instructions": {
                        "reason_for_call": "Some unsupported request.",
                        "known_info": "Your name is Test and you live in zip 00000.",
                        "unknown_info": "",
                    }
                },
                "evaluation_criteria": {
                    "actions": [],
                    "nl_assertions": [],
                },
            },
        ]

        (retail_dir / "tasks.json").write_text(json.dumps(tasks))
        (retail_dir / "split_tasks.json").write_text(
            json.dumps({"train": ["24"], "test": [], "base": []})
        )

        config = _config(tmp_path)
        cases = get_tau_all_cases(config)

        assert len(cases) == 1
        case = cases[0]
        assert case.case_id == "tau_24"
        assert case.expected_no_write is True
        assert case.max_turns == 1
        assert case.subset == "tau_retail_all"

    def test_all_cases_have_tau_retail_all_subset(self, tmp_path: Path):
        """Every case from get_tau_all_cases uses subset='tau_retail_all'."""
        from app.eval.tau_loader import get_tau_all_cases

        retail_dir = tmp_path / "domains" / "retail"
        retail_dir.mkdir(parents=True)

        tasks = [
            {
                "id": 0,
                "user_scenario": {
                    "instructions": {
                        "reason_for_call": "Check order #W1.",
                        "known_info": "Your name is A and you live in zip 11111.",
                        "unknown_info": "",
                    }
                },
                "evaluation_criteria": {
                    "actions": [
                        {
                            "action_id": "1",
                            "name": "find_user_id_by_name_zip",
                            "arguments": {"first_name": "A", "last_name": "B", "zip": "11111"},
                        },
                        {
                            "action_id": "2",
                            "name": "get_order_details",
                            "arguments": {"order_id": "#W1"},
                        },
                    ],
                    "nl_assertions": [],
                },
            },
        ]

        (retail_dir / "tasks.json").write_text(json.dumps(tasks))
        (retail_dir / "split_tasks.json").write_text(
            json.dumps({"train": ["0"], "test": [], "base": []})
        )

        config = _config(tmp_path)
        cases = get_tau_all_cases(config)

        for case in cases:
            assert case.subset == "tau_retail_all", (
                f"Expected tau_retail_all, got {case.subset} for {case.case_id}"
            )


def test_get_cases_supports_tau_retail_all_subset(monkeypatch):
    """get_cases('tau_retail_all') dispatches to get_tau_all_cases."""
    from app.eval import cases as cases_mod
    from app.eval import tau_loader as loader_mod
    from app.config import AppConfig

    called_configs: list[AppConfig] = []

    def fake_get_all(config_):
        called_configs.append(config_)
        return []

    monkeypatch.setattr(loader_mod, "get_tau_all_cases", fake_get_all)

    result = cases_mod.get_cases("tau_retail_all")
    assert isinstance(result, list)
    assert len(called_configs) == 1
