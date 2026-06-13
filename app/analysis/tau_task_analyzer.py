"""Tau 零售任务空间分析器。

读取 tau3 零售任务的 tasks.json 和 split_tasks.json，将每个任务分类为
supported / partial / unsupported，分析 NL 断言，并生成综合性的 Markdown 报告。

用法：
    uv run python -m app.analysis.tau_task_analyzer
    uv run python -m app.analysis.tau_task_analyzer --json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from app.config import AppConfig


@dataclass
class TaskClassification:
    """Classification result for a single tau task."""
    task_id: str
    split: str  # "train" | "test"
    status: str  # "supported" | "partial" | "unsupported"
    subcategory: Optional[str] = None
    tools_used: List[str] = field(default_factory=list)
    missing_tools: List[str] = field(default_factory=list)
    has_nl_assertion: bool = False
    has_policy_keywords: bool = False
    action_count: int = 0
    reward_basis: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class TaskSpaceStats:
    """Aggregate statistics across all tasks."""
    total_tasks: int = 0
    train_count: int = 0
    test_count: int = 0
    reward_basis_distribution: dict = field(default_factory=dict)
    action_count_min: int = 0
    action_count_max: int = 0
    action_count_avg: float = 0.0
    tool_frequencies: dict = field(default_factory=dict)


@dataclass
class NLAssertionItem:
    """A single NL assertion from a task."""
    task_id: str
    text: str
    category: str  # "must_say" | "must_not_say" | "must_convey"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _resolve_tau3_retail_dir(config: AppConfig) -> Path:
    """Resolve the tau3 retail domain directory, raising if not found."""
    retail_dir = config.retail_domain_dir
    if not retail_dir.exists():
        raise FileNotFoundError(
            f"tau3 retail domain directory not found: {retail_dir}\n"
            f"Set TAU3_RETAIL_ROOT or ensure the data exists at the default path."
        )
    return retail_dir


def load_tasks(retail_dir: Path) -> list[dict]:
    """Load all tasks from tasks.json."""
    tasks_path = retail_dir / "tasks.json"
    with open(tasks_path, encoding="utf-8") as f:
        return json.load(f)


def load_splits(retail_dir: Path) -> dict:
    """Load train/test split definitions.

    Returns:
        dict with keys "train", "test", "base", each mapping to a list of
        task ID strings.
    """
    splits_path = retail_dir / "split_tasks.json"
    with open(splits_path, encoding="utf-8") as f:
        return json.load(f)
