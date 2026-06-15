"""Tests for tau task analyzer."""

import json
import tempfile
from pathlib import Path

import pytest

from app.analysis.tau_task_analyzer import (
    NLAssertionItem,
    Phase12LiveEvidence,
    TaskClassification,
    TaskSpaceStats,
    _resolve_tau3_retail_dir,
    aggregate_by_capability,
    analyze_and_report,
    analyze_nl_assertions,
    analyze_phase12_gap,
    build_phase12_coverage_rung_plan,
    classify_task,
    compute_phase12_coverage_rungs,
    compute_task_space_stats,
    load_phase12_live_evidence,
    load_splits,
    load_tasks,
    render_report,
    select_phase12_next_candidates,
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


def test_phase12_gap_analysis_classifies_supported_as_ready():
    classification = TaskClassification(
        task_id="1",
        split="train",
        status="supported",
        tools_used=["get_order_details", "cancel_pending_order"],
        missing_tools=[],
        has_nl_assertion=False,
        has_policy_keywords=False,
    )

    gap = analyze_phase12_gap(classification)

    assert gap.category == "ready"
    assert gap.can_expand_without_runtime_parser is True
    assert gap.priority == 0


def test_phase12_gap_analysis_prioritizes_schema_gap_before_prompt_gap():
    classification = TaskClassification(
        task_id="2",
        split="test",
        status="partial",
        subcategory="partial_multi",
        tools_used=["get_order_details", "calculate"],
        missing_tools=["calculate"],
        has_nl_assertion=True,
        has_policy_keywords=False,
    )

    gap = analyze_phase12_gap(classification)

    assert gap.category == "schema_gap"
    assert gap.blocking_reasons == ["missing auxiliary/schema support: calculate"]
    assert gap.priority == 10


def test_phase12_gap_analysis_marks_auxiliary_only_gap_as_schema_ready():
    classification = TaskClassification(
        task_id="49",
        split="test",
        status="partial",
        subcategory="partial_missing_tool",
        tools_used=["calculate", "exchange_delivered_order_items"],
        missing_tools=["calculate"],
        has_nl_assertion=False,
        has_policy_keywords=False,
    )

    gap = analyze_phase12_gap(classification)

    assert gap.category == "schema_ready"
    assert gap.blocking_reasons == ["auxiliary tools already exposed: calculate"]
    assert gap.priority == 5


def test_phase12_gap_analysis_marks_policy_tasks_as_guard_review():
    classification = TaskClassification(
        task_id="3",
        split="train",
        status="partial",
        subcategory="partial_policy_gap",
        tools_used=["get_order_details", "return_delivered_order_items"],
        has_policy_keywords=True,
    )

    gap = analyze_phase12_gap(classification)

    assert gap.category == "guard_policy_review"
    assert gap.can_expand_without_runtime_parser is True


def test_phase12_coverage_rungs_report_current_and_targets():
    classifications = [
        TaskClassification(task_id=str(i), split="train", status="supported")
        for i in range(42)
    ]

    rungs = compute_phase12_coverage_rungs(classifications, total_supported_target=69)

    assert rungs["current_supported"] == 42
    assert rungs["target_total"] == 69
    assert rungs["stable_40_plus"] is True
    assert rungs["stable_50_plus"] is False
    assert rungs["stable_55_plus"] is False
    assert rungs["remaining_to_50"] == 8


def test_phase12_next_candidates_prioritize_schema_then_guard_then_prompt():
    classifications = [
        TaskClassification(
            task_id="10",
            split="train",
            status="partial",
            subcategory="partial_nl_assertion",
            tools_used=["get_order_details"],
            has_nl_assertion=True,
        ),
        TaskClassification(
            task_id="11",
            split="train",
            status="partial",
            subcategory="partial_missing_tool",
            tools_used=["calculate"],
            missing_tools=["calculate"],
        ),
        TaskClassification(
            task_id="12",
            split="test",
            status="partial",
            subcategory="partial_policy_gap",
            tools_used=["return_delivered_order_items"],
            has_policy_keywords=True,
        ),
    ]

    candidates = select_phase12_next_candidates(classifications, limit=3)

    assert [candidate.task_id for candidate in candidates] == ["11", "12", "10"]
    assert [candidate.category for candidate in candidates] == [
        "schema_ready",
        "guard_policy_review",
        "prompt_or_response_gap",
    ]


def test_phase12_coverage_rung_plan_reports_next_target_capacity():
    classifications = [
        TaskClassification(task_id=str(i), split="train", status="supported")
        for i in range(42)
    ]
    classifications.extend(
        TaskClassification(
            task_id=str(100 + i),
            split="test",
            status="partial",
            subcategory="partial_missing_tool",
            missing_tools=["calculate"],
            tools_used=["calculate"],
        )
        for i in range(6)
    )

    plan = build_phase12_coverage_rung_plan(classifications)

    assert plan["current_rung"] == "stable_40_plus"
    assert plan["next_target"] == 50
    assert plan["remaining_to_next"] == 8
    assert plan["safe_candidate_count"] == 6
    assert plan["projected_supported_after_safe_candidates"] == 48
    assert plan["can_reach_next_with_safe_candidates"] is False


def test_phase12_coverage_rung_plan_marks_top_rung_complete():
    classifications = [
        TaskClassification(task_id=str(i), split="train", status="supported")
        for i in range(57)
    ]

    plan = build_phase12_coverage_rung_plan(classifications)

    assert plan["current_rung"] == "stable_55_plus"
    assert plan["next_target"] is None
    assert plan["remaining_to_next"] == 0
    assert plan["can_reach_next_with_safe_candidates"] is True


def test_load_phase12_live_evidence_selects_latest_passing_schema_ready_run(tmp_path):
    eval_runs = tmp_path / "phase2" / "eval_runs"
    eval_runs.mkdir(parents=True)
    older = {
        "created_at": "2026-06-15T07:00:00+00:00",
        "eval_run_id": "eval-old",
        "subset": "tau_phase12_schema_ready",
        "eval_backend": "live",
        "case_count": 2,
        "passed_count": 1,
        "pass_rate": 0.5,
        "metrics": {
            "tool_call_success_rate": 0.5,
            "mutation_error_rate": 0.0,
        },
    }
    latest = {
        "created_at": "2026-06-15T08:00:00+00:00",
        "eval_run_id": "eval-new",
        "subset": "tau_phase12_schema_ready",
        "eval_backend": "live",
        "case_count": 2,
        "passed_count": 2,
        "pass_rate": 1.0,
        "metrics": {
            "tool_call_success_rate": 0.95,
            "mutation_error_rate": 0.0,
        },
        "results": [
            {"case_id": "tau_49", "passed": True},
            {"case_id": "tau_61", "passed": True},
        ],
    }
    unrelated = {
        "created_at": "2026-06-15T09:00:00+00:00",
        "eval_run_id": "eval-other",
        "subset": "curated_mvp",
        "eval_backend": "live",
        "case_count": 11,
        "passed_count": 11,
        "pass_rate": 1.0,
        "metrics": {
            "tool_call_success_rate": 1.0,
            "mutation_error_rate": 0.0,
        },
    }
    (eval_runs / "eval-old.json").write_text(json.dumps(older), encoding="utf-8")
    (eval_runs / "eval-new.json").write_text(json.dumps(latest), encoding="utf-8")
    (eval_runs / "eval-other.json").write_text(json.dumps(unrelated), encoding="utf-8")

    evidence = load_phase12_live_evidence(tmp_path / "phase2")

    assert evidence is not None
    assert evidence.eval_run_id == "eval-new"
    assert evidence.subset == "tau_phase12_schema_ready"
    assert evidence.passed_count == 2
    assert evidence.case_count == 2
    assert evidence.promoted_task_ids == ["49", "61"]
    assert evidence.promotable is True


def test_load_phase12_live_evidence_summarizes_non_promotable_failures(tmp_path):
    eval_runs = tmp_path / "phase2" / "eval_runs"
    eval_runs.mkdir(parents=True)
    payload = {
        "created_at": "2026-06-15T09:00:00+00:00",
        "eval_run_id": "eval-nl",
        "subset": "tau_phase12_nl_evidence",
        "eval_backend": "live",
        "case_count": 9,
        "passed_count": 0,
        "pass_rate": 0.0,
        "metrics": {
            "tool_call_success_rate": 0.8243,
            "mutation_error_rate": 0.0,
        },
        "results": [
            {"case_id": "tau_16", "passed": False, "failure_label": "response_mismatch"},
            {"case_id": "tau_21", "passed": False, "failure_label": "tool_exception"},
            {"case_id": "tau_46", "passed": False, "failure_label": "wrong_tool"},
        ],
    }
    (eval_runs / "eval-nl.json").write_text(json.dumps(payload), encoding="utf-8")

    evidence = load_phase12_live_evidence(
        tmp_path / "phase2",
        subset="tau_phase12_nl_evidence",
    )

    assert evidence is not None
    assert evidence.eval_run_id == "eval-nl"
    assert evidence.promotable is False
    assert evidence.promoted_task_ids == []
    assert evidence.failure_labels == {
        "response_mismatch": 1,
        "tool_exception": 1,
        "wrong_tool": 1,
    }


def test_phase12_promoted_live_evidence_updates_effective_coverage():
    classifications = [
        TaskClassification(task_id="1", split="train", status="supported"),
        TaskClassification(task_id="2", split="train", status="supported"),
        TaskClassification(
            task_id="49",
            split="test",
            status="partial",
            missing_tools=["calculate"],
            tools_used=["calculate"],
        ),
        TaskClassification(
            task_id="61",
            split="test",
            status="partial",
            missing_tools=["calculate"],
            tools_used=["calculate"],
        ),
        TaskClassification(
            task_id="16",
            split="test",
            status="partial",
            missing_tools=["calculate"],
            tools_used=["calculate"],
            has_nl_assertion=True,
        ),
    ]

    rungs = compute_phase12_coverage_rungs(
        classifications,
        total_supported_target=5,
        promoted_task_ids=["49", "61"],
    )
    candidates = select_phase12_next_candidates(
        classifications,
        promoted_task_ids=["49", "61"],
    )

    assert rungs["current_supported"] == 2
    assert rungs["live_promoted_count"] == 2
    assert rungs["effective_supported"] == 4
    assert rungs["remaining_to_all_tasks"] == 1
    assert [candidate.task_id for candidate in candidates] == ["16"]


def test_render_report_includes_phase12_live_evidence(tmp_path):
    eval_runs = tmp_path / "phase2" / "eval_runs"
    eval_runs.mkdir(parents=True)
    payload = {
        "created_at": "2026-06-15T08:00:00+00:00",
        "eval_run_id": "eval-live",
        "subset": "tau_phase12_schema_ready",
        "eval_backend": "live",
        "case_count": 2,
        "passed_count": 2,
        "pass_rate": 1.0,
        "metrics": {
            "tool_call_success_rate": 0.95,
            "mutation_error_rate": 0.0,
        },
        "results": [
            {"case_id": "tau_49", "passed": True},
            {"case_id": "tau_61", "passed": True},
        ],
    }
    (eval_runs / "eval-live.json").write_text(json.dumps(payload), encoding="utf-8")
    evidence = load_phase12_live_evidence(tmp_path / "phase2")
    stats = TaskSpaceStats(total_tasks=1, train_count=1)
    classifications = [
        TaskClassification(task_id="49", split="test", status="partial")
    ]

    report = render_report(
        stats=stats,
        classifications=classifications,
        nl_analysis={
            "total_tasks_with_nl": 0,
            "total_assertions": 0,
            "by_category": {},
            "sample_by_category": {},
            "items": [],
        },
        cap_agg={},
        data_source_path="/fake/path",
        unsupported_tool_info={},
        missing_tool_info={},
        phase12_live_evidence=evidence,
    )

    assert "### 9.3 Phase 12 Live Evidence" in report
    assert "| eval_run_id | eval-live |" in report
    assert "| subset | tau_phase12_schema_ready |" in report
    assert "| promoted_task_ids | 49, 61 |" in report
    assert "| promotable | True |" in report


def test_render_report_includes_additional_phase12_live_evidence():
    stats = TaskSpaceStats(total_tasks=1, train_count=1)
    classifications = [
        TaskClassification(task_id="16", split="train", status="partial")
    ]
    primary = Phase12LiveEvidence(
        eval_run_id="eval-schema",
        subset="tau_phase12_schema_ready",
        eval_backend="live",
        created_at="2026-06-15T08:00:00+00:00",
        passed_count=2,
        case_count=2,
        pass_rate=1.0,
        tool_call_success_rate=0.95,
        mutation_error_rate=0.0,
        promotable=True,
        promoted_task_ids=["49", "61"],
    )
    nl_evidence = Phase12LiveEvidence(
        eval_run_id="eval-nl",
        subset="tau_phase12_nl_evidence",
        eval_backend="live",
        created_at="2026-06-15T09:00:00+00:00",
        passed_count=0,
        case_count=9,
        pass_rate=0.0,
        tool_call_success_rate=0.8243,
        mutation_error_rate=0.0,
        promotable=False,
        failure_labels={
            "response_mismatch": 5,
            "tool_exception": 3,
            "wrong_tool": 1,
        },
    )

    report = render_report(
        stats=stats,
        classifications=classifications,
        nl_analysis={
            "total_tasks_with_nl": 0,
            "total_assertions": 0,
            "by_category": {},
            "sample_by_category": {},
            "items": [],
        },
        cap_agg={},
        data_source_path="/fake/path",
        unsupported_tool_info={},
        missing_tool_info={},
        phase12_live_evidence=primary,
        phase12_additional_live_evidence=[nl_evidence],
    )

    assert "Additional Phase 12 Evidence" in report
    assert "| tau_phase12_nl_evidence | eval-nl | 0/9 | 0.0000 | False |" in report
    assert "response_mismatch=5, tool_exception=3, wrong_tool=1" in report


def test_render_report_produces_markdown_with_all_sections():
    """render_report produces Markdown with all 8 required sections."""
    stats = TaskSpaceStats(
        total_tasks=2,
        train_count=1,
        test_count=1,
        reward_basis_distribution={"DB + NL_ASSERTION": 2},
        action_count_min=1,
        action_count_max=3,
        action_count_avg=2.0,
        tool_frequencies={"get_order_details": 2, "cancel_pending_order": 1},
    )
    classifications = [
        TaskClassification(
            task_id="0", split="train", status="supported",
            tools_used=["get_order_details", "cancel_pending_order"],
            action_count=2, reward_basis=["DB", "NL_ASSERTION"],
            notes="All good.",
        ),
        TaskClassification(
            task_id="1", split="test", status="partial",
            subcategory="partial_nl_assertion",
            tools_used=["get_order_details"], missing_tools=[],
            has_nl_assertion=True, action_count=1,
            reward_basis=["DB", "NL_ASSERTION"],
            notes="has NL assertions",
        ),
    ]
    nl_analysis = {
        "total_tasks_with_nl": 1,
        "total_assertions": 1,
        "by_category": {"must_say": 1},
        "sample_by_category": {"must_say": ["Agent should tell the user something."]},
        "items": [
            NLAssertionItem(
                task_id="1", text="Agent should tell the user something.",
                category="must_say",
            ),
        ],
    }
    cap_agg = {
        "cancel": {"total": 1, "supported": 1, "partial": 0, "unsupported": 0, "train": 1, "test": 0},
        "lookup": {"total": 1, "supported": 0, "partial": 1, "unsupported": 0, "train": 0, "test": 1},
    }

    report = render_report(
        stats=stats,
        classifications=classifications,
        nl_analysis=nl_analysis,
        cap_agg=cap_agg,
        data_source_path="/fake/path",
        unsupported_tool_info={"calculate": {"count": 0, "task_ids": []}},
        missing_tool_info={},
    )

    # Check all required section headers
    assert "## 1. 概述" in report
    assert "## 2. Task 空间统计" in report
    assert "## 3. 工具覆盖分析" in report
    assert "## 4. 分类结果" in report
    assert "## 5. NL Assertion 分析" in report
    assert "## 6. 按 Capability 维度聚合" in report
    assert "## 7. 已知问题 Task" in report
    assert "## 8. Phase 9 首批 Ingestion 建议" in report
    assert "## 9. Phase 12 Coverage Expansion Queue" in report
    assert "stable_40_plus" in report
    assert "current_rung" in report
    assert "next_target" in report
    assert "safe_candidate_count" in report
    assert "schema_ready_count" in report
    assert "Next candidates" in report

    # Check key data points appear
    assert "2" in report  # total tasks
    assert "supported" in report
    assert "partial_nl_assertion" in report


def test_analyze_and_report_runs_on_real_data():
    """analyze_and_report runs against real tau3 data and returns non-empty report."""
    try:
        report = analyze_and_report()
    except FileNotFoundError:
        pytest.skip("tau3 retail data not available")
    assert len(report) > 1000
    assert "# Tau Retail Task Space Analysis" in report
    assert "## 8. Phase 9 首批 Ingestion 建议" in report

    # Verify all 114 tasks appear in the report
    task_id_pattern = sum(1 for line in report.splitlines() if line.startswith("| "))
    assert task_id_pattern > 100  # at least the full task list rows
