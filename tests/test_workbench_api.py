import tempfile
import unittest

from fastapi.testclient import TestClient

from app.config import resolve_config
from app.workbench.api import create_app


class WorkbenchAPITests(unittest.TestCase):
    def test_config_returns_cases_and_llm_availability(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(config=resolve_config(artifact_dir=tmp))
            client = TestClient(app)

            response = client.get("/api/workbench/config")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["default_mode"], "deterministic")
        self.assertFalse(payload["llm_available"])
        self.assertEqual(payload["case_catalog"]["subset"], "curated_mvp")
        self.assertGreaterEqual(len(payload["case_catalog"]["demo_cases"]), 5)

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


if __name__ == "__main__":
    unittest.main()
