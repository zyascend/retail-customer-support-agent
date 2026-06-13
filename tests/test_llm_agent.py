from __future__ import annotations

from app.agent.context_builder import ContextBuilder
from app.agent.models import (
    SessionState,
    ToolCallResponse,
)
from app.agent.providers import ScriptedToolCallingProvider
from app.config import resolve_config
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry
from app.tools.retail_adapter import RetailAdapter


def _registry() -> ToolRegistry:
    runtime = RetailAdapter(resolve_config()).create_runtime()
    return ToolRegistry(runtime.tools)


def _gateway() -> ToolGateway:
    runtime = RetailAdapter(resolve_config()).create_runtime()
    registry = ToolRegistry(runtime.tools)
    return ToolGateway(registry=registry, runtime=runtime)


def _context_builder() -> ContextBuilder:
    policy_path = resolve_config().retail_policy_path
    policy_text = policy_path.read_text()[:500] if policy_path.exists() else ""
    return ContextBuilder(policy_text=policy_text)


def _session(**kwargs) -> SessionState:
    defaults = dict(
        session_id="test-1",
        authenticated_user_id="U1",
        auth_method="email",
        active_user_identity={"user_id": "U1", "name": "Test User", "email": "test@example.com"},
    )
    defaults.update(kwargs)
    return SessionState(**defaults)


class TestAgentLoopBasic:
    """Tests: single-turn response, no tool calls."""

    def test_direct_text_response_no_tools(self) -> None:
        from app.agent.llm_agent import AgentLoop

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    assistant_content="Hello! How can I help you today?",
                    finish_reason="stop",
                )
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        session = _session()
        result = loop.run_turn(session, "Hi")

        assert result.assistant_message == "Hello! How can I help you today?"
        assert result.turn.loop_iterations == 1
        assert result.turn.termination == "final_response"
        assert result.pending_action_set is False

    def test_turn_context_has_steps(self) -> None:
        from app.agent.llm_agent import AgentLoop

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    assistant_content="Done.",
                    finish_reason="stop",
                )
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(_session(), "Hello")

        assert len(result.turn.steps) > 0
        assert any(s.node == "llm_reason" for s in result.turn.steps)
        assert any(s.node == "finalize" for s in result.turn.steps)


class TestAgentLoopReadTools:
    """Tests: read tool execution."""

    def test_read_tool_then_respond(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.agent.models import ToolCallRequest

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="get_order_details",
                            arguments={"order_id": "#W5918442"},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    assistant_content="Your order #W5918442 is pending with 4 items.",
                    finish_reason="stop",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        session = _session()
        result = loop.run_turn(session, "Check my order #W5918442")

        assert "W5918442" in result.assistant_message
        assert result.turn.loop_iterations == 2
        assert result.turn.termination == "final_response"
        assert len(session.tool_results) == 1
        assert session.tool_results[0].tool_name == "get_order_details"
        assert session.tool_results[0].status == "success"

    def test_multi_read_tool_sequence(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.agent.models import ToolCallRequest

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="get_order_details",
                            arguments={"order_id": "#W5918442"},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_2",
                            tool_name="get_user_details",
                            arguments={"user_id": "sofia_rossi_8776"},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    assistant_content="I found your order and your account details.",
                    finish_reason="stop",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        session = _session()
        result = loop.run_turn(session, "Show my order and account")

        assert result.turn.loop_iterations == 3
        assert len(session.tool_results) == 2
        assert session.tool_results[0].tool_name == "get_order_details"
        assert session.tool_results[1].tool_name == "get_user_details"


class TestAgentLoopWritePending:
    """Tests: write tool requires confirmation."""

    def test_write_triggers_pending_confirmation(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.agent.models import ToolCallRequest
        from app.tools.retail_adapter import get_order_from_db

        gateway = _gateway()
        runtime = gateway.runtime
        db = runtime.db
        db_orders = db.get("orders", {})
        pending_order = next(
            (oid for oid, o in db_orders.items() if o.get("status") == "pending"),
            None,
        )
        assert pending_order is not None, "Need a pending order in test DB"

        order = get_order_from_db(db, pending_order)
        user_id = order["user_id"]

        session = _session(
            authenticated_user_id=user_id,
            active_user_identity={"user_id": user_id, "name": "Test User"},
        )
        session.loaded_context.orders[pending_order] = order

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_cancel",
                            tool_name="cancel_pending_order",
                            arguments={
                                "order_id": pending_order,
                                "reason": "no longer needed",
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=gateway,
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(session, "Cancel my order")

        assert result.pending_action_set is True
        assert session.pending_action is not None
        assert session.pending_action.action_name == "cancel_pending_order"
        assert session.pending_action.arguments.get("order_id") == pending_order
        assert "cancel" in result.assistant_message.lower()

    def test_write_without_read_before_write_blocks(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.agent.models import ToolCallRequest
        from app.tools.retail_adapter import get_order_from_db

        gateway = _gateway()
        runtime = gateway.runtime
        db = runtime.db
        db_orders = db.get("orders", {})
        pending_order = next(
            (oid for oid, o in db_orders.items() if o.get("status") == "pending"),
            None,
        )
        assert pending_order is not None

        order = get_order_from_db(db, pending_order)
        user_id = order["user_id"]

        session = _session(
            authenticated_user_id=user_id,
            active_user_identity={"user_id": user_id},
        )
        # Deliberately NOT loading order into loaded_context

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_cancel",
                            tool_name="cancel_pending_order",
                            arguments={
                                "order_id": pending_order,
                                "reason": "no longer needed",
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    assistant_content="I need to review the order details first.",
                    finish_reason="stop",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=gateway,
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(session, "Cancel my order")

        assert result.pending_action_set is True
        # Auto-load should have loaded the order and retried,
        # so the block should now be explicit_confirmation_required
        blocked = [r for r in session.tool_results if r.status == "blocked"]
        assert len(blocked) >= 2  # original + retry after auto-load
        assert blocked[-1].error == "explicit_confirmation_required"


class TestAgentLoopGuardBlock:
    """Tests: guard blocks (non-confirmation) become tool errors."""

    def test_cancel_delivered_order_guard_block(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.agent.models import ToolCallRequest
        from app.tools.retail_adapter import get_order_from_db

        gateway = _gateway()
        db = gateway.runtime.db
        db_orders = db.get("orders", {})
        delivered_order = next(
            (oid for oid, o in db_orders.items() if o.get("status") == "delivered"),
            None,
        )
        assert delivered_order is not None, "Need a delivered order in test DB"

        order = get_order_from_db(db, delivered_order)
        user_id = order["user_id"]

        session = _session(
            authenticated_user_id=user_id,
            active_user_identity={"user_id": user_id},
        )
        session.loaded_context.orders[delivered_order] = order

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_cancel",
                            tool_name="cancel_pending_order",
                            arguments={
                                "order_id": delivered_order,
                                "reason": "no longer needed",
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    assistant_content=(
                        "I cannot cancel this order because it has already been "
                        "delivered. Would you like to return it instead?"
                    ),
                    finish_reason="stop",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=gateway,
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(session, "Cancel my order")

        # With confirmation-before-policy, the guard asks for confirmation first.
        # The second mock response (about delivered) is reached when the LLM sees
        # the explicit_confirmation_required block and retries.
        assert "confirm" in result.assistant_message.lower()
        blocked = [r for r in session.tool_results if r.status == "blocked"]
        assert len(blocked) == 1
        assert blocked[0].error == "explicit_confirmation_required"


class TestAgentLoopToolErrors:
    """Tests: unknown tool, malformed args, missing args self-correction."""

    def test_unknown_tool_self_correction(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.agent.models import ToolCallRequest

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="hallucinated_tool",
                            arguments={},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_2",
                            tool_name="get_order_details",
                            arguments={"order_id": "#W5918442"},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    assistant_content="Found your order #W5918442.",
                    finish_reason="stop",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(_session(), "Check order")

        assert "W5918442" in result.assistant_message
        assert result.turn.loop_iterations == 3

    def test_malformed_arguments_self_correction(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.agent.models import ToolCallRequest

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="get_order_details",
                            arguments={},
                            raw_arguments="{not-json",
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_2",
                            tool_name="get_order_details",
                            arguments={"order_id": "#W5918442"},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    assistant_content="Found your order #W5918442.",
                    finish_reason="stop",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(_session(), "Check order")

        assert "W5918442" in result.assistant_message
        assert result.turn.loop_iterations == 3

class TestAgentLoopIntegration:
    """Tests: full integration with context builder and turn tracking."""

    def test_context_summary_in_prompt(self) -> None:
        from app.agent.llm_agent import AgentLoop

        session = _session()
        session.loaded_context.orders["O1"] = {
            "order_id": "O1", "user_id": "U1", "status": "pending",
            "items": [{"item_id": "I1", "name": "Widget"}],
        }

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    assistant_content="I see your pending order O1.",
                    finish_reason="stop",
                )
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(session, "Show my orders")

        assert "O1" in result.assistant_message
        assert result.turn.termination == "final_response"

    def test_pending_action_persisted_in_session(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.agent.models import ToolCallRequest
        from app.tools.retail_adapter import get_order_from_db

        gateway = _gateway()
        db = gateway.runtime.db
        db_orders = db.get("orders", {})
        pending_order = next(
            (oid for oid, o in db_orders.items() if o.get("status") == "pending"),
            None,
        )
        assert pending_order is not None

        order = get_order_from_db(db, pending_order)
        user_id = order["user_id"]
        session = _session(
            authenticated_user_id=user_id,
            active_user_identity={"user_id": user_id},
        )
        session.loaded_context.orders[pending_order] = order

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_cancel",
                            tool_name="cancel_pending_order",
                            arguments={
                                "order_id": pending_order,
                                "reason": "no longer needed",
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=gateway,
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(session, "Cancel")

        assert result.pending_action_set is True
        assert session.pending_action is not None
        assert session.pending_action.action_name == "cancel_pending_order"

    def test_turn_context_fully_populated(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.agent.models import ToolCallRequest

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="get_order_details",
                            arguments={"order_id": "#W5918442"},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    assistant_content="Order #W5918442 is pending.",
                    finish_reason="stop",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(_session(), "Check order")

        assert result.turn.loop_iterations == 2
        assert result.turn.termination == "final_response"
        assert len(result.turn.steps) >= 3
        step_nodes = {s.node for s in result.turn.steps}
        assert "llm_reason" in step_nodes
        assert "tool_execute" in step_nodes
        assert "finalize" in step_nodes
        assert result.turn.step_durations


class TestAgentLoopSafetyGuards:
    """Tests: max iterations, consecutive failures, provider timeout."""

    def test_max_iterations_exceeded(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.agent.models import ToolCallRequest

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{i}",
                            tool_name="get_order_details",
                            arguments={"order_id": "#W5918442"},
                        )
                    ],
                    finish_reason="tool_calls",
                )
                for i in range(10)
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
            max_iterations=3,
        )
        result = loop.run_turn(_session(), "Check order")

        assert result.turn.loop_iterations == 3
        assert result.turn.termination == "max_iterations"
        assert "transfer" in result.assistant_message.lower() or "human" in result.assistant_message.lower()

    def test_consecutive_failures_transfer(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.agent.models import ToolCallRequest

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{i}",
                            tool_name="unknown_tool",
                            arguments={},
                        )
                    ],
                    finish_reason="tool_calls",
                )
                for i in range(5)
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
            max_consecutive_failures=3,
        )
        result = loop.run_turn(_session(), "Help")

        assert result.turn.termination == "consecutive_failures"
        assert result.turn.consecutive_tool_failures >= 3

    def test_provider_timeout_safe_failure(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.agent.providers import FakeFailingProvider

        provider = FakeFailingProvider(error_type="timeout")
        loop = AgentLoop(
            provider=provider,
            gateway=_gateway(),
            registry=_registry(),
            context_builder=_context_builder(),
        )
        result = loop.run_turn(_session(), "Hello")

        assert result.turn.termination == "provider_timeout"
        assert len(result.assistant_message) > 0

    def test_missing_required_args_self_correction(self) -> None:
        from app.agent.llm_agent import AgentLoop
        from app.agent.models import ToolCallRequest
        from app.tools.retail_adapter import get_order_from_db

        gateway = _gateway()
        db = gateway.runtime.db
        db_orders = db.get("orders", {})
        pending_order_id = next(
            (oid for oid, o in db_orders.items() if o.get("status") == "pending"),
            None,
        )
        assert pending_order_id is not None, "Need a pending order in test DB"

        order = get_order_from_db(db, pending_order_id)
        user_id = order["user_id"]

        provider = ScriptedToolCallingProvider(
            responses=[
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="cancel_pending_order",
                            arguments={},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                ToolCallResponse(
                    tool_calls=[
                        ToolCallRequest(
                            id="call_2",
                            tool_name="cancel_pending_order",
                            arguments={
                                "order_id": pending_order_id,
                                "reason": "no longer needed",
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                ),
            ]
        )
        loop = AgentLoop(
            provider=provider,
            gateway=gateway,
            registry=_registry(),
            context_builder=_context_builder(),
        )
        session = _session(
            authenticated_user_id=user_id,
            active_user_identity={"user_id": user_id, "name": "Test User"},
        )
        session.loaded_context.orders[pending_order_id] = order
        result = loop.run_turn(session, "Cancel")

        assert result.turn.loop_iterations == 1
        assert result.pending_action_set is True
