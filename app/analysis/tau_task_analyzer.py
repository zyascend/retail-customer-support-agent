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
class Phase12GapAnalysis:
    """Phase 12 expansion category for a tau task."""

    task_id: str
    category: str
    priority: int
    blocking_reasons: list[str] = field(default_factory=list)
    can_expand_without_runtime_parser: bool = True


@dataclass
class Phase12LiveEvidence:
    """Latest live evidence for a Phase 12 eval slice."""

    eval_run_id: str
    subset: str
    eval_backend: str
    created_at: str
    passed_count: int
    case_count: int
    pass_rate: float
    tool_call_success_rate: float
    mutation_error_rate: float
    promotable: bool
    promoted_task_ids: list[str] = field(default_factory=list)
    failure_labels: dict[str, int] = field(default_factory=dict)


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


def analyze_phase12_gap(classification: TaskClassification) -> Phase12GapAnalysis:
    """Map a task classification to the Phase 12 capability expansion queue."""
    if classification.status == "supported":
        return Phase12GapAnalysis(
            task_id=classification.task_id,
            category="ready",
            priority=0,
        )

    if classification.missing_tools:
        missing = ", ".join(classification.missing_tools)
        category = "tool_gap"
        priority = 10
        reasons = [f"missing auxiliary/schema support: {missing}"]
        can_expand = False
        if all(tool in AUXILIARY_TOOLS for tool in classification.missing_tools):
            category = "schema_gap"
            can_expand = True
            if not classification.has_nl_assertion and not classification.has_policy_keywords:
                category = "schema_ready"
                priority = 5
                reasons = [f"auxiliary tools already exposed: {missing}"]
        return Phase12GapAnalysis(
            task_id=classification.task_id,
            category=category,
            priority=priority,
            blocking_reasons=reasons,
            can_expand_without_runtime_parser=can_expand,
        )

    if classification.has_policy_keywords:
        return Phase12GapAnalysis(
            task_id=classification.task_id,
            category="guard_policy_review",
            priority=20,
            blocking_reasons=["policy-sensitive wording requires guard review"],
        )

    if classification.has_nl_assertion:
        return Phase12GapAnalysis(
            task_id=classification.task_id,
            category="prompt_or_response_gap",
            priority=30,
            blocking_reasons=["NL assertion requires response evidence"],
        )

    return Phase12GapAnalysis(
        task_id=classification.task_id,
        category="fixture_or_unknown_gap",
        priority=40,
        blocking_reasons=["unsupported task shape or fixture gap"],
        can_expand_without_runtime_parser=False,
    )


def compute_phase12_coverage_rungs(
    classifications: list[TaskClassification],
    *,
    total_supported_target: int = 69,
    promoted_task_ids: list[str] | None = None,
) -> dict:
    """Compute Phase 12 target rung status for supported tau tasks."""
    current = sum(1 for c in classifications if c.status == "supported")
    supported_ids = {c.task_id for c in classifications if c.status == "supported"}
    promoted_ids = set(promoted_task_ids or [])
    live_promoted_count = len(promoted_ids - supported_ids)
    effective_supported = current + live_promoted_count
    return {
        "current_supported": current,
        "live_promoted_count": live_promoted_count,
        "effective_supported": effective_supported,
        "target_total": total_supported_target,
        "total_tasks": len(classifications),
        "stable_40_plus": effective_supported >= 40,
        "stable_50_plus": effective_supported >= 50,
        "stable_55_plus": effective_supported >= 55,
        "remaining_to_40": max(0, 40 - effective_supported),
        "remaining_to_50": max(0, 50 - effective_supported),
        "remaining_to_55": max(0, 55 - effective_supported),
        "remaining_to_all_tasks": max(0, len(classifications) - effective_supported),
    }


def build_phase12_coverage_rung_plan(
    classifications: list[TaskClassification],
    *,
    promoted_task_ids: list[str] | None = None,
) -> dict:
    """Summarize the current rung and whether safe candidates can reach the next one."""
    rungs = compute_phase12_coverage_rungs(
        classifications,
        promoted_task_ids=promoted_task_ids,
    )
    current = rungs["effective_supported"]
    safe_candidates = select_phase12_next_candidates(
        classifications,
        limit=1000,
        promoted_task_ids=promoted_task_ids,
    )
    safe_candidate_count = len(safe_candidates)
    schema_ready_count = sum(
        1 for candidate in safe_candidates if candidate.category == "schema_ready"
    )
    projected = current + safe_candidate_count

    if current >= 55:
        current_rung = "stable_55_plus"
        next_target = None
    elif current >= 50:
        current_rung = "stable_50_plus"
        next_target = 55
    elif current >= 40:
        current_rung = "stable_40_plus"
        next_target = 50
    else:
        current_rung = "below_40"
        next_target = 40

    remaining = 0 if next_target is None else max(0, next_target - current)
    return {
        "current_rung": current_rung,
        "next_target": next_target,
        "remaining_to_next": remaining,
        "safe_candidate_count": safe_candidate_count,
        "schema_ready_count": schema_ready_count,
        "projected_supported_after_safe_candidates": projected,
        "can_reach_next_with_safe_candidates": (
            True if next_target is None else projected >= next_target
        ),
    }


def load_phase12_live_evidence(
    artifact_dir: Path = Path("artifacts/phase2"),
    *,
    subset: str = "tau_phase12_schema_ready",
) -> Phase12LiveEvidence | None:
    """Load the latest live eval evidence for a Phase 12 subset."""
    eval_runs_dir = artifact_dir / "eval_runs"
    if not eval_runs_dir.exists():
        return None

    candidates: list[dict] = []
    for path in eval_runs_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("subset") != subset:
            continue
        if payload.get("eval_backend") != "live":
            continue
        candidates.append(payload)

    if not candidates:
        return None

    latest = max(
        candidates,
        key=lambda item: str(item.get("created_at") or item.get("artifact_created_at") or ""),
    )
    metrics = latest.get("metrics") or {}
    passed_count = int(latest.get("passed_count") or 0)
    case_count = int(latest.get("case_count") or 0)
    mutation_error_rate = float(metrics.get("mutation_error_rate") or 0.0)
    pass_rate = float(latest.get("pass_rate") or 0.0)
    tool_call_success_rate = float(metrics.get("tool_call_success_rate") or 0.0)
    promotable = (
        case_count > 0 and passed_count == case_count and mutation_error_rate == 0.0
    )
    promoted_task_ids: list[str] = []
    failure_labels: dict[str, int] = {}
    if promotable:
        for result in latest.get("results") or []:
            if not result.get("passed"):
                continue
            case_id = str(result.get("case_id") or "")
            if case_id.startswith("tau_"):
                case_id = case_id[4:]
            if case_id:
                promoted_task_ids.append(case_id)
    else:
        for result in latest.get("results") or []:
            label = str(result.get("failure_label") or "")
            if not label:
                continue
            failure_labels[label] = failure_labels.get(label, 0) + 1
    return Phase12LiveEvidence(
        eval_run_id=str(latest.get("eval_run_id") or ""),
        subset=str(latest.get("subset") or subset),
        eval_backend=str(latest.get("eval_backend") or ""),
        created_at=str(latest.get("created_at") or latest.get("artifact_created_at") or ""),
        passed_count=passed_count,
        case_count=case_count,
        pass_rate=pass_rate,
        tool_call_success_rate=tool_call_success_rate,
        mutation_error_rate=mutation_error_rate,
        promotable=promotable,
        promoted_task_ids=promoted_task_ids,
        failure_labels=failure_labels,
    )


def select_phase12_next_candidates(
    classifications: list[TaskClassification],
    *,
    limit: int = 10,
    promoted_task_ids: list[str] | None = None,
) -> list[Phase12GapAnalysis]:
    """Return safe non-supported tasks prioritized for Phase 12 expansion."""
    promoted_ids = set(promoted_task_ids or [])
    gaps = [
        analyze_phase12_gap(classification)
        for classification in classifications
        if classification.status != "supported"
        and classification.task_id not in promoted_ids
    ]
    safe_gaps = [gap for gap in gaps if gap.can_expand_without_runtime_parser]
    safe_gaps.sort(key=lambda gap: (gap.priority, int(gap.task_id)))
    return safe_gaps[:limit]


@dataclass
class NLAssertionItem:
    """A single NL assertion from a task."""
    task_id: str
    text: str
    category: str  # "must_say" | "must_not_say" | "must_convey"


# ---------------------------------------------------------------------------
# NL assertion analysis
# ---------------------------------------------------------------------------


def _categorize_nl_assertion(text: str) -> str:
    """Categorize a single NL assertion string.

    Categories:
      - "must_say": Agent should tell/user should be informed of specific info
      - "must_not_say": Agent should NOT mention/say something
      - "must_convey": Agent should convey a general concept (less specific)
    """
    lower = text.lower()
    if "should not" in lower or "must not" in lower or "shouldn't" in lower:
        return "must_not_say"
    if "should tell" in lower or "should inform" in lower or "should state" in lower:
        return "must_say"
    if "should convey" in lower or "should communicate" in lower or "should explain" in lower:
        return "must_convey"
    return "must_say"


def analyze_nl_assertions(tasks: list[dict]) -> dict:
    """Analyze all NL assertions across tasks.

    Returns a dict with:
      - total_tasks_with_nl: count of tasks that have NL assertions
      - total_assertions: total number of assertion strings
      - by_category: dict of category -> count
      - sample_by_category: dict of category -> list of up to 3 examples
      - items: list of NLAssertionItem for all assertions
    """
    items: list[NLAssertionItem] = []
    by_category: dict[str, int] = {}
    sample_by_category: dict[str, list[str]] = {}

    for task in tasks:
        nl = task.get("evaluation_criteria", {}).get("nl_assertions")
        if not nl:
            continue
        for assertion_text in nl:
            category = _categorize_nl_assertion(assertion_text)
            items.append(
                NLAssertionItem(
                    task_id=str(task["id"]),
                    text=assertion_text,
                    category=category,
                )
            )
            by_category[category] = by_category.get(category, 0) + 1
            if category not in sample_by_category:
                sample_by_category[category] = []
            if len(sample_by_category[category]) < 3:
                sample_by_category[category].append(assertion_text)

    return {
        "total_tasks_with_nl": len(
            {item.task_id for item in items}
        ),
        "total_assertions": len(items),
        "by_category": by_category,
        "sample_by_category": sample_by_category,
        "items": items,
    }


# ---------------------------------------------------------------------------
# Capability aggregation
# ---------------------------------------------------------------------------

# Map tool names to capability groups
TOOL_TO_CAPABILITY: dict[str, str] = {
    "cancel_pending_order": "cancel",
    "return_delivered_order_items": "return",
    "exchange_delivered_order_items": "exchange",
    "modify_pending_order_address": "modify_address",
    "modify_pending_order_items": "modify_items",
    "modify_pending_order_payment": "modify_payment",
    "modify_user_address": "modify_user_address",
    "transfer_to_human_agents": "transfer",
    "find_user_id_by_email": "lookup",
    "find_user_id_by_name_zip": "lookup",
    "get_user_details": "lookup",
    "get_order_details": "lookup",
    "get_product_details": "lookup",
    "calculate": "calculate",
    "get_item_details": "lookup",
}


def _primary_capability(tools_used: list[str]) -> str:
    """Determine the primary capability from the tools used.

    Priority: write tools > auxiliary tools > read tools.
    If multiple in the same tier, pick the first alphabetically for consistency.
    """
    write_caps: set[str] = set()
    auxiliary_caps: set[str] = set()
    read_caps: set[str] = set()
    for tool in tools_used:
        cap = TOOL_TO_CAPABILITY.get(tool, "unknown")
        if tool in SUPPORTED_WRITE_TOOLS:
            write_caps.add(cap)
        elif tool in AUXILIARY_TOOLS:
            auxiliary_caps.add(cap)
        else:
            read_caps.add(cap)
    if write_caps:
        return sorted(write_caps)[0]
    if auxiliary_caps:
        return sorted(auxiliary_caps)[0]
    if "lookup" in read_caps:
        return "lookup"
    if read_caps:
        return sorted(read_caps)[0]
    return "unknown"


def aggregate_by_capability(classifications: list[TaskClassification]) -> dict:
    """Aggregate classifications by capability group.

    Returns:
        dict of capability_name -> {
            "total": int,
            "supported": int,
            "partial": int,
            "unsupported": int,
            "train": int,
            "test": int,
        }
    """
    caps: dict[str, dict] = {}
    for c in classifications:
        cap = _primary_capability(c.tools_used)
        if cap not in caps:
            caps[cap] = {
                "total": 0,
                "supported": 0,
                "partial": 0,
                "unsupported": 0,
                "train": 0,
                "test": 0,
            }
        caps[cap]["total"] += 1
        caps[cap][c.status] += 1
        if c.split in ("train", "test"):
            caps[cap][c.split] += 1
    return caps


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


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def render_report(
    stats: TaskSpaceStats,
    classifications: list[TaskClassification],
    nl_analysis: dict,
    cap_agg: dict,
    data_source_path: str,
    unsupported_tool_info: dict,
    missing_tool_info: dict,
    phase12_live_evidence: Phase12LiveEvidence | None = None,
    phase12_additional_live_evidence: list[Phase12LiveEvidence] | None = None,
) -> str:
    """Render the complete Markdown analysis report."""
    evidence_items = [
        item
        for item in [
            phase12_live_evidence,
            *(phase12_additional_live_evidence or []),
        ]
        if item is not None
    ]
    promoted_task_ids = sorted(
        {
            task_id
            for item in evidence_items
            if item.promotable
            for task_id in item.promoted_task_ids
        },
        key=int,
    )
    lines: list[str] = []
    _section_1_overview(lines, stats, data_source_path)
    _section_2_task_space(lines, stats)
    _section_3_tool_coverage(lines, classifications, unsupported_tool_info, missing_tool_info)
    _section_4_classification(lines, classifications, stats)
    _section_5_nl_assertions(lines, nl_analysis, classifications)
    _section_6_capability(lines, cap_agg)
    _section_7_known_issues(lines)
    _section_8_recommendations(lines, classifications, stats)
    _section_9_phase12_queue(
        lines,
        compute_phase12_coverage_rungs(
            classifications,
            promoted_task_ids=promoted_task_ids,
        ),
        build_phase12_coverage_rung_plan(
            classifications,
            promoted_task_ids=promoted_task_ids,
        ),
        select_phase12_next_candidates(
            classifications,
            promoted_task_ids=promoted_task_ids,
        ),
        phase12_live_evidence,
        phase12_additional_live_evidence or [],
    )
    return "\n".join(lines)


def _section_1_overview(lines: list[str], stats: TaskSpaceStats, data_source: str) -> None:
    lines.append("# Tau Retail Task Space Analysis")
    lines.append("")
    lines.append("## 1. 概述")
    lines.append("")
    lines.append("**分析日期**: 2026-06-13")
    lines.append(f"**数据来源**: `{data_source}`")
    lines.append(f"**Task 总数**: {stats.total_tasks}")
    lines.append(f"**Split 分布**: train {stats.train_count} / test {stats.test_count}")
    lines.append("")


def _section_2_task_space(lines: list[str], stats: TaskSpaceStats) -> None:
    lines.append("## 2. Task 空间统计")
    lines.append("")
    lines.append("### 2.1 Split 分布")
    lines.append("")
    lines.append("| Split | Task 数量 |")
    lines.append("|-------|----------|")
    lines.append(f"| train | {stats.train_count} |")
    lines.append(f"| test  | {stats.test_count} |")
    lines.append(f"| **合计** | **{stats.total_tasks}** |")
    lines.append("")

    lines.append("### 2.2 Reward Basis 分布")
    lines.append("")
    lines.append("| Reward Basis | 数量 |")
    lines.append("|-------------|------|")
    for basis, count in sorted(stats.reward_basis_distribution.items()):
        lines.append(f"| {basis} | {count} |")
    lines.append("")

    lines.append("### 2.3 Action 数量分布")
    lines.append("")
    lines.append(f"- **最小**: {stats.action_count_min}")
    lines.append(f"- **最大**: {stats.action_count_max}")
    lines.append(f"- **平均**: {stats.action_count_avg:.1f}")
    lines.append("")

    lines.append("### 2.4 工具使用频率 (Top 15)")
    lines.append("")
    lines.append("| 工具 | 出现次数 |")
    lines.append("|------|---------|")
    for tool, count in list(stats.tool_frequencies.items())[:15]:
        lines.append(f"| {tool} | {count} |")
    lines.append("")


def _section_3_tool_coverage(
    lines: list[str],
    classifications: list[TaskClassification],
    unsupported_info: dict,
    missing_info: dict,
) -> None:
    lines.append("## 3. 工具覆盖分析")
    lines.append("")
    lines.append("### 3.1 Agent 已支持工具 vs tau3 要求工具")
    lines.append("")
    lines.append("| 工具 | 状态 | 出现次数 |")
    lines.append("|------|------|---------|")
    tau_tools = set()
    for c in classifications:
        tau_tools.update(c.tools_used)
    for tool in sorted(tau_tools):
        if tool in SUPPORTED_TOOLS:
            status = "✅ 已支持"
        elif tool in AUXILIARY_TOOLS:
            status = "⚠️ 辅助工具（partial）"
        else:
            status = "❌ 不支持"
        count = sum(1 for c in classifications if tool in c.tools_used)
        lines.append(f"| {tool} | {status} | {count} |")

    lines.append("")
    lines.append("### 3.2 缺失工具详情")
    lines.append("")
    for tool_name, info in sorted(unsupported_info.items()):
        lines.append(f"#### `{tool_name}`")
        lines.append(f"- 出现次数: {info['count']}")
        lines.append(f"- 影响 task: {', '.join(info['task_ids'])}")
        lines.append("")
    for tool_name, info in sorted(missing_info.items()):
        lines.append(f"#### `{tool_name}` (辅助工具)")
        lines.append(f"- 出现次数: {info['count']}")
        lines.append(f"- 影响 task: {', '.join(info['task_ids'])}")
        lines.append("- 评估: 辅助计算/查询，Agent 主流程不受阻，标记为 partial")
        lines.append("")


def _section_4_classification(
    lines: list[str],
    classifications: list[TaskClassification],
    stats: TaskSpaceStats,
) -> None:
    lines.append("## 4. 分类结果")
    lines.append("")

    supported = [c for c in classifications if c.status == "supported"]
    partial = [c for c in classifications if c.status == "partial"]
    unsupported = [c for c in classifications if c.status == "unsupported"]

    lines.append("### 4.1 总览")
    lines.append("")
    lines.append("| 分类 | 数量 | 占比 |")
    lines.append("|------|------|------|")
    lines.append(f"| supported | {len(supported)} | {len(supported)/stats.total_tasks*100:.1f}% |")
    lines.append(f"| partial | {len(partial)} | {len(partial)/stats.total_tasks*100:.1f}% |")
    lines.append(f"| unsupported | {len(unsupported)} | {len(unsupported)/stats.total_tasks*100:.1f}% |")

    lines.append("")
    lines.append("### 4.2 按 Split 分布")
    lines.append("")
    for split_name in ("train", "test"):
        items = [c for c in classifications if c.split == split_name]
        sup = sum(1 for c in items if c.status == "supported")
        part = sum(1 for c in items if c.status == "partial")
        unsup = sum(1 for c in items if c.status == "unsupported")
        lines.append(f"- **{split_name}**: supported {sup}, partial {part}, unsupported {unsup}")

    lines.append("")
    lines.append("### 4.3 Partial 子类别")
    lines.append("")
    lines.append("| 子类别 | 数量 |")
    lines.append("|--------|------|")
    subcat_counts: dict[str, int] = {}
    for c in partial:
        key = c.subcategory or "unknown"
        subcat_counts[key] = subcat_counts.get(key, 0) + 1
    for subcat, count in sorted(subcat_counts.items()):
        lines.append(f"| {subcat} | {count} |")

    lines.append("")
    lines.append("### 4.4 Unsupported 子类别")
    lines.append("")
    lines.append("| 子类别 | 数量 | Task IDs |")
    lines.append("|--------|------|----------|")
    usubcat: dict[str, list[str]] = {}
    for c in unsupported:
        key = c.subcategory or "unknown"
        usubcat.setdefault(key, []).append(c.task_id)
    for subcat, task_ids in sorted(usubcat.items()):
        lines.append(f"| {subcat} | {len(task_ids)} | {', '.join(task_ids[:10])} |")

    lines.append("")
    lines.append("### 4.5 完整 Task 分类清单")
    lines.append("")
    lines.append("| Task ID | Split | 状态 | 子类别 | 工具数 | NL Assertion | 备注 |")
    lines.append("|---------|-------|------|--------|--------|-------------|------|")
    for c in sorted(classifications, key=lambda x: int(x.task_id)):
        nl_mark = "✓" if c.has_nl_assertion else "-"
        lines.append(
            f"| {c.task_id} | {c.split} | {c.status} | {c.subcategory or '-'} "
            f"| {c.action_count} | {nl_mark} | {c.notes[:80]} |"
        )
    lines.append("")


def _section_5_nl_assertions(
    lines: list[str],
    nl_analysis: dict,
    classifications: list[TaskClassification],
) -> None:
    lines.append("## 5. NL Assertion 分析")
    lines.append("")
    lines.append(f"- **含 NL assertion 的 task 数**: {nl_analysis['total_tasks_with_nl']}")
    lines.append(f"- **NL assertion 总数**: {nl_analysis['total_assertions']}")
    lines.append("")

    lines.append("### 5.1 按类型分布")
    lines.append("")
    lines.append("| 类型 | 数量 | 说明 |")
    lines.append("|------|------|------|")
    lines.append(f"| must_say | {nl_analysis['by_category'].get('must_say', 0)} | Agent 必须说出特定信息 |")
    lines.append(f"| must_not_say | {nl_analysis['by_category'].get('must_not_say', 0)} | Agent 不得提及特定内容 |")
    lines.append(f"| must_convey | {nl_analysis['by_category'].get('must_convey', 0)} | Agent 必须传达概念（措辞不限） |")
    lines.append("")

    lines.append("### 5.2 代表性示例")
    lines.append("")
    for category in ("must_say", "must_not_say", "must_convey"):
        samples = nl_analysis.get("sample_by_category", {}).get(category, [])
        if samples:
            lines.append(f"**{category}**:")
            for sample in samples:
                lines.append(f"- {sample}")
            lines.append("")

    lines.append("### 5.3 与现有 eval 能力的映射")
    lines.append("")
    lines.append("- `must_say` 类型可部分映射到 `expected_assistant_contains`，但 tau3 的 assertion 往往要求精确数值（如退款金额），当前 agent 的响应文本可能措辞不同但语义正确。")
    lines.append("- `must_not_say` 类型当前无直接对应的 eval 断言机制。")
    lines.append("- `must_convey` 类型最适合 `expected_assistant_contains`，但仍需人工判断。")
    lines.append("- **建议**: Phase 9 首批 ingestion 中将 NL assertion 标记为 `partial`，不作为 gate；后续可引入 LLM-based NL assertion evaluator。")
    lines.append("")

    nl_task_ids = sorted(set(
        item.task_id for item in nl_analysis["items"]
    ), key=int)
    lines.append("### 5.4 含 NL Assertion 的 Task 列表")
    lines.append("")
    lines.append(f"共 {len(nl_task_ids)} 个 task: {', '.join(nl_task_ids)}")
    lines.append("")


def _section_6_capability(lines: list[str], cap_agg: dict) -> None:
    lines.append("## 6. 按 Capability 维度聚合")
    lines.append("")
    lines.append("| Capability | 总数 | Supported | Partial | Unsupported | Train | Test |")
    lines.append("|-----------|------|-----------|---------|-------------|-------|------|")
    for cap in sorted(cap_agg.keys()):
        d = cap_agg[cap]
        lines.append(
            f"| {cap} | {d['total']} | {d['supported']} | {d['partial']} "
            f"| {d['unsupported']} | {d['train']} | {d['test']} |"
        )
    lines.append("")

    lines.append("### 6.2 与现有 Capability Matrix 对照")
    lines.append("")
    lines.append("现有 capability matrix（`docs/phase5-capability-matrix.md`）覆盖的能力：")
    lines.append("")
    lines.append("| Capability | 现有 Eval 覆盖 | tau3 Task 数 | 差距 |")
    lines.append("|-----------|---------------|-------------|------|")
    existing_caps = {
        "cancel": "generalized_mvp",
        "return": "generalized_mvp",
        "exchange": "generalized_mvp",
        "modify_address": "generalized_mvp",
        "modify_items": "generalized_mvp",
        "modify_payment": "generalized_mvp",
        "modify_user_address": "generalized_mvp",
        "transfer": "generalized_mvp",
        "lookup": "curated_mvp + generalized_mvp",
    }
    for cap, existing in sorted(existing_caps.items()):
        tau_count = cap_agg.get(cap, {}).get("total", 0)
        lines.append(f"| {cap} | {existing} | {tau_count} | {'⚠️ 需扩展' if tau_count > 5 else '✅ 接近'} |")
    lines.append("")


def _section_7_known_issues(lines: list[str]) -> None:
    lines.append("## 7. 已知问题 Task")
    lines.append("")
    lines.append("`task_issues/` 目录包含 3 个历史执行问题记录：")
    lines.append("")
    lines.append("- `task_4_issue_2b74ee61.json`")
    lines.append("- `task_5_issue_770466c1.json`")
    lines.append("- `task_7_issue_9a37c151.json`")
    lines.append("")
    lines.append("这些文件是 tau3 benchmark 的执行日志（包含 termination_reason、reward_info 等），")
    lines.append("而非 task 定义本身的问题。它们记录了 agent 在 tau3 原生环境中执行时的失败案例，")
    lines.append("可作为 Phase 9 smoke test 的参考——优先验证 task 4/5/7 在我们的 Agent 中能否通过。")
    lines.append("")


def _section_8_recommendations(
    lines: list[str],
    classifications: list[TaskClassification],
    stats: TaskSpaceStats,
) -> None:
    supported = [c for c in classifications if c.status == "supported"]
    partial = [c for c in classifications if c.status == "partial"]
    unsupported = [c for c in classifications if c.status == "unsupported"]

    sup_train = [c for c in supported if c.split == "train"]
    sup_test = [c for c in supported if c.split == "test"]

    lines.append("## 8. Phase 9 首批 Ingestion 建议")
    lines.append("")

    lines.append("### 8.1 推荐接入范围")
    lines.append("")
    lines.append(f"- **全量 supported task**: {len(supported)} 个（train {len(sup_train)} + test {len(sup_test)}）")
    lines.append(f"- **可考虑接入的 partial task**: {len(partial)} 个")
    partial_nl = sum(1 for c in partial if c.subcategory == "partial_nl_assertion")
    partial_tool = sum(1 for c in partial if c.subcategory == "partial_missing_tool")
    lines.append(f"  - 其中 `partial_nl_assertion` 子类: {partial_nl} 个（仅 NL assertion 差距，core workflow 完整）")
    lines.append(f"  - 其中 `partial_missing_tool` 子类: {partial_tool} 个")
    lines.append(f"- **建议排除的 unsupported task**: {len(unsupported)} 个")
    lines.append("")

    lines.append("### 8.2 分阶段接入策略")
    lines.append("")
    lines.append("**第一步: Smoke Test**")
    smoke_count = min(5, len(supported))
    lines.append(f"- 选取 {smoke_count} 个 supported task 验证 task → EvalCase 转换和 reward evaluation 流程")
    lines.append("- 优先选择 task_issues 中已知有问题的 task（4/5/7），验证我们的 Agent 能否改善")
    lines.append("")
    lines.append("**第二步: Supported 全量接入**")
    lines.append(f"- 接入全部 {len(supported)} 个 supported task")
    lines.append("- 新增 subset: `tau_retail_supported`")
    lines.append("- 作为 Phase 9 的 gate")
    lines.append("")
    lines.append("**第三步: Partial 接入**")
    lines.append(f"- 接入 {len(partial)} 个 partial task，NL assertion 作为非 gate 参考维度")
    lines.append("- 新增 subset: `tau_retail_partial`")
    lines.append("")

    lines.append("### 8.3 风险提示")
    lines.append("")
    lines.append("1. **NL Assertion 验证**: 40 个 task 有 NL assertion，当前无法自动验证。Phase 9 首批应将其作为非 gate 指标。")
    calc_tasks = sum(1 for c in partial if "calculate" in c.missing_tools)
    lines.append(f"2. **`calculate` 工具**: {calc_tasks} 个 task 依赖此工具。Agent 可在 response 中包含退款金额而不显式调用 `calculate`，但 reward evaluation 可能期望此 tool call。")
    lines.append("3. **DB State**: 所有 114 个 task 的 `initial_state` 为 null，tau3 使用完整 DB。Phase 9 需要确保每次 eval run 的 DB 初始状态一致。")
    lines.append("4. **User Simulation**: tau3 task 的 `user_scenario.instructions` 定义了用户行为脚本。Phase 9 需要实现 user simulator adapter 来驱动多轮对话。")
    lines.append("5. **Policy 差异**: tau3 的 `policy.md` 与我们的 guard rules 可能存在细微差异，需要在 smoke test 中逐条对照。")
    lines.append("")

    lines.append("### 8.4 排除项")
    lines.append("")
    lines.append(f"- {len(unsupported)} 个 unsupported task（原因: 无 action 或包含完全不支持的工具）")
    lines.append("- 短期内不考虑 `get_item_details` 工具实现（仅 3 个 task 使用）")
    lines.append("- 不引入 `calculate` 工具（Agent 的 LLM 推理可替代简单数学计算）")
    lines.append("")


def _section_9_phase12_queue(
    lines: list[str],
    coverage_rungs: dict,
    rung_plan: dict,
    next_candidates: list[Phase12GapAnalysis],
    live_evidence: Phase12LiveEvidence | None = None,
    additional_live_evidence: list[Phase12LiveEvidence] | None = None,
) -> None:
    lines.append("## 9. Phase 12 Coverage Expansion Queue")
    lines.append("")
    lines.append("### 9.1 Coverage rungs")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    for key in (
        "current_supported",
        "live_promoted_count",
        "effective_supported",
        "target_total",
        "total_tasks",
        "stable_40_plus",
        "stable_50_plus",
        "stable_55_plus",
        "remaining_to_40",
        "remaining_to_50",
        "remaining_to_55",
        "remaining_to_all_tasks",
    ):
        lines.append(f"| {key} | {coverage_rungs[key]} |")
    for key in (
        "current_rung",
        "next_target",
        "remaining_to_next",
        "safe_candidate_count",
        "schema_ready_count",
        "projected_supported_after_safe_candidates",
        "can_reach_next_with_safe_candidates",
    ):
        lines.append(f"| {key} | {rung_plan[key]} |")
    lines.append("")

    lines.append("### 9.2 Next candidates")
    lines.append("")
    if not next_candidates:
        lines.append("No safe non-supported candidates found for Phase 12 expansion.")
        lines.append("")
    else:
        lines.append("| Task ID | Category | Priority | Blocking reasons |")
        lines.append("|---------|----------|----------|------------------|")
        for candidate in next_candidates:
            reasons = "; ".join(candidate.blocking_reasons) or "-"
            lines.append(
                f"| {candidate.task_id} | {candidate.category} "
                f"| {candidate.priority} | {reasons} |"
            )
        lines.append("")

    lines.append("### 9.3 Phase 12 Live Evidence")
    lines.append("")
    if live_evidence is None:
        lines.append("No live evidence artifact found for Phase 12 schema-ready slice.")
        lines.append("")
    else:
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| eval_run_id | {live_evidence.eval_run_id} |")
        lines.append(f"| subset | {live_evidence.subset} |")
        lines.append(f"| eval_backend | {live_evidence.eval_backend} |")
        lines.append(f"| created_at | {live_evidence.created_at} |")
        lines.append(f"| passed_count | {live_evidence.passed_count} |")
        lines.append(f"| case_count | {live_evidence.case_count} |")
        lines.append(
            "| promoted_task_ids | "
            f"{', '.join(live_evidence.promoted_task_ids) or '-'} |"
        )
        lines.append(f"| pass_rate | {live_evidence.pass_rate:.4f} |")
        lines.append(
            f"| tool_call_success_rate | {live_evidence.tool_call_success_rate:.4f} |"
        )
        lines.append(f"| mutation_error_rate | {live_evidence.mutation_error_rate:.4f} |")
        lines.append(f"| promotable | {live_evidence.promotable} |")
        lines.append("")

    additional = additional_live_evidence or []
    if additional:
        lines.append("#### Additional Phase 12 Evidence")
        lines.append("")
        lines.append(
            "| Subset | Eval Run | Passed | Pass Rate | Promotable | Failure labels |"
        )
        lines.append(
            "|--------|----------|--------|-----------|------------|----------------|"
        )
        for evidence in additional:
            failure_labels = ", ".join(
                f"{label}={count}"
                for label, count in sorted(evidence.failure_labels.items())
            ) or "-"
            lines.append(
                f"| {evidence.subset} | {evidence.eval_run_id} | "
                f"{evidence.passed_count}/{evidence.case_count} | "
                f"{evidence.pass_rate:.4f} | {evidence.promotable} | "
                f"{failure_labels} |"
            )
        lines.append("")

    lines.append("### 9.4 Expansion rule")
    lines.append("")
    lines.append(
        "Phase 12 coverage must come from tool/schema/prompt/guard changes, "
        "not runtime case-specific parser branches."
    )
    lines.append("")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def analyze_and_report(config: AppConfig | None = None) -> str:
    """Run full analysis and return the Markdown report as a string.

    Args:
        config: Optional AppConfig. If None, resolves from env.

    Returns:
        Complete Markdown report string.

    Raises:
        FileNotFoundError: If tau3 retail data directory is not found.
    """
    if config is None:
        config = resolve_config()

    retail_dir = _resolve_tau3_retail_dir(config)

    # Load data
    tasks = load_tasks(retail_dir)
    splits = load_splits(retail_dir)

    # Statistics
    stats = compute_task_space_stats(tasks, splits)

    # Classify every task
    classifications = [classify_task(t, splits) for t in tasks]

    # NL assertion analysis
    nl_analysis = analyze_nl_assertions(tasks)

    # Capability aggregation
    cap_agg = aggregate_by_capability(classifications)

    # Tool gap info
    unsupported_tool_info: dict = {}
    missing_tool_info: dict = {}
    for c in classifications:
        for tool in c.missing_tools:
            if tool in AUXILIARY_TOOLS:
                target = missing_tool_info
            else:
                target = unsupported_tool_info
            if tool not in target:
                target[tool] = {"count": 0, "task_ids": []}
            target[tool]["count"] += 1
            if c.task_id not in target[tool]["task_ids"]:
                target[tool]["task_ids"].append(c.task_id)

    # Render report
    report = render_report(
        stats=stats,
        classifications=classifications,
        nl_analysis=nl_analysis,
        cap_agg=cap_agg,
        data_source_path=str(retail_dir),
        unsupported_tool_info=unsupported_tool_info,
        missing_tool_info=missing_tool_info,
        phase12_live_evidence=load_phase12_live_evidence(),
        phase12_additional_live_evidence=[
            evidence
            for evidence in [
                load_phase12_live_evidence(subset="tau_phase12_nl_evidence")
            ]
            if evidence is not None
        ],
    )
    return report


def main() -> None:
    """CLI entry point: run analysis and write report to docs/."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Analyze tau3 retail task space and generate a report."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also write structured classifications to artifacts/phase9a/",
    )
    args = parser.parse_args()

    config = resolve_config()
    try:
        report = analyze_and_report(config)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Write report
    report_path = Path("docs/tau-task-space-analysis.md")
    report_path.write_text(report, encoding="utf-8")
    print(f"Report written to {report_path}")

    # Optional JSON output
    if args.json:
        json_dir = Path("artifacts/phase9a")
        json_dir.mkdir(parents=True, exist_ok=True)
        # Re-run classification to get the data for JSON
        retail_dir = _resolve_tau3_retail_dir(config)
        tasks = load_tasks(retail_dir)
        splits = load_splits(retail_dir)
        classifications = [classify_task(t, splits) for t in tasks]
        json_path = json_dir / "task_classifications.json"
        json_path.write_text(
            json.dumps(
                [c.__dict__ for c in classifications],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"Classifications written to {json_path}")


if __name__ == "__main__":
    main()
