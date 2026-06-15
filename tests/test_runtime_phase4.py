from __future__ import annotations

import tempfile
from dataclasses import replace

from app.agent.models import (
    Message,
    PendingAction,
    SessionState,
    ToolCallRequest,
    ToolCallResponse,
)
from app.agent.providers import DisabledLLMProvider, ScriptedToolCallingProvider
from app.agent.runtime import AgentRuntime
from app.config import resolve_config
from app.tools.retail_adapter import get_order_from_db


def _offline_demo_runtime(tmp: str) -> AgentRuntime:
    return AgentRuntime(
        resolve_config(artifact_dir=tmp),
        provider=DisabledLLMProvider(),
        offline_demo=True,
    )


class TestRuntimeSafeFallback:
    """Tests: provider availability and offline demo boundaries."""

    def test_no_provider_returns_safe_unavailable_message_without_demo_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = AgentRuntime(
                replace(resolve_config(artifact_dir=tmp), deepseek_api_key="")
            )
            result = runtime.run_script(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "My email is sofia.rossi2645@example.com. "
                            "Cancel order #W5918442 because no longer needed."
                        ),
                    }
                ],
                session_id="test-no-hidden-fallback",
            )

        assert len(result.state.messages) >= 2  # user + assistant
        assert result.state.messages[-1].role == "assistant"
        assert "human agent" in result.state.messages[-1].content.lower()
        assert result.state.pending_action is None
        assert not any(
            record.tool_name == "cancel_pending_order"
            for record in result.state.tool_results
        )
        assert result.state.termination_reason == "script_completed"

    def test_offline_demo_provider_uses_explicit_demo_harness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _offline_demo_runtime(tmp)
            result = runtime.run_script(
                messages=[{"role": "user", "content": "Help me with my order"}],
                session_id="test-offline-demo",
            )

        assert len(result.state.messages) >= 2
        assert result.state.messages[-1].role == "assistant"
        assert any(step.node == "offline_demo_harness" for step in result.state.steps)
        assert result.state.termination_reason == "script_completed"

    def test_offline_demo_parser_lives_outside_agent_runtime(self) -> None:
        assert not hasattr(AgentRuntime, "_offline_demo_intent")
        assert not hasattr(AgentRuntime, "_det_call")
        assert not hasattr(AgentRuntime, "_parse_address")

        from app.agent.offline_demo import OfflineDemoHarness

        assert hasattr(OfflineDemoHarness, "handle")


class TestRuntimePreflightConfirmation:
    """Tests: pending confirmation handled in pre-flight."""

    def test_confirm_executes_pending_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            runtime = AgentRuntime(
                config, provider=DisabledLLMProvider(), offline_demo=True
            )

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

    def test_confirmed_action_returns_to_llm_for_remaining_requested_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            provider = ScriptedToolCallingProvider(
                responses=[
                    ToolCallResponse(
                        tool_calls=[
                            ToolCallRequest(
                                id="call_cancel_first",
                                tool_name="cancel_pending_order",
                                arguments={
                                    "order_id": "#W5199551",
                                    "reason": "no longer needed",
                                },
                            )
                        ],
                        finish_reason="tool_calls",
                    ),
                    ToolCallResponse(
                        tool_calls=[
                            ToolCallRequest(
                                id="call_cancel_second",
                                tool_name="cancel_pending_order",
                                arguments={
                                    "order_id": "#W8665881",
                                    "reason": "no longer needed",
                                },
                            )
                        ],
                        finish_reason="tool_calls",
                    ),
                    ToolCallResponse(
                        assistant_content="I cancelled both pending orders.",
                        finish_reason="stop",
                    ),
                ]
            )
            runtime = AgentRuntime(config, provider=provider)
            session = SessionState(session_id="test-confirm-continue")
            session.authenticated_user_id = "fatima_johnson_7581"
            db = runtime.retail_runtime.db
            first_order = get_order_from_db(db, "#W5199551")
            second_order = get_order_from_db(db, "#W8665881")
            session.loaded_context.orders["#W5199551"] = first_order
            session.loaded_context.orders["#W8665881"] = second_order

            first_msg = runtime.handle_user_message(
                session,
                (
                    "Cancel all pending orders because they are no longer needed, "
                    "including #W5199551 and #W8665881."
                ),
            )
            assert "confirm" in first_msg.lower()

            second_msg = runtime.handle_user_message(session, "yes confirm")

            assert "confirm" in second_msg.lower()
            assert len(provider.calls) >= 2
            assert session.pending_action is not None
            assert session.pending_action.action_name == "cancel_pending_order"
            assert session.pending_action.arguments["order_id"] == "#W8665881"

    def test_confirmation_continuation_preserves_original_request_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            provider = ScriptedToolCallingProvider(
                responses=[
                    ToolCallResponse(
                        assistant_content="I can continue the full original request.",
                        finish_reason="stop",
                    ),
                ]
            )
            runtime = AgentRuntime(config, provider=provider)
            session = SessionState(session_id="test-confirm-original-context")
            original_request = (
                "Return the skateboard, garden hose, backpack, keyboard, and bed, "
                "then tell me the total refund amount."
            )
            session.messages.append(Message(role="user", content=original_request))
            for index in range(4):
                session.messages.append(
                    Message(role="assistant", content=f"Intermediate reply {index}")
                )
                session.messages.append(
                    Message(role="user", content=f"Intermediate user turn {index}")
                )
            session.authenticated_user_id = "isabella_johansson_2152"
            db = runtime.retail_runtime.db
            order = get_order_from_db(db, "#W3792453")
            session.loaded_context.orders["#W3792453"] = order
            session.pending_action = PendingAction(
                action_name="return_delivered_order_items",
                arguments={
                    "order_id": "#W3792453",
                    "item_ids": ["4293355847"],
                    "payment_method_id": "paypal_3024827",
                },
                user_facing_summary="Return one item",
            )

            runtime.handle_user_message(session, "yes confirm")

            continuation_messages = provider.calls[0]["messages"]
            assert original_request in continuation_messages[-1]["content"]

    def test_deny_clears_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_config(artifact_dir=tmp)
            runtime = AgentRuntime(
                config, provider=DisabledLLMProvider(), offline_demo=True
            )
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
            runtime = AgentRuntime(
                config, provider=DisabledLLMProvider(), offline_demo=True
            )
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
            runtime = AgentRuntime(
                config, provider=DisabledLLMProvider(), offline_demo=True
            )
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
            runtime = _offline_demo_runtime(tmp)
            result = runtime.run_script(
                messages=[{"role": "user", "content": "Hello"}],
                session_id="test-ss",
            )
        assert result.state.session_id == "test-ss"
        assert isinstance(result.state, SessionState)
        assert len(result.state.messages) >= 2
