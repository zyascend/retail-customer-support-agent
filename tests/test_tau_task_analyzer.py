"""Tests for tau task analyzer."""

import json
import tempfile
from pathlib import Path

import pytest

from app.analysis.tau_task_analyzer import (
    TaskClassification,
    _resolve_tau3_retail_dir,
    aggregate_by_capability,
    analyze_nl_assertions,
    classify_task,
    compute_task_space_stats,
    load_splits,
    load_tasks,
)
from app.config import AppConfig


def test_load_splits_parses_split_tasks_json():
    """load_splits returns dict with train, test, base keys."""
    with tempfile.TemporaryDirectory() as tmp:
        retail_dir = Path(tmp)
        splits = {"train": ["0", "1"], "test": ["5", "9"], "base": ["0", "1", "5", "9"]}
        (retail_dir / "split_tasks.json").write_text(json.dumps(splits))
        result = load_splits(retail_dir)
        assert result == splits


def test_load_tasks_parses_tasks_json():
    """load_tasks returns list of task dicts."""
    with tempfile.TemporaryDirectory() as tmp:
        retail_dir = Path(tmp)
        tasks = [
            {
                "id": 0,
                "description": {"purpose": "test"},
                "user_scenario": {"persona": None, "instructions": {}},
                "initial_state": None,
                "evaluation_criteria": {
                    "actions": [],
                    "communicate_info": [],
                    "nl_assertions": None,
                    "reward_basis": ["DB"],
                },
            }
        ]
        (retail_dir / "tasks.json").write_text(json.dumps(tasks))
        result = load_tasks(retail_dir)
        assert len(result) == 1
        assert result[0]["id"] == 0


def test_resolve_tau3_retail_dir_success(tmp_path: Path):
    """_resolve_tau3_retail_dir returns the retail dir path when it exists."""
    retail_dir = tmp_path / "domains" / "retail"
    retail_dir.mkdir(parents=True)
    (retail_dir / "tasks.json").write_text("[]")
    config = AppConfig(
        tau3_retail_root=tmp_path,
        tau2_bench_root=tmp_path,
        artifact_dir=tmp_path,
        deepseek_api_key="",
        deepseek_base_url="",
        default_agent_model="test",
        agent_llm_timeout_seconds=1.0,
        agent_llm_max_retries=0,
    )
    result = _resolve_tau3_retail_dir(config)
    assert isinstance(result, Path)
    assert result == config.retail_domain_dir


def test_resolve_tau3_retail_dir_raises_when_missing(tmp_path: Path):
    """_resolve_tau3_retail_dir raises FileNotFoundError when dir is missing."""
    config = AppConfig(
        tau3_retail_root=tmp_path,
        tau2_bench_root=tmp_path,
        artifact_dir=tmp_path,
        deepseek_api_key="",
        deepseek_base_url="",
        default_agent_model="test",
        agent_llm_timeout_seconds=1.0,
        agent_llm_max_retries=0,
    )
    with pytest.raises(FileNotFoundError, match="tau3 retail domain directory not found"):
        _resolve_tau3_retail_dir(config)


def test_compute_task_space_stats_counts_correctly():
    """compute_task_space_stats computes correct aggregate statistics."""
    tasks = [
        {
            "id": 0,
            "evaluation_criteria": {
                "actions": [
                    {"name": "get_order_details", "action_id": "0_0", "arguments": {}, "info": None},
                    {"name": "cancel_pending_order", "action_id": "0_1", "arguments": {}, "info": None},
                ],
                "reward_basis": ["DB", "NL_ASSERTION"],
            },
        },
        {
            "id": 1,
            "evaluation_criteria": {
                "actions": [
                    {"name": "get_order_details", "action_id": "1_0", "arguments": {}, "info": None},
                ],
                "reward_basis": ["DB"],
            },
        },
    ]
    splits = {"train": ["0"], "test": ["1"], "base": ["0", "1"]}
    stats = compute_task_space_stats(tasks, splits)
    assert stats.total_tasks == 2
    assert stats.train_count == 1
    assert stats.test_count == 1
    assert stats.action_count_min == 1
    assert stats.action_count_max == 2
    assert stats.action_count_avg == 1.5
    assert stats.tool_frequencies["get_order_details"] == 2
    assert stats.tool_frequencies["cancel_pending_order"] == 1


def test_classify_task_all_supported_tools_returns_supported():
    """Task with only supported tools classifies as supported."""
    task = {
        "id": 0,
        "evaluation_criteria": {
            "actions": [
                {"name": "get_order_details", "action_id": "0_0", "arguments": {}, "info": None},
                {"name": "cancel_pending_order", "action_id": "0_1", "arguments": {}, "info": None},
            ],
            "nl_assertions": None,
            "reward_basis": ["DB"],
        },
    }
    splits = {"train": ["0"], "test": [], "base": ["0"]}
    result = classify_task(task, splits)
    assert result.status == "supported"
    assert result.split == "train"


def test_classify_task_with_calculate_returns_partial_missing_tool():
    """Task using 'calculate' classifies as partial_missing_tool."""
    task = {
        "id": 5,
        "evaluation_criteria": {
            "actions": [
                {"name": "get_order_details", "action_id": "5_0", "arguments": {}, "info": None},
                {"name": "calculate", "action_id": "5_1", "arguments": {}, "info": None},
            ],
            "nl_assertions": None,
            "reward_basis": ["DB"],
        },
    }
    splits = {"train": [], "test": ["5"], "base": ["5"]}
    result = classify_task(task, splits)
    assert result.status == "partial"
    assert result.subcategory == "partial_missing_tool"
    assert "calculate" in result.missing_tools


def test_classify_task_with_nl_assertion_returns_partial():
    """Task with NL assertion but all tools supported returns partial_nl_assertion."""
    task = {
        "id": 10,
        "evaluation_criteria": {
            "actions": [
                {"name": "get_order_details", "action_id": "10_0", "arguments": {}, "info": None},
            ],
            "nl_assertions": ["Agent should tell the user something."],
            "reward_basis": ["DB", "NL_ASSERTION"],
        },
    }
    splits = {"train": ["10"], "test": [], "base": ["10"]}
    result = classify_task(task, splits)
    assert result.status == "partial"
    assert result.subcategory == "partial_nl_assertion"


def test_classify_task_no_actions_returns_unsupported():
    """Task with zero actions classifies as unsupported_unknown."""
    task = {
        "id": 99,
        "evaluation_criteria": {
            "actions": [],
            "nl_assertions": None,
            "reward_basis": ["DB"],
        },
    }
    splits = {"train": [], "test": ["99"], "base": ["99"]}
    result = classify_task(task, splits)
    assert result.status == "unsupported"


def test_analyze_nl_assertions_categorizes_correctly():
    """analyze_nl_assertions categorizes NL assertions by type."""
    tasks = [
        {
            "id": 1,
            "evaluation_criteria": {
                "nl_assertions": [
                    "Agent should tell the user the refund is $50.",
                    "Agent should not mention the competitor's price.",
                ],
            },
        },
        {
            "id": 2,
            "evaluation_criteria": {
                "nl_assertions": [
                    "Agent should convey the shipping timeline.",
                ],
            },
        },
    ]
    result = analyze_nl_assertions(tasks)

    assert result["total_tasks_with_nl"] == 2
    assert result["total_assertions"] == 3
    assert result["by_category"]["must_say"] == 1
    assert result["by_category"]["must_not_say"] == 1
    assert result["by_category"]["must_convey"] == 1
    assert len(result["items"]) == 3
    assert result["items"][0].task_id == "1"


def test_analyze_nl_assertions_no_assertions_returns_empty():
    """Tasks without NL assertions return empty analysis."""
    tasks = [
        {
            "id": 0,
            "evaluation_criteria": {"nl_assertions": None},
        },
    ]
    result = analyze_nl_assertions(tasks)
    assert result["total_tasks_with_nl"] == 0
    assert result["total_assertions"] == 0
    assert len(result["items"]) == 0


def test_aggregate_by_capability_groups_tasks():
    """aggregate_by_capability groups classifications by primary intent."""
    classifications = [
        TaskClassification(
            task_id="0", split="train", status="supported",
            tools_used=["get_order_details", "cancel_pending_order"],
        ),
        TaskClassification(
            task_id="1", split="train", status="supported",
            tools_used=["get_order_details", "return_delivered_order_items"],
        ),
        TaskClassification(
            task_id="2", split="test", status="partial",
            subcategory="partial_missing_tool",
            tools_used=["get_order_details", "calculate", "cancel_pending_order"],
        ),
    ]
    result = aggregate_by_capability(classifications)
    # "cancel" capability should group tasks using cancel_pending_order
    assert "cancel" in result
    assert result["cancel"]["total"] == 2  # task 0 and 2
    assert result["cancel"]["supported"] == 1
    assert result["cancel"]["partial"] == 1
    # "return" capability
    assert "return" in result
    assert result["return"]["total"] == 1
    assert result["return"]["supported"] == 1
