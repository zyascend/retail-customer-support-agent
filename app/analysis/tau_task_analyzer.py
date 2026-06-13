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


# ---------------------------------------------------------------------------
# Tool coverage constants
# ---------------------------------------------------------------------------

SUPPORTED_READ_TOOLS: set[str] = {
    "find_user_id_by_email",
    "find_user_id_by_name_zip",
    "get_user_details",
    "get_order_details",
    "get_product_details",
    "lookup_payment_method",
    "check_gift_card_balance",
}

SUPPORTED_WRITE_TOOLS: set[str] = {
    "cancel_pending_order",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
    "exchange_delivered_order_items",
    "transfer_to_human_agents",
}

SUPPORTED_TOOLS: set[str] = SUPPORTED_READ_TOOLS | SUPPORTED_WRITE_TOOLS

# Tools tau3 uses that we have but are auxiliary (not core transaction tools).
# Missing these does not block the main workflow.
AUXILIARY_TOOLS: set[str] = {
    "calculate",
    "get_item_details",
}

# Keywords that suggest policy-sensitive scenarios
POLICY_KEYWORDS: list[str] = [
    "gift", "coupon", "discount", "compensation", "refund",
    "price match", "loyalty", "warranty", "damage", "lost",
    "missing", "wrong item",
]


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_task(task: dict, splits: dict) -> TaskClassification:
    """Classify a single tau task as supported / partial / unsupported.

    Classification order (first match wins):
      1. unsupported: no actions, or uses tools we completely lack
      2. partial: uses auxiliary tools, has NL assertions, or policy gaps
      3. supported: everything else
    """
    task_id = str(task["id"])
    ec = task.get("evaluation_criteria", {})
    actions = ec.get("actions", [])
    action_names = [a.get("name", "unknown") for a in actions]
    action_set = set(action_names)
    nl_assertions = ec.get("nl_assertions")

    # Determine split
    split = "unknown"
    for split_name in ("train", "test", "base"):
        if task_id in splits.get(split_name, []):
            split = split_name
            break

    # Check unsupported: no actions at all
    if len(actions) == 0:
        return TaskClassification(
            task_id=task_id,
            split=split,
            status="unsupported",
            subcategory="unsupported_unknown",
            tools_used=[],
            missing_tools=[],
            has_nl_assertion=nl_assertions is not None,
            has_policy_keywords=False,
            action_count=0,
            reward_basis=list(ec.get("reward_basis", [])),
            notes="Task has no expected actions.",
        )

    # Check unsupported: uses tools we completely lack
    # (tools not in SUPPORTED_TOOLS and not in AUXILIARY_TOOLS)
    completely_missing = action_set - SUPPORTED_TOOLS - AUXILIARY_TOOLS
    if completely_missing:
        return TaskClassification(
            task_id=task_id,
            split=split,
            status="unsupported",
            subcategory="unsupported_tool",
            tools_used=sorted(action_set),
            missing_tools=sorted(completely_missing),
            has_nl_assertion=nl_assertions is not None,
            has_policy_keywords=False,
            action_count=len(actions),
            reward_basis=list(ec.get("reward_basis", [])),
            notes=f"Uses unsupported tools: {', '.join(sorted(completely_missing))}.",
        )

    # Check partial: uses auxiliary tools
    auxiliary_used = action_set & AUXILIARY_TOOLS
    has_nl = nl_assertions is not None

    # Check policy keywords in task description
    desc_str = json.dumps(task.get("description", {}))
    has_policy = any(kw in desc_str.lower() for kw in POLICY_KEYWORDS)

    partial_reasons = []
    if auxiliary_used:
        partial_reasons.append("partial_missing_tool")
    if has_nl:
        partial_reasons.append("partial_nl_assertion")
    if has_policy:
        partial_reasons.append("partial_policy_gap")

    if partial_reasons:
        subcategory = (
            "partial_multi" if len(partial_reasons) > 1 else partial_reasons[0]
        )
        notes_parts = []
        if auxiliary_used:
            notes_parts.append(
                f"uses auxiliary tools: {', '.join(sorted(auxiliary_used))}"
            )
        if has_nl:
            notes_parts.append("has NL assertions")
        if has_policy:
            notes_parts.append("involves policy-sensitive keywords")
        return TaskClassification(
            task_id=task_id,
            split=split,
            status="partial",
            subcategory=subcategory,
            tools_used=sorted(action_set),
            missing_tools=sorted(auxiliary_used),
            has_nl_assertion=has_nl,
            has_policy_keywords=has_policy,
            action_count=len(actions),
            reward_basis=list(ec.get("reward_basis", [])),
            notes="; ".join(notes_parts),
        )

    # Default: supported
    return TaskClassification(
        task_id=task_id,
        split=split,
        status="supported",
        subcategory=None,
        tools_used=sorted(action_set),
        missing_tools=[],
        has_nl_assertion=False,
        has_policy_keywords=False,
        action_count=len(actions),
        reward_basis=list(ec.get("reward_basis", [])),
        notes="All tools supported, no NL assertions, no policy concerns.",
    )


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


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def compute_task_space_stats(tasks: list[dict], splits: dict) -> TaskSpaceStats:
    """Compute aggregate statistics across all tasks."""
    total = len(tasks)
    train_ids = set(splits.get("train", []))
    test_ids = set(splits.get("test", []))

    action_counts = []
    tool_freq: dict[str, int] = {}
    reward_basis_dist: dict[str, int] = {}

    for t in tasks:
        ec = t.get("evaluation_criteria", {})
        actions = ec.get("actions", [])
        action_counts.append(len(actions))
        for action in actions:
            name = action.get("name", "unknown")
            tool_freq[name] = tool_freq.get(name, 0) + 1
        rb = tuple(sorted(ec.get("reward_basis", [])))
        key = " + ".join(rb) if rb else "none"
        reward_basis_dist[key] = reward_basis_dist.get(key, 0) + 1

    return TaskSpaceStats(
        total_tasks=total,
        train_count=sum(1 for t in tasks if str(t["id"]) in train_ids),
        test_count=sum(1 for t in tasks if str(t["id"]) in test_ids),
        reward_basis_distribution=reward_basis_dist,
        action_count_min=min(action_counts) if action_counts else 0,
        action_count_max=max(action_counts) if action_counts else 0,
        action_count_avg=sum(action_counts) / len(action_counts) if action_counts else 0.0,
        tool_frequencies=dict(
            sorted(tool_freq.items(), key=lambda x: x[1], reverse=True)
        ),
    )
