"""Tests for tau task analyzer."""

import json
import tempfile
from pathlib import Path

import pytest

from app.analysis.tau_task_analyzer import (
    _resolve_tau3_retail_dir,
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
