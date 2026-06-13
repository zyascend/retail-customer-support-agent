import json
import tempfile
import threading
import time
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
            self.assertIn("order:#W5918442:cancel", second["business"]["write_locks"])
            self.assertTrue(Path(second["trace_artifact_path"]).exists())

    def test_generated_generalization_case_replays_with_seeded_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(
                mode="deterministic",
                case_id="cancel_success_s100_l1",
            )

            snapshot = session.run_all()

            self.assertEqual(snapshot["selected_case_id"], "cancel_success_s100_l1")
            self.assertEqual(snapshot["business"]["confirmation_status"], "confirmed")
            self.assertTrue(Path(snapshot["trace_artifact_path"]).exists())

    def test_concurrent_steps_serialize_script_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(
                mode="deterministic", case_id="cancel_pending_order"
            )
            original_send = session._send_user_content
            seen_contents = []

            def synchronized_send(content):
                seen_contents.append(content)
                time.sleep(0.05)
                return original_send(content)

            session._send_user_content = synchronized_send

            threads = [threading.Thread(target=session.step) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(session.script_cursor, 2)
            self.assertEqual(
                seen_contents,
                [
                    "My email is sofia.rossi2645@example.com. Cancel order #W5918442 because no longer needed.",
                    "yes",
                ],
            )

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
                manager.create_session(mode="deterministic", case_id="missing_case")

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
            self.assertEqual(
                session.snapshot()["messages"], before_snapshot["messages"]
            )

    def test_failed_reset_during_trace_write_preserves_existing_session_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(
                mode="deterministic", case_id="cancel_pending_order"
            )
            before_snapshot = session.step()
            before_case = session.selected_case
            before_messages = list(session.state.messages)
            before_runtime = session.runtime
            before_state = session.state
            before_trace_path = session.trace_artifact_path

            def fail_write_trace_for(
                runtime,
                state,
                mode,
                initial_db_hash,
                trace_path=None,
            ):
                raise RuntimeError("trace unavailable")

            session._write_trace_for = fail_write_trace_for

            with self.assertRaises(RuntimeError):
                session.reset(case_id="return_delivered_order_item")

            self.assertEqual(session.mode, "deterministic")
            self.assertIs(session.selected_case, before_case)
            self.assertEqual(session.script_cursor, 1)
            self.assertEqual(session.state.messages, before_messages)
            self.assertIs(session.runtime, before_runtime)
            self.assertIs(session.state, before_state)
            self.assertEqual(session.trace_artifact_path, before_trace_path)
            self.assertEqual(
                session.snapshot()["messages"], before_snapshot["messages"]
            )

    def test_failed_reset_trace_staging_preserves_existing_trace_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(
                mode="deterministic", case_id="cancel_pending_order"
            )
            session.step()
            before_case = session.selected_case
            before_runtime = session.runtime
            before_trace_path = Path(session.trace_artifact_path)
            before_trace_text = before_trace_path.read_text(encoding="utf-8")

            def fail_write_trace_for(
                runtime,
                state,
                mode,
                initial_db_hash,
                trace_path=None,
            ):
                self.assertIsNotNone(trace_path)
                Path(trace_path).write_text("corrupted candidate", encoding="utf-8")
                raise RuntimeError("trace staging failed")

            session._write_trace_for = fail_write_trace_for

            with self.assertRaises(RuntimeError):
                session.reset(case_id="return_delivered_order_item")

            self.assertIs(session.selected_case, before_case)
            self.assertEqual(session.script_cursor, 1)
            self.assertIs(session.runtime, before_runtime)
            self.assertEqual(session.trace_artifact_path, str(before_trace_path))
            self.assertEqual(
                before_trace_path.read_text(encoding="utf-8"),
                before_trace_text,
            )
            self.assertEqual(
                list(before_trace_path.parent.glob(f".{session.session_id}.*.tmp")),
                [],
            )

    def test_wrong_user_demo_exposes_guard_block_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(
                mode="deterministic", case_id="block_wrong_user_order_access"
            )

            snapshot = session.run_all()

            self.assertEqual(
                snapshot["selected_case_id"], "block_wrong_user_order_access"
            )
            self.assertIn("another account", snapshot["messages"][-1]["content"])
            self.assertEqual(len(snapshot["guard_blocks"]), 1)
            self.assertEqual(snapshot["guard_blocks"][0]["status"], "blocked")
            self.assertEqual(
                snapshot["guard_blocks"][0]["error"], "wrong_user_order_access"
            )

    def test_confirmed_write_tool_call_appears_after_confirmation_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = WorkbenchSessionManager(config=resolve_config(artifact_dir=tmp))
            session = manager.create_session(
                mode="deterministic", case_id="cancel_pending_order"
            )

            snapshot = session.run_all()

            labels = [
                (event["kind"], event["label"], event["summary"])
                for event in snapshot["timeline"]
            ]
            yes_index = next(
                index
                for index, (kind, label, summary) in enumerate(labels)
                if kind == "message" and label == "user" and summary == "yes"
            )
            write_index = next(
                index
                for index, (kind, label, _summary) in enumerate(labels)
                if kind == "tool_call" and label == "cancel_pending_order"
            )

            self.assertGreater(write_index, yes_index)


if __name__ == "__main__":
    unittest.main()
