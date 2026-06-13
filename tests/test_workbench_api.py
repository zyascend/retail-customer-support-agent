import tempfile
import unittest
from dataclasses import replace

from fastapi.testclient import TestClient

from app.config import resolve_config
from app.workbench.api import create_app


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
        self.assertEqual(payload["default_mode"], "deterministic")
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
                json={"mode": "deterministic", "case_id": "cancel_pending_order"},
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
        self.assertEqual(snapshot["mode"], "deterministic")
        self.assertIsNone(snapshot["selected_case_id"])

    def test_reset_accepts_no_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)
            created = client.post(
                "/api/sessions",
                json={"mode": "deterministic", "case_id": "cancel_pending_order"},
            ).json()
            session_id = created["session_id"]
            client.post(f"/api/sessions/{session_id}/step")

            response = client.post(f"/api/sessions/{session_id}/reset")

        self.assertEqual(response.status_code, 200)
        snapshot = response.json()
        self.assertEqual(snapshot["session_id"], session_id)
        self.assertEqual(snapshot["mode"], "deterministic")
        self.assertEqual(snapshot["selected_case_id"], "cancel_pending_order")
        self.assertEqual(snapshot["script_cursor"], 0)

    def test_manual_message_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)
            session_id = client.post(
                "/api/sessions", json={"mode": "deterministic"}
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

        self.assertEqual(snapshot["business"]["current_intent"], "lookup")
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
                json={"mode": "deterministic", "case_id": "not_a_case"},
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


if __name__ == "__main__":
    unittest.main()
