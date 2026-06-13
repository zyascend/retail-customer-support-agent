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


def test_load_splits_parses_split_tasks_json():
    """load_splits returns dict with train, test, base keys."""
    with tempfile.TemporaryDirectory() as tmp:
        retail_dir = Path(tmp)
        splits = {"train": ["0", "1"], "test": ["5", "9"], "base": ["0", "1", "5", "9"]}
        (retail_dir / "split_tasks.json").write_text(json.dumps(splits))
        result = load_splits(retail_dir)
        assert result == splits
        assert result["train"] == ["0", "1"]
        assert result["test"] == ["5", "9"]


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


def test_resolve_tau3_retail_dir_returns_path():
    """_resolve_tau3_retail_dir returns a Path that exists or raises."""
    from app.config import AppConfig, resolve_config

    config = resolve_config()
    result = _resolve_tau3_retail_dir(config)
    assert isinstance(result, Path)
