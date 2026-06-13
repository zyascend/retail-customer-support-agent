"""Tau retail task space analyzer.

Reads tau3 retail tasks.json and split_tasks.json, classifies every task
as supported / partial / unsupported, analyzes NL assertions, and renders
a comprehensive Markdown report.

Usage:
    uv run python -m app.analysis.tau_task_analyzer
    uv run python -m app.analysis.tau_task_analyzer --json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from app.config import AppConfig, resolve_config


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
