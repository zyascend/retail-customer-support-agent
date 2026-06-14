import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from app.dashboard.builder import DashboardBuilder
from app.dashboard.cli import dashboard_main


class DashboardBuilderTests(unittest.TestCase):
    def test_build_embeds_trace_and_redacts_pii(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            trace_path = tmp_path / "trace.json"
            trace_path.write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Email is alex@example.com and phone 555-123-4567.",
                                "created_at": "2026-01-01T00:00:00Z",
                            }
                        ],
                        "steps": [
                            {"node": "receive_message", "status": "ok", "detail": {}}
                        ],
                        "tool_calls": [
                            {
                                "tool_name": "modify_address",
                                "status": "success",
                                "arguments": {"address": "123 Main Street"},
                            }
                        ],
                        "policy_checks": [{"decision": "allow"}],
                        "write_audit_logs": [{"action": "modify_address"}],
                        "final_state": {
                            "compat": {
                                "current_intent": "modify_order_address",
                                "slots": {},
                                "policy_decision": None,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            report_path = tmp_path / "report.json"
            report = _report(trace_path)
            report_path.write_text(json.dumps(report), encoding="utf-8")

            data = DashboardBuilder().build(report, report_path)
            html = DashboardBuilder().render_html(data)

        self.assertEqual(data["schema_version"], "phase3.dashboard.v1")
        self.assertEqual(data["report"]["eval_run_id"], "eval-test")
        self.assertEqual(data["report"]["case_count"], 1)
        self.assertEqual(len(data["cases"][0]["trace"]["timeline"]), 5)
        self.assertEqual(data["cases"][0]["trace"]["timeline"][0]["source"], "message")
        self.assertEqual(
            data["cases"][0]["trace"]["messages"][0]["content"],
            "Email is [redacted-email] and phone [redacted-phone].",
        )
        self.assertEqual(
            data["cases"][0]["trace"]["tool_calls"][0]["arguments"]["address"],
            "[redacted-address]",
        )
        self.assertIn("Phase 3 Dashboard", html)
        self.assertIn("Trace Timeline", html)
        self.assertIn("dashboard-data", html)
        self.assertNotIn("alex@example.com", html)

    def test_dashboard_cli_writes_static_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            trace_path = tmp_path / "trace.json"
            trace_path.write_text(
                json.dumps({"messages": [], "steps": []}), encoding="utf-8"
            )
            report_path = tmp_path / "report.json"
            report_path.write_text(json.dumps(_report(trace_path)), encoding="utf-8")
            output_dir = tmp_path / "dashboard"

            with redirect_stdout(StringIO()):
                exit_code = dashboard_main(
                    [str(report_path), "--output-dir", str(output_dir)]
                )

            data = json.loads(
                (output_dir / "dashboard-data.json").read_text(encoding="utf-8")
            )
            html = (output_dir / "index.html").read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(data["report"]["eval_run_id"], "eval-test")
        self.assertEqual(data["cases"][0]["case_id"], "case-1")
        self.assertIn("Phase 3 Dashboard", html)


def _report(trace_path: Path) -> dict:
    return {
        "schema_version": "phase2.eval_report.v1",
        "report_type": "phase2_eval_report",
        "eval_run_id": "eval-test",
        "subset": "curated_mvp",
        "trials": 1,
        "model": "deepseek-v4-flash",
        "agent_strategy": "guarded_workflow_agent",
        "dataset_root": "/tmp/data",
        "dataset_db_path": "/tmp/data/retail.db",
        "code_commit": "abc123",
        "metrics": {
            "pass_1": 0.0,
            "pass_k": 0.0,
            "db_accuracy": 1.0,
            "tool_call_success_rate": 1.0,
            "guard_block_rate": 0.0,
            "mutation_error_rate": 0.0,
        },
        "failure_analysis": {
            "failure_label_counts": {"wrong_tool": 1},
            "failed_cases": [],
        },
        "results": [
            {
                "case_id": "case-1",
                "category": "cancel",
                "trial": 0,
                "passed": False,
                "failure_label": "wrong_tool",
                "failure_summary": "wrong_tool: mismatch in tool",
                "duration_seconds": 0.12,
                "trace_artifact_path": str(trace_path),
                "replay_metadata": {"task_id": "case-1"},
                "final_intent": "cancel_order",
                "authenticated_user_id": "user-1",
                "tool_call_count": 1,
                "successful_tool_calls": 1,
                "failed_tool_calls": 0,
                "blocked_tool_calls": 0,
                "tool_errors": 0,
                "guard_blocks": 0,
                "db_accuracy_passed": True,
                "db_accuracy_basis": "order_status",
                "mutation_detected": False,
                "unexpected_mutation": False,
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
