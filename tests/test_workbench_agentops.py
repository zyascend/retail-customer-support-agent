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
                    "eval_backend": "live",
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
        self.assertEqual(detail.trace_detail.trace_id, "case-a")
        self.assertEqual(
            Path(detail.trace_detail.trace_artifact_path).resolve(), trace_path.resolve()
        )

    def test_get_case_detail_resolves_relative_report_trace_path(self):
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
                            "trace_artifact_path": str(trace_path.relative_to(artifact_dir)),
                        }
                    ],
                },
            )
            _write_json(
                trace_path,
                {
                    "run_id": "case-a",
                    "messages": [{"role": "user", "content": "hi"}],
                    "metadata": {"llm_responses": []},
                    "tool_calls": [],
                    "steps": [],
                    "final_state": {},
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)
            detail = service.get_case("eval-run-a", "case-a")

        self.assertEqual(detail.trace_artifact_path, "traces/eval-run-a/runs/case-a.json")
        self.assertEqual(
            Path(detail.trace_detail.trace_artifact_path).resolve(), trace_path.resolve()
        )
        self.assertEqual(detail.user_messages, ["hi"])

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

    def test_get_trace_by_path_rejects_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            service = AgentOpsService(artifact_dir=artifact_dir)

            with self.assertRaises(WorkbenchAPIError) as context:
                service.get_trace_by_path("traces/trace-a.json")

        self.assertEqual(context.exception.code, "invalid_trace_path")
        self.assertEqual(context.exception.status_code, 400)

    def test_get_trace_by_path_splits_multiple_user_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            trace_path = artifact_dir / "traces" / "trace-b.json"
            _write_json(
                trace_path,
                {
                    "run_id": "trace-b",
                    "messages": [
                        {"role": "user", "content": "my email is alex@example.com"},
                        {"role": "assistant", "content": "I found your account."},
                        {"role": "user", "content": "cancel order #W2"},
                        {"role": "assistant", "content": "I can help with that."},
                    ],
                    "metadata": {
                        "llm_responses": [
                            {"assistant_content": "I found your account.", "finish_reason": "stop"},
                            {"assistant_content": "I can help with that.", "finish_reason": "stop"},
                        ]
                    },
                    "tool_calls": [],
                    "steps": [],
                    "final_state": {},
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)
            detail = service.get_trace_by_path(str(trace_path))

        self.assertEqual(len(detail.turns), 2)
        self.assertEqual(detail.turns[0]["messages"][0]["content"], "my email is [redacted-email]")
        self.assertEqual(detail.turns[0]["messages"][1]["content"], "I found your account.")
        self.assertEqual(detail.turns[1]["messages"][0]["content"], "cancel order #W2")
        self.assertEqual(detail.turns[1]["messages"][1]["content"], "I can help with that.")
        self.assertEqual(detail.turns[0]["llm_responses"][0]["assistant_content"], "I found your account.")
        self.assertEqual(detail.turns[1]["llm_responses"][0]["assistant_content"], "I can help with that.")

    def test_get_trace_by_path_keeps_multiple_llm_responses_in_same_user_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            trace_path = artifact_dir / "traces" / "trace-multi-llm.json"
            _write_json(
                trace_path,
                {
                    "run_id": "trace-multi-llm",
                    "messages": [
                        {"role": "user", "content": "cancel order #W9"},
                        {"role": "assistant", "content": "Let me check that."},
                        {"role": "assistant", "content": "I need confirmation before canceling."},
                        {"role": "user", "content": "yes, confirm it"},
                        {"role": "assistant", "content": "Confirmed."},
                    ],
                    "metadata": {
                        "llm_responses": [
                            {"assistant_content": "Let me check that.", "finish_reason": "tool_calls"},
                            {
                                "assistant_content": "I need confirmation before canceling.",
                                "finish_reason": "stop",
                            },
                            {"assistant_content": "Confirmed.", "finish_reason": "stop"},
                        ]
                    },
                    "tool_calls": [],
                    "steps": [
                        {"node": "receive_message", "status": "ok", "detail": {}},
                        {"node": "policy_reasoner", "status": "ok", "detail": {}},
                        {"node": "write_action_guard", "status": "ok", "detail": {}},
                        {"node": "receive_message", "status": "ok", "detail": {}},
                        {"node": "policy_reasoner", "status": "ok", "detail": {}},
                    ],
                    "final_state": {},
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)
            detail = service.get_trace_by_path(str(trace_path))

        self.assertEqual(len(detail.turns), 2)
        self.assertEqual(len(detail.turns[0]["llm_responses"]), 2)
        self.assertEqual(
            [item["assistant_content"] for item in detail.turns[0]["llm_responses"]],
            ["Let me check that.", "I need confirmation before canceling."],
        )
        self.assertEqual(
            [item["assistant_content"] for item in detail.turns[1]["llm_responses"]],
            ["Confirmed."],
        )

    def test_get_trace_by_path_allows_runtime_turn_without_llm_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            trace_path = artifact_dir / "traces" / "trace-empty-runtime-turn.json"
            _write_json(
                trace_path,
                {
                    "run_id": "trace-empty-runtime-turn",
                    "messages": [
                        {"role": "user", "content": "cancel order #W9"},
                        {"role": "assistant", "content": "Let me check that."},
                        {"role": "assistant", "content": "I need confirmation before canceling."},
                        {"role": "user", "content": "actually never mind"},
                    ],
                    "metadata": {
                        "llm_responses": [
                            {"assistant_content": "Let me check that.", "finish_reason": "tool_calls"},
                            {
                                "assistant_content": "I need confirmation before canceling.",
                                "finish_reason": "stop",
                            },
                        ]
                    },
                    "tool_calls": [],
                    "steps": [
                        {"node": "receive_message", "status": "ok", "detail": {}},
                        {"node": "policy_reasoner", "status": "ok", "detail": {}},
                        {"node": "write_action_guard", "status": "ok", "detail": {}},
                        {"node": "receive_message", "status": "ok", "detail": {}},
                    ],
                    "final_state": {},
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)
            detail = service.get_trace_by_path(str(trace_path))

        self.assertEqual(len(detail.turns), 2)
        self.assertEqual(
            [item["assistant_content"] for item in detail.turns[0]["llm_responses"]],
            ["Let me check that.", "I need confirmation before canceling."],
        )
        self.assertEqual(detail.turns[1]["llm_responses"], [])

    def test_get_trace_by_path_keeps_preflight_confirmation_without_llm_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            trace_path = artifact_dir / "traces" / "trace-preflight-confirmation.json"
            _write_json(
                trace_path,
                {
                    "run_id": "trace-preflight-confirmation",
                    "messages": [
                        {"role": "user", "content": "cancel order #W9"},
                        {"role": "assistant", "content": "Can you confirm?"},
                        {"role": "user", "content": "yes"},
                        {"role": "assistant", "content": "Done."},
                    ],
                    "metadata": {
                        "llm_responses": [
                            {"assistant_content": "", "finish_reason": "tool_calls"},
                            {
                                "assistant_content": "Let me proceed with the cancellation.",
                                "finish_reason": "tool_calls",
                            },
                        ]
                    },
                    "tool_calls": [],
                    "steps": [
                        {"node": "receive_message", "status": "ok", "detail": {}},
                        {
                            "node": "tool_executor",
                            "status": "ok",
                            "detail": {"tool_name": "find_user_id_by_email"},
                        },
                        {
                            "node": "write_action_guard",
                            "status": "ok",
                            "detail": {"tool_name": "cancel_pending_order"},
                        },
                        {"node": "receive_message", "status": "ok", "detail": {}},
                        {"node": "preflight_confirmation", "status": "ok", "detail": {}},
                        {
                            "node": "tool_executor",
                            "status": "ok",
                            "detail": {"tool_name": "cancel_pending_order"},
                        },
                    ],
                    "final_state": {},
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)
            detail = service.get_trace_by_path(str(trace_path))

        self.assertEqual(len(detail.turns), 2)
        self.assertEqual(
            [item["finish_reason"] for item in detail.turns[0]["llm_responses"]],
            ["tool_calls", "tool_calls"],
        )
        self.assertEqual(detail.turns[1]["messages"][-1]["content"], "Done.")
        self.assertEqual(detail.turns[1]["llm_responses"], [])

    def test_get_trace_by_path_loads_absolute_path_outside_trace_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            outside_path = artifact_dir / "outside-trace.json"
            _write_json(
                outside_path,
                {
                    "run_id": "outside-trace",
                    "messages": [{"role": "user", "content": "hi"}],
                    "metadata": {"llm_responses": []},
                    "tool_calls": [],
                    "steps": [],
                    "final_state": {},
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)
            detail = service.get_trace_by_path(str(outside_path))

        self.assertEqual(detail.trace_id, "outside-trace")
        self.assertEqual(detail.trace_artifact_path, str(outside_path))
        self.assertEqual(detail.timeline[0]["kind"], "message")

    def test_get_trace_by_path_includes_write_audit_events_in_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            trace_path = artifact_dir / "traces" / "trace-audit.json"
            _write_json(
                trace_path,
                {
                    "run_id": "trace-audit",
                    "messages": [{"role": "user", "content": "cancel order #W3"}],
                    "metadata": {"llm_responses": []},
                    "tool_calls": [],
                    "steps": [],
                    "write_audit_logs": [
                        {
                            "tool_name": "cancel_pending_order",
                            "status": "blocked",
                            "timestamp": "2026-06-15T01:23:45+00:00",
                            "event": "write_blocked",
                        }
                    ],
                    "final_state": {},
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)
            detail = service.get_trace_by_path(str(trace_path))

        write_audit_events = [item for item in detail.timeline if item["kind"] == "write_audit"]
        self.assertEqual(len(write_audit_events), 1)
        self.assertEqual(write_audit_events[0]["label"], "cancel_pending_order")

    def test_get_trace_by_path_raises_structured_error_for_malformed_nested_entries(self):
        malformed_payloads = {
            "bad-message": {
                "run_id": "bad-message",
                "messages": [{"role": "user", "content": {"text": "hi"}}],
                "metadata": {"llm_responses": []},
                "tool_calls": [],
                "steps": [],
                "final_state": {},
            },
            "bad-step": {
                "run_id": "bad-step",
                "messages": [{"role": "user", "content": "hi"}],
                "metadata": {"llm_responses": []},
                "tool_calls": [],
                "steps": [{"node": "write_action_guard", "status": "ok", "detail": []}],
                "final_state": {},
            },
            "bad-tool-call": {
                "run_id": "bad-tool-call",
                "messages": [{"role": "user", "content": "hi"}],
                "metadata": {"llm_responses": []},
                "tool_calls": [
                    {
                        "tool_name": "cancel_pending_order",
                        "arguments": {"order_id": "#W1"},
                        "tool_kind": "danger",
                        "status": "blocked",
                    }
                ],
                "steps": [],
                "final_state": {},
            },
        }

        for name, payload in malformed_payloads.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as tmp:
                    artifact_dir = Path(tmp)
                    trace_path = artifact_dir / "traces" / f"{name}.json"
                    _write_json(trace_path, payload)

                    service = AgentOpsService(artifact_dir=artifact_dir)

                    with self.assertRaises(WorkbenchAPIError) as context:
                        service.get_trace_by_path(str(trace_path))

                self.assertEqual(context.exception.code, "artifact_parse_error")
                self.assertEqual(context.exception.status_code, 500)

    def test_get_trace_by_path_raises_structured_error_for_malformed_final_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            trace_path = artifact_dir / "traces" / "bad-final-state.json"
            _write_json(
                trace_path,
                {
                    "run_id": "bad-final-state",
                    "messages": [{"role": "user", "content": "hi"}],
                    "metadata": {"llm_responses": []},
                    "tool_calls": [],
                    "steps": [],
                    "final_state": [],
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)

            with self.assertRaises(WorkbenchAPIError) as context:
                service.get_trace_by_path(str(trace_path))

        self.assertEqual(context.exception.code, "artifact_parse_error")
        self.assertEqual(context.exception.status_code, 500)
