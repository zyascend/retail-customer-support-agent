import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from app.config import resolve_config
from app.workbench.errors import WorkbenchAPIError
from app.workbench.session import WorkbenchSessionManager


class WorkbenchSessionTests(unittest.TestCase):
    def test_step_and_run_all_share_conversation_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(
                mode="deterministic", case_id="cancel_pending_order"
            )

            first = session.step()
            self.assertEqual(first["script_cursor"], 1)
            self.assertEqual(first["business"]["confirmation_status"], "required")
            self.assertEqual(
                first["pending_action"]["action_name"], "cancel_pending_order"
            )

            second = session.run_all()
            self.assertEqual(second["script_cursor"], 2)
            self.assertEqual(second["business"]["confirmation_status"], "confirmed")
            self.assertIn(
                "order:#W5918442:cancel", second["business"]["write_locks"]
            )
            self.assertTrue(Path(second["trace_artifact_path"]).exists())

    def test_manual_message_does_not_move_script_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(
                mode="deterministic", case_id="transfer_to_human"
            )

            snapshot = session.send_message(
                "My email is sofia.rossi2645@example.com. What is the status of order #W5918442?"
            )

            self.assertEqual(snapshot["script_cursor"], 0)
            self.assertEqual(snapshot["business"]["current_intent"], "lookup")
            self.assertGreaterEqual(len(snapshot["messages"]), 2)

    def test_reset_recreates_runtime_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(
                mode="deterministic", case_id="cancel_pending_order"
            )
            session.step()

            reset_snapshot = session.reset(case_id="return_delivered_order_item")

            self.assertEqual(
                reset_snapshot["selected_case_id"], "return_delivered_order_item"
            )
            self.assertEqual(reset_snapshot["script_cursor"], 0)
            self.assertEqual(reset_snapshot["messages"], [])
            self.assertEqual(
                reset_snapshot["business"]["confirmation_status"], "not_required"
            )

    def test_trace_artifact_updates_after_each_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(
                mode="deterministic", case_id="transfer_to_human"
            )

            snapshot = session.step()
            trace = json.loads(
                Path(snapshot["trace_artifact_path"]).read_text(encoding="utf-8")
            )

            self.assertEqual(trace["run_id"], session.session_id)
            self.assertEqual(trace["final_state"]["current_intent"], "transfer")

    def test_get_missing_session_raises_structured_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))

            with self.assertRaises(WorkbenchAPIError) as context:
                manager.get("missing")

            self.assertEqual(context.exception.code, "session_not_found")
            self.assertEqual(context.exception.status_code, 404)
            self.assertEqual(context.exception.details, {"session_id": "missing"})

    def test_runtime_failure_keeps_script_cursor_on_failing_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(
                mode="deterministic", case_id="cancel_pending_order"
            )

            def fail_handle_user_message(state, content):
                raise RuntimeError("boom")

            session.runtime.handle_user_message = fail_handle_user_message

            step_snapshot = session.step()

            self.assertEqual(step_snapshot["script_cursor"], 0)
            self.assertEqual(step_snapshot["last_error"]["code"], "runtime_error")
            self.assertTrue(Path(step_snapshot["trace_artifact_path"]).exists())

            run_all_snapshot = session.run_all()

            self.assertEqual(run_all_snapshot["script_cursor"], 0)
            self.assertEqual(run_all_snapshot["last_error"]["code"], "runtime_error")

    def test_unknown_case_ids_raise_structured_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))

            with self.assertRaises(WorkbenchAPIError) as create_context:
                manager.create_session(
                    mode="deterministic", case_id="missing_case"
                )

            self.assertEqual(create_context.exception.code, "case_not_found")
            self.assertEqual(create_context.exception.status_code, 404)
            self.assertEqual(
                create_context.exception.details, {"case_id": "missing_case"}
            )

            session = manager.create_session(mode="deterministic")

            with self.assertRaises(WorkbenchAPIError) as reset_context:
                session.reset(case_id="missing_case")

            self.assertEqual(reset_context.exception.code, "case_not_found")
            self.assertEqual(reset_context.exception.status_code, 404)
            self.assertEqual(
                reset_context.exception.details, {"case_id": "missing_case"}
            )

    def test_failed_reset_preserves_existing_session_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(
                resolve_config(artifact_dir=tmp),
                deepseek_api_key="dummy",
            )
            manager = WorkbenchSessionManager(config=config)
            session = manager.create_session(
                mode="deterministic", case_id="cancel_pending_order"
            )
            before_snapshot = session.step()
            before_messages = list(session.state.messages)
            before_runtime = session.runtime

            with self.assertRaises(WorkbenchAPIError) as context:
                session.reset(case_id="missing_case", mode="llm")

            self.assertEqual(context.exception.code, "case_not_found")
            self.assertEqual(session.mode, "deterministic")
            self.assertEqual(session.selected_case.case_id, "cancel_pending_order")
            self.assertEqual(session.script_cursor, 1)
            self.assertEqual(session.state.messages, before_messages)
            self.assertIs(session.runtime, before_runtime)
            self.assertEqual(session.snapshot()["messages"], before_snapshot["messages"])


if __name__ == "__main__":
    unittest.main()
