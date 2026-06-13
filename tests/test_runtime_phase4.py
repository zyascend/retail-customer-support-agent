from __future__ import annotations

import tempfile

from app.agent.models import PendingAction, SessionState
from app.agent.providers import DisabledLLMProvider
from app.agent.runtime import AgentRuntime
from app.config import resolve_config
from app.tools.retail_adapter import get_order_from_db


def _runtime_with_disabled_provider(tmp: str) -> AgentRuntime:
    return AgentRuntime(
        resolve_config(artifact_dir=tmp),
        provider=DisabledLLMProvider(),
    )


class TestRuntimeSafeFallback:
    """Tests: provider=None falls back to DeterministicProvider."""

    def test_safe_fallback_when_no_provider(self) -> None:
        # Phase 7: DisabledLLMProvider → self.provider = None → DeterministicProvider
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime_with_disabled_provider(tmp)
            result = runtime.run_script(
                messages=[{"role": "user", "content": "Help me with my order"}],
                session_id="test-fallback",
            )

        # DeterministicProvider echoes last user message; agent should not crash
        assert len(result.state.messages) >= 2  # user + assistant
        assert result.state.messages[-1].role == "assistant"
        assert result.state.termination_reason == "script_completed"


class TestRuntimePreflightConfirmation:
    """Tests: pending confirmation handled in pre-flight."""

    def test_confirm_executes_pending_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            runtime = AgentRuntime(config, provider=DisabledLLMProvider())

            session = SessionState(session_id="test-confirm")
            db = runtime.retail_runtime.db
            db_orders = db.get("orders", {})
            pending_order = next(
                (oid for oid, o in db_orders.items() if o.get("status") == "pending"),
                None,
            )
            assert pending_order is not None
            order = get_order_from_db(db, pending_order)
            user_id = order["user_id"]
            session.authenticated_user_id = user_id
            session.loaded_context.orders[pending_order] = order
            session.pending_action = PendingAction(
                action_name="cancel_pending_order",
                arguments={"order_id": pending_order, "reason": "no longer needed"},
                user_facing_summary=f"Cancel order {pending_order}",
            )

            msg = runtime.handle_user_message(session, "yes confirm")
            assert "completed" in msg.lower() or "Done" in msg

    def test_deny_clears_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            runtime = AgentRuntime(config, provider=DisabledLLMProvider())
            session = SessionState(session_id="test-deny")
            session.pending_action = PendingAction(
                action_name="cancel_pending_order",
                arguments={"order_id": "#W1234567", "reason": "no longer needed"},
                user_facing_summary="Cancel order",
            )
            msg = runtime.handle_user_message(session, "no don't do it")
            assert "No changes" in msg or "no changes" in msg.lower()
            assert session.pending_action is None


    def test_changed_clears_pending_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            runtime = AgentRuntime(config, provider=DisabledLLMProvider())
            session = SessionState(session_id="test-changed")
            session.pending_action = PendingAction(
                action_name="cancel_pending_order",
                arguments={"order_id": "#W1234567", "reason": "no longer needed"},
                user_facing_summary="Cancel order",
            )
            msg = runtime.handle_user_message(session, "change to express shipping instead")
            assert "discarded" in msg.lower()
            assert session.pending_action is None

    def test_identity_preflight_by_email(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            runtime = AgentRuntime(config, provider=DisabledLLMProvider())
            session = SessionState(session_id="test-ident")
            # Find a known user email from the DB
            db = runtime.retail_runtime.db
            users = db.get("users", {})
            first_user = next(iter(users.values()))
            email = first_user.get("email", "")
            assert email and "@" in email

            msg = runtime.handle_user_message(session, f"My email is {email}")
            # Should authenticate or return offline fallback
            assert session.authenticated_user_id is not None or "offline" in msg.lower()


class TestRuntimeIntegration:
    """Tests: end-to-end script execution."""

    def test_run_script_uses_session_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime_with_disabled_provider(tmp)
            result = runtime.run_script(
                messages=[{"role": "user", "content": "Hello"}],
                session_id="test-ss",
            )
        assert result.state.session_id == "test-ss"
        assert isinstance(result.state, SessionState)
        assert len(result.state.messages) >= 2
