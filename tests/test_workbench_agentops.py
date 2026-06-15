from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.workbench.agentops import AgentOpsService
from app.workbench.errors import WorkbenchAPIError


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class AgentOpsServiceTests(unittest.TestCase):
    def test_list_reports_returns_latest_report_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_json(
                artifact_dir / "reports" / "eval-run-a.json",
                {
                    "eval_run_id": "eval-run-a",
                    "created_at": "2026-06-15T01:00:00+00:00",
                    "eval_backend": "live",
                    "model": "deepseek-v4-flash",
                    "baseline_metadata": {
                        "provider": "deepseek",
                        "subset": "live_smoke_core",
                    },
                    "results": [{"passed": True}, {"passed": False}],
                },
            )
            _write_json(
                artifact_dir / "reports" / "eval-run-b.json",
                {
                    "eval_run_id": "eval-run-b",
                    "created_at": "2026-06-15T02:00:00+00:00",
                    "eval_backend": "scripted_offline_demo",
                    "model": "deepseek-v4-flash",
                    "baseline_metadata": {
                        "provider": "deepseek",
                        "subset": "curated_mvp",
                    },
                    "results": [{"passed": False}],
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)
            reports = service.list_reports()

        self.assertEqual([report.run_id for report in reports], ["eval-run-b", "eval-run-a"])
        self.assertEqual(reports[0].failure_case_count, 1)
        self.assertEqual(reports[0].fail_count, 1)
        self.assertEqual(reports[0].subset, "curated_mvp")

    def test_get_report_detail_raises_structured_error_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = AgentOpsService(artifact_dir=Path(tmp))

            with self.assertRaises(WorkbenchAPIError) as context:
                service.get_report("missing-run")

        self.assertEqual(context.exception.code, "report_not_found")
        self.assertEqual(context.exception.status_code, 404)

    def test_get_report_rejects_path_traversal_run_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = AgentOpsService(artifact_dir=Path(tmp))

            with self.assertRaises(WorkbenchAPIError) as context:
                service.get_report("../secret")

        self.assertEqual(context.exception.code, "invalid_report_id")
        self.assertEqual(context.exception.status_code, 400)

    def test_list_reports_skips_malformed_report_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_json(
                artifact_dir / "reports" / "valid.json",
                {
                    "eval_run_id": "valid",
                    "created_at": "2026-06-15T03:00:00+00:00",
                    "eval_backend": "live",
                    "model": "deepseek-v4-flash",
                    "baseline_metadata": {"provider": "deepseek", "subset": "curated_mvp"},
                    "results": [{"passed": True}, {"passed": False}],
                },
            )
            _write_text(artifact_dir / "reports" / "broken.json", "{not-json")

            service = AgentOpsService(artifact_dir=artifact_dir)
            reports = service.list_reports()

        self.assertEqual([report.run_id for report in reports], ["valid"])

    def test_get_report_raises_structured_error_for_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_text(artifact_dir / "reports" / "broken.json", "{not-json")
            service = AgentOpsService(artifact_dir=artifact_dir)

            with self.assertRaises(WorkbenchAPIError) as context:
                service.get_report("broken")

        self.assertEqual(context.exception.code, "artifact_parse_error")
        self.assertEqual(context.exception.status_code, 500)

    def test_get_report_raises_structured_error_for_missing_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_json(
                artifact_dir / "reports" / "missing-fields.json",
                {
                    "created_at": "2026-06-15T03:00:00+00:00",
                    "results": [],
                },
            )
            service = AgentOpsService(artifact_dir=artifact_dir)

            with self.assertRaises(WorkbenchAPIError) as context:
                service.get_report("missing-fields")

        self.assertEqual(context.exception.code, "artifact_parse_error")
        self.assertEqual(context.exception.status_code, 500)

    def test_get_report_raises_structured_error_for_malformed_nested_case_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_json(
                artifact_dir / "reports" / "bad-case.json",
                {
                    "eval_run_id": "bad-case",
                    "created_at": "2026-06-15T03:00:00+00:00",
                    "eval_backend": "live",
                    "model": "deepseek-v4-flash",
                    "baseline_metadata": {"provider": "deepseek", "subset": "curated_mvp"},
                    "results": [
                        {
                            "case_id": "c1",
                            "passed": False,
                            "trace_artifact_path": {"x": 1},
                        }
                    ],
                },
            )
            service = AgentOpsService(artifact_dir=artifact_dir)

            with self.assertRaises(WorkbenchAPIError) as context:
                service.get_report("bad-case")

        self.assertEqual(context.exception.code, "artifact_parse_error")
        self.assertEqual(context.exception.status_code, 500)

    def test_get_case_detail_merges_report_and_trace_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            trace_path = artifact_dir / "traces" / "eval-run-a" / "runs" / "case-a.json"
            _write_json(
                artifact_dir / "reports" / "eval-run-a.json",
                {
                    "eval_run_id": "eval-run-a",
                    "created_at": "2026-06-15T01:00:00+00:00",
                    "eval_backend": "live",
                    "model": "deepseek-v4-flash",
                    "baseline_metadata": {"provider": "deepseek", "subset": "live_smoke_core"},
                    "results": [
                        {
                            "case_id": "case-a",
                            "passed": False,
                            "failure_label": "wrong_tool",
                            "failure_category": "prompt_gap",
                            "trace_artifact_path": str(trace_path),
                            "expected_actual_diff": {
                                "order_status": {"expected": "cancelled", "actual": "pending"}
                            },
                        }
                    ],
                },
            )
            _write_json(
                trace_path,
                {
                    "run_id": "case-a",
                    "messages": [
                        {"role": "user", "content": "cancel order #W1"},
                        {"role": "assistant", "content": "I need confirmation."},
                    ],
                    "metadata": {
                        "llm_responses": [
                            {
                                "assistant_content": "",
                                "finish_reason": "tool_calls",
                                "token_usage": {"total_tokens": 42},
                                "tool_calls": [
                                    {
                                        "tool_name": "cancel_pending_order",
                                        "arguments": {"order_id": "#W1"},
                                        "id": "call_1",
                                        "raw_arguments": "{\"order_id\":\"#W1\"}",
                                    }
                                ],
                            }
                        ]
                    },
                    "tool_calls": [
                        {
                            "tool_name": "cancel_pending_order",
                            "arguments": {"order_id": "#W1"},
                            "tool_kind": "write",
                            "status": "blocked",
                            "error": "explicit_confirmation_required",
                            "block_context": {
                                "confirmation_required": True,
                                "summary": "Cancel order #W1.",
                            },
                            "observation": {
                                "block_reason": "explicit_confirmation_required"
                            },
                        }
                    ],
                    "steps": [
                        {
                            "node": "write_action_guard",
                            "status": "ok",
                            "detail": {
                                "tool_name": "cancel_pending_order",
                                "status": "blocked",
                                "block_reason": "explicit_confirmation_required",
                                "block_context": {
                                    "confirmation_required": True,
                                    "summary": "Cancel order #W1.",
                                },
                            },
                        }
                    ],
                    "final_state": {
                        "auth_method": "email",
                        "authenticated_user_id": "user-1",
                        "compat": {
                            "current_intent": "unknown",
                            "slots": {},
                            "policy_decision": None,
                        },
                        "confirmation_status": "required",
                        "pending_action": {"action_name": "cancel_pending_order"},
                        "session_id": "case-a",
                        "task_id": "case-a",
                        "termination_reason": "awaiting_confirmation",
                        "write_locks": [],
                    },
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)
            detail = service.get_case("eval-run-a", "case-a")

        self.assertEqual(detail.failure_label, "wrong_tool")
        self.assertEqual(detail.root_cause, "prompt_gap")
        self.assertEqual(
            detail.guard_context,
            [{"confirmation_required": True, "summary": "Cancel order #W1."}],
        )
        self.assertEqual(detail.db_assertion_diff["order_status"]["actual"], "pending")

    def test_get_trace_by_path_returns_timeline_and_redacted_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            trace_path = artifact_dir / "traces" / "trace-a.json"
            _write_json(
                trace_path,
                {
                    "run_id": "trace-a",
                    "messages": [{"role": "user", "content": "email me at alex@example.com"}],
                    "metadata": {"llm_responses": []},
                    "tool_calls": [],
                    "steps": [],
                    "final_state": {},
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)
            detail = service.get_trace_by_path(str(trace_path))

        self.assertEqual(detail.trace_id, "trace-a")
        self.assertEqual(detail.timeline[0]["kind"], "message")
        self.assertEqual(
            detail.turns[0]["messages"][0]["content"], "email me at [redacted-email]"
        )
