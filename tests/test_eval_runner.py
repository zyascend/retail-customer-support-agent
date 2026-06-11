import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import resolve_config
from app.eval.cases import get_cases
from app.eval.runner import CuratedEvalRunner, classify_failure


class CuratedEvalTests(unittest.TestCase):
    def test_curated_subset_contains_mvp_categories(self):
        cases = get_cases("curated_mvp")
        categories = {case.category for case in cases}

        self.assertEqual(len(cases), 11)
        self.assertEqual(
            categories,
            {
                "lookup",
                "cancel",
                "modify_address",
                "return",
                "exchange",
                "transfer",
                "confirmation",
                "guard",
            },
        )

    def test_classify_failure_detects_auth_failure_first(self):
        case = get_cases("curated_mvp")[0]

        label = classify_failure(
            case=case,
            authenticated_user_id="wrong_user",
            final_intent=case.expected_intent,
            write_locks=[],
            actual_order_status=None,
            assistant_messages=[],
            tool_names=case.expected_tool_names,
            guard_block_reasons=[],
            tool_errors=0,
            guard_blocks=0,
            pending_action=False,
            llm_errors=0,
            confirmation_status="not_required",
        )

        self.assertEqual(label, "auth_failure")

    def test_classify_failure_accepts_expected_guard_block(self):
        case = next(
            item
            for item in get_cases("curated_mvp")
            if item.case_id == "block_cancel_processed_order"
        )

        label = classify_failure(
            case=case,
            authenticated_user_id=case.expected_user_id,
            final_intent=case.expected_intent,
            write_locks=[],
            actual_order_status=case.expected_order_status,
            assistant_messages=[],
            tool_names=case.expected_tool_names,
            guard_block_reasons=[case.expected_guard_block_reason],
            tool_errors=0,
            guard_blocks=1,
            pending_action=False,
            llm_errors=0,
            confirmation_status=case.expected_confirmation_status,
        )

        self.assertIsNone(label)

    def test_curated_eval_runner_writes_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "AGENT_LLM_TIMEOUT_SECONDS": "30",
                    "AGENT_LLM_MAX_RETRIES": "2",
                },
            ):
                config = resolve_config(artifact_dir=tmp)
                summary = CuratedEvalRunner(
                    config=config,
                    artifact_dir=Path(tmp),
                ).run(subset="curated_mvp", trials=1)
            payload = json.loads(
                Path(summary.result_artifact_path).read_text(encoding="utf-8")
            )

        self.assertEqual(summary.case_count, 11)
        self.assertEqual(summary.passed_count, 11)
        self.assertEqual(summary.pass_rate, 1.0)
        self.assertEqual(payload["passed_count"], 11)
        self.assertEqual(len(payload["results"]), 11)
        self.assertIn("prompt_metadata", payload)
        self.assertIn("dataset_db_path", payload)
        self.assertEqual(payload["llm_timeout_seconds"], 30.0)
        self.assertEqual(payload["llm_max_retries"], 2)
        self.assertIsInstance(payload["results"][0]["duration_seconds"], float)
        self.assertGreaterEqual(payload["results"][0]["duration_seconds"], 0.0)

    def test_curated_eval_runner_reports_progress(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            CuratedEvalRunner(
                config=config,
                artifact_dir=Path(tmp),
                progress_callback=lambda event, result: events.append(
                    (event, result.case_id, result.trial)
                ),
            ).run(subset="curated_mvp", trials=1)

        self.assertEqual(events[0], ("start", "lookup_pending_order", 0))
        self.assertEqual(events[1][0], "finish")
        self.assertEqual(len(events), 22)


if __name__ == "__main__":
    unittest.main()
