import unittest

from app.agent.models import Message, PendingAction, SessionState, ToolCallRecord
from app.workbench.snapshot import build_timeline, redact_value, snapshot_from_state

SNAPSHOT_KEYS = {
    "session_id",
    "mode",
    "llm_available",
    "selected_case_id",
    "script_cursor",
    "script_message_count",
    "run_controls",
    "messages",
    "business",
    "pending_action",
    "policy_decision",
    "tool_results",
    "timeline",
    "audit_logs",
    "guard_blocks",
    "trace_artifact_path",
    "last_error",
}


class WorkbenchSnapshotTests(unittest.TestCase):
    def test_redacts_sensitive_strings_and_keys(self):
        payload = {
            "email": "alex@example.com",
            "phone": "555-123-4567",
            "address": "123 Main St",
            "order_id": "#W1234567",
        }

        redacted = redact_value(payload)

        self.assertEqual(redacted["email"], "[redacted-email]")
        self.assertEqual(redacted["phone"], "[redacted-phone]")
        self.assertEqual(redacted["address"], "[redacted-address]")
        self.assertEqual(redacted["order_id"], "#W1234567")

    def test_redacts_sensitive_patterns_without_losing_context(self):
        redacted = redact_value("My email is sofia@example.com. Cancel order #W5918442")

        self.assertEqual(
            redacted,
            "My email is [redacted-email]. Cancel order #W5918442",
        )

    def test_timeline_combines_messages_steps_tools_and_audit(self):
        state = SessionState(session_id="session-1")
        state.messages.append(Message(role="user", content="hello"))
        state.add_step("receive_message", status="seen")
        state.tool_results.append(
            ToolCallRecord(
                tool_name="cancel_pending_order",
                arguments={"order_id": "#W5918442"},
                tool_kind="write",
                status="blocked",
                error="explicit_confirmation_required",
            )
        )
        state.audit_logs.append({"tool_name": "cancel_pending_order"})

        timeline = build_timeline(state)

        self.assertEqual(
            [event["kind"] for event in timeline],
            ["message", "step", "tool_call", "write_audit"],
        )
        self.assertEqual(timeline[2]["status"], "blocked")
        self.assertEqual(timeline[2]["label"], "cancel_pending_order")

    def test_timeline_preserves_message_and_step_chronology(self):
        state = SessionState(session_id="session-1")
        state.messages.append(
            Message(
                role="user",
                content="first",
                created_at="2026-06-12T00:00:00+00:00",
            )
        )
        state.messages.append(
            Message(
                role="assistant",
                content="reply",
                created_at="2026-06-12T00:00:01+00:00",
            )
        )
        state.add_step("receive_message", status="ok")
        state.add_step("response_generator", status="ok")

        timeline = build_timeline(state)

        self.assertEqual(
            [event["kind"] for event in timeline],
            ["message", "step", "step", "message"],
        )
        self.assertEqual(
            [event["label"] for event in timeline],
            ["user", "receive_message", "response_generator", "assistant"],
        )

    def test_snapshot_includes_pending_action_and_business_summary(self):
        state = SessionState(
            session_id="session-1", authenticated_user_id="user-1"
        )
        state.pending_action = PendingAction(
            action_name="cancel_pending_order",
            arguments={"order_id": "#W5918442", "reason": "no longer needed"},
            user_facing_summary="Cancel order #W5918442 because no longer needed.",
        )
        state.confirmation_status = "required"

        snapshot = snapshot_from_state(
            session_id="session-1",
            mode="offline_demo",
            llm_available=False,
            state=state,
            initial_db_hash="before",
            current_db_hash="after",
            trace_artifact_path="/tmp/session-1.json",
            selected_case_id="cancel_pending_order",
            script_cursor=1,
            script_message_count=2,
        )

        self.assertEqual(snapshot["session_id"], "session-1")
        self.assertEqual(snapshot["business"]["authenticated_user_id"], "user-1")
        self.assertIsNone(snapshot["business"]["active_order_id"])
        self.assertEqual(
            snapshot["pending_action"]["action_name"], "cancel_pending_order"
        )
        self.assertTrue(snapshot["run_controls"]["can_step"])
        self.assertTrue(snapshot["run_controls"]["can_run_all"])

    def test_snapshot_uses_supplied_last_error_and_required_keys(self):
        state = SessionState(session_id="session-1")
        supplied_error = {
            "code": "case_failed",
            "message": "Could not continue session #W5918442",
        }

        snapshot = snapshot_from_state(
            session_id="session-1",
            mode="offline_demo",
            llm_available=False,
            state=state,
            initial_db_hash="same",
            current_db_hash="same",
            trace_artifact_path=None,
            selected_case_id=None,
            script_cursor=0,
            script_message_count=0,
            last_error=supplied_error,
        )

        self.assertEqual(set(snapshot), SNAPSHOT_KEYS)
        self.assertIs(snapshot["last_error"], supplied_error)


if __name__ == "__main__":
    unittest.main()
