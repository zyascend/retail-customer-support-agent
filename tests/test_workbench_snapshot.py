import unittest

from app.agent.models import ConversationState, Message, PendingAction, ToolCallRecord
from app.workbench.snapshot import build_timeline, redact_value, snapshot_from_state


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

    def test_timeline_combines_messages_steps_tools_and_audit(self):
        state = ConversationState(session_id="session-1")
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

    def test_snapshot_includes_pending_action_and_business_summary(self):
        state = ConversationState(
            session_id="session-1", authenticated_user_id="user-1"
        )
        state.current_intent = "cancel_order"
        state.slots["order_id"] = "#W5918442"
        state.pending_action = PendingAction(
            action_name="cancel_pending_order",
            arguments={"order_id": "#W5918442", "reason": "no longer needed"},
            user_facing_summary="Cancel order #W5918442 because no longer needed.",
        )
        state.confirmation_status = "required"

        snapshot = snapshot_from_state(
            session_id="session-1",
            mode="deterministic",
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
        self.assertEqual(snapshot["business"]["active_order_id"], "#W5918442")
        self.assertEqual(
            snapshot["pending_action"]["action_name"], "cancel_pending_order"
        )
        self.assertTrue(snapshot["run_controls"]["can_step"])
        self.assertTrue(snapshot["run_controls"]["can_run_all"])


if __name__ == "__main__":
    unittest.main()
