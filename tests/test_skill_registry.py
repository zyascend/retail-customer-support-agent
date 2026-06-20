from __future__ import annotations

from app.eval.metrics import compute_skill_metrics
from app.eval.runner import EvalCaseResult
from app.eval.baseline import build_baseline_metadata
from app.config import resolve_config
from app.skills.registry import SKILL_REGISTRY, build_skill_guidance_for_prompt, skill_hashes


def test_skill_registry_covers_all_write_skills() -> None:
    skill_ids = {skill.skill_id for skill in SKILL_REGISTRY}

    assert len(SKILL_REGISTRY) == 8
    assert skill_ids == {
        "cancel_order",
        "modify_address",
        "modify_items",
        "modify_payment",
        "return_items",
        "exchange_items",
        "modify_user_address",
        "modify_shipping",
    }


def test_build_skill_guidance_for_prompt_includes_titles_and_examples() -> None:
    guidance = build_skill_guidance_for_prompt()

    assert "### Cancel Order" in guidance
    assert "### Modify Shipping Method" in guidance
    assert "cancel_pending_order" in guidance
    assert "modify_pending_order_shipping_method" in guidance
    assert "Tool succeeds → call `calculate(...)` for the total refund" in guidance


def test_skill_hashes_cover_all_skills() -> None:
    hashes = skill_hashes()

    assert set(hashes) == {skill.skill_id for skill in SKILL_REGISTRY}
    assert all(isinstance(value, str) and value for value in hashes.values())


def test_compute_skill_metrics_groups_results_by_skill() -> None:
    results = [
        EvalCaseResult(
            run_id="r1",
            session_id="s1",
            case_id="c1",
            category="cancel",
            skill_id="cancel_order",
            trial=0,
            passed=True,
            failure_label=None,
            trace_artifact_path="",
            authenticated_user_id=None,
            final_intent="",
            termination_reason=None,
            expected_write_lock=None,
        ),
        EvalCaseResult(
            run_id="r1",
            session_id="s2",
            case_id="c2",
            category="cancel",
            skill_id="cancel_order",
            trial=0,
            passed=False,
            failure_label="guard_blocked",
            trace_artifact_path="",
            authenticated_user_id=None,
            final_intent="",
            termination_reason=None,
            expected_write_lock=None,
        ),
        EvalCaseResult(
            run_id="r1",
            session_id="s3",
            case_id="c3",
            category="exchange",
            skill_id="exchange_items",
            trial=0,
            passed=True,
            failure_label=None,
            trace_artifact_path="",
            authenticated_user_id=None,
            final_intent="",
            termination_reason=None,
            expected_write_lock=None,
        ),
    ]

    metrics = compute_skill_metrics(results)

    assert metrics["cancel_order"]["result_count"] == 2
    assert metrics["cancel_order"]["passed_count"] == 1
    assert metrics["cancel_order"]["pass_rate"] == 0.5
    assert metrics["cancel_order"]["failure_labels"]["guard_blocked"] == 1
    assert metrics["exchange_items"]["result_count"] == 1
    assert metrics["exchange_items"]["pass_rate"] == 1.0


def test_baseline_metadata_includes_skill_hashes() -> None:
    metadata = build_baseline_metadata(
        config=resolve_config(),
        subset="curated_mvp",
        eval_backend="scripted",
        live=False,
        require_llm=False,
    )

    assert "skill_hashes" in metadata
    assert set(metadata["skill_hashes"]) == {skill.skill_id for skill in SKILL_REGISTRY}
