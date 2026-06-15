import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import resolve_config
from app.workbench.api import create_app


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_agentops_artifacts(artifact_dir: Path) -> Path:
    trace_path = artifact_dir / "traces" / "eval-run-a" / "runs" / "case-a.json"
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
            "metrics": {"pass_rate": 0.0},
            "results": [
                {
                    "case_id": "case-a",
                    "subset": "live_smoke_core",
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
                        "assistant_content": "I need confirmation.",
                        "finish_reason": "stop",
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
                    "observation": {"block_reason": "explicit_confirmation_required"},
                }
            ],
            "steps": [],
            "final_state": {
                "confirmation_status": "required",
                "pending_action": {"action_name": "cancel_pending_order"},
            },
        },
    )
    return trace_path


class WorkbenchAPITests(unittest.TestCase):
    def test_config_returns_cases_and_llm_availability(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                config=replace(resolve_config(artifact_dir=tmp), deepseek_api_key="")
            )
            client = TestClient(app)

            response = client.get("/api/workbench/config")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["default_mode"], "offline_demo")
        self.assertFalse(payload["llm_available"])
        self.assertEqual(payload["case_catalog"]["subset"], "generalized_mvp")
        self.assertGreaterEqual(len(payload["case_catalog"]["demo_cases"]), 5)

    def test_config_includes_generated_scenario_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.get("/api/workbench/config")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        generated = [
            case
            for case in payload["case_catalog"]["all_cases"]
            if case["subset"] == "generalization"
        ]
        self.assertTrue(generated)
        self.assertIn("seed", generated[0])
        self.assertIn("scenario_family", generated[0])
        self.assertIn("variant_type", generated[0])
        self.assertIn("language_variation_level", generated[0])
        self.assertIn("expected_oracle", generated[0])

    def test_session_step_and_run_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)
            created = client.post(
                "/api/sessions",
                json={"mode": "offline_demo", "case_id": "cancel_pending_order"},
            ).json()
            session_id = created["session_id"]

            first = client.post(f"/api/sessions/{session_id}/step").json()
            second = client.post(f"/api/sessions/{session_id}/run-all").json()

        self.assertEqual(first["script_cursor"], 1)
        self.assertEqual(second["script_cursor"], 2)
        self.assertEqual(second["business"]["confirmation_status"], "confirmed")

    def test_create_session_accepts_no_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.post("/api/sessions")

        self.assertEqual(response.status_code, 200)
        snapshot = response.json()
        self.assertEqual(snapshot["mode"], "offline_demo")
        self.assertIsNone(snapshot["selected_case_id"])

    def test_reset_accepts_no_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)
            created = client.post(
                "/api/sessions",
                json={"mode": "offline_demo", "case_id": "cancel_pending_order"},
            ).json()
            session_id = created["session_id"]
            client.post(f"/api/sessions/{session_id}/step")

            response = client.post(f"/api/sessions/{session_id}/reset")

        self.assertEqual(response.status_code, 200)
        snapshot = response.json()
        self.assertEqual(snapshot["session_id"], session_id)
        self.assertEqual(snapshot["mode"], "offline_demo")
        self.assertEqual(snapshot["selected_case_id"], "cancel_pending_order")
        self.assertEqual(snapshot["script_cursor"], 0)

    def test_manual_message_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)
            session_id = client.post(
                "/api/sessions", json={"mode": "offline_demo"}
            ).json()["session_id"]

            snapshot = client.post(
                f"/api/sessions/{session_id}/messages",
                json={
                    "content": (
                        "My email is sofia.rossi2645@example.com. What is the "
                        "status of order #W5918442?"
                    )
                },
            ).json()

        self.assertEqual(snapshot["compat"]["current_intent"], "unknown")
        self.assertEqual(snapshot["script_cursor"], 0)

    def test_errors_are_structured(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.post("/api/sessions/missing/step")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "session_not_found")

    def test_create_session_with_unknown_case_returns_structured_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.post(
                "/api/sessions",
                json={"mode": "offline_demo", "case_id": "not_a_case"},
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "case_not_found")

    def test_create_session_with_invalid_mode_returns_structured_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.post("/api/sessions", json={"mode": "unknown"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_mode")

    def test_step_without_case_returns_structured_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)
            session_id = client.post("/api/sessions").json()["session_id"]

            response = client.post(f"/api/sessions/{session_id}/step")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "case_required")

    def test_blank_message_returns_structured_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)
            session_id = client.post("/api/sessions").json()["session_id"]

            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"content": "   "},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "empty_message")

    def test_agentops_reports_list_returns_summaries_from_artifact_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_agentops_artifacts(artifact_dir)
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.get("/api/agentops/reports")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([report["run_id"] for report in payload], ["eval-run-a"])
        self.assertEqual(
            payload[0]["report_path"],
            str((artifact_dir / "reports" / "eval-run-a.json").resolve()),
        )
        self.assertEqual(payload[0]["failure_case_count"], 1)
        self.assertEqual(payload[0]["subset"], "live_smoke_core")

    def test_agentops_report_detail_returns_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_agentops_artifacts(Path(tmp))
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.get("/api/agentops/reports/eval-run-a")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["run_id"], "eval-run-a")
        self.assertEqual(payload["metrics"], {"pass_rate": 0.0})
        self.assertEqual(payload["cases"][0]["case_id"], "case-a")
        self.assertEqual(payload["cases"][0]["root_cause"], "prompt_gap")

    def test_agentops_case_detail_returns_merged_trace_and_report_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_agentops_artifacts(Path(tmp))
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.get("/api/agentops/reports/eval-run-a/cases/case-a")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["case_id"], "case-a")
        self.assertEqual(payload["failure_label"], "wrong_tool")
        self.assertEqual(payload["root_cause"], "prompt_gap")
        self.assertEqual(payload["user_messages"], ["cancel order #W1"])
        self.assertEqual(payload["assistant_messages"], ["I need confirmation."])
        self.assertEqual(
            payload["guard_context"],
            [{"confirmation_required": True, "summary": "Cancel order #W1."}],
        )
        self.assertEqual(payload["db_assertion_diff"]["order_status"]["actual"], "pending")
        self.assertEqual(payload["trace_summary"]["guard_block_count"], 1)

    def test_agentops_trace_by_path_returns_trace_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = _write_agentops_artifacts(Path(tmp))
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.get(
                "/api/agentops/traces/by-path",
                params={"path": str(trace_path)},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["trace_id"], "case-a")
        self.assertEqual(payload["trace_artifact_path"], str(trace_path))
        self.assertEqual(payload["turns"][0]["messages"][0]["content"], "cancel order #W1")

    def test_agentops_trace_by_path_rejects_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.get(
                "/api/agentops/traces/by-path",
                params={"path": "traces/case-a.json"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_trace_path")

    def test_agentops_missing_report_returns_structured_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.get("/api/agentops/reports/missing-run")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "report_not_found")


if __name__ == "__main__":
    unittest.main()
