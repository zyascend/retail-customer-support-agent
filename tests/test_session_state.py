from __future__ import annotations

from app.agent.models import (
    AgentTurnResult,
    LoadedContext,
    Message,
    PendingAction,
    SessionState,
    ToolCallRecord,
    TurnContext,
)


def test_session_state_minimal_construction() -> None:
    session = SessionState(session_id="sess-1")
    assert session.session_id == "sess-1"
    assert session.task_id is None
    assert session.authenticated_user_id is None
    assert session.messages == []
    assert isinstance(session.loaded_context, LoadedContext)
    assert session.tool_results == []
    assert session.write_locks == []
    assert session.audit_logs == []
    assert session.pending_action is None


def test_session_state_holds_accumulated_data() -> None:
    session = SessionState(
        session_id="sess-2",
        authenticated_user_id="U1",
        auth_method="email",
        active_user_identity={"name": "Test User", "email": "test@example.com"},
    )
    session.messages.append(Message(role="user", content="hello"))
    session.tool_results.append(
        ToolCallRecord(
            tool_name="get_order_details",
            arguments={"order_id": "O1"},
            tool_kind="read",
            status="success",
        )
    )
    session.write_locks.append("order_O1_write_lock")
    session.pending_action = PendingAction(
        action_name="cancel_pending_order",
        arguments={"order_id": "O1", "reason": "no longer needed"},
        user_facing_summary="Cancel order O1",
    )
    assert len(session.messages) == 1
    assert len(session.tool_results) == 1
    assert session.pending_action.action_name == "cancel_pending_order"


def test_turn_context_defaults() -> None:
    turn = TurnContext()
    assert turn.steps == []
    assert turn.step_durations == {}
    assert turn.llm_call_durations == []
    assert turn.llm_token_usage is None
    assert turn.loop_iterations == 0
    assert turn.consecutive_tool_failures == 0
    assert turn.termination is None


def test_turn_context_records_loop_metadata() -> None:
    turn = TurnContext(
        step_durations={"identity_resolver": 45.2},
        llm_call_durations=[
            {"node": "policy_reasoner", "call_type": "json", "duration_ms": 185.2, "status": "ok"},
        ],
        llm_token_usage={"prompt_tokens": 500, "completion_tokens": 80, "total_tokens": 580},
        loop_iterations=3,
        termination="final_response",
    )
    assert turn.step_durations["identity_resolver"] == 45.2
    assert turn.llm_token_usage["total_tokens"] == 580
    assert turn.loop_iterations == 3


def test_session_state_roundtrip() -> None:
    session = SessionState(
        session_id="sess-3",
        authenticated_user_id="U2",
        auth_method="name_zip",
    )
    session.messages.append(Message(role="user", content="track my order"))
    session.loaded_context.orders["O1"] = {"order_id": "O1", "status": "pending"}

    data = session.model_dump()
    restored = SessionState.model_validate(data)

    assert restored.session_id == "sess-3"
    assert restored.authenticated_user_id == "U2"
    assert restored.loaded_context.orders["O1"]["status"] == "pending"


def test_turn_context_roundtrip() -> None:
    turn = TurnContext(
        step_durations={"response_generator": 0.5},
        loop_iterations=2,
        termination="final_response",
    )
    data = turn.model_dump()
    restored = TurnContext.model_validate(data)
    assert restored.step_durations == {"response_generator": 0.5}
    assert restored.loop_iterations == 2


def test_session_and_turn_are_independent() -> None:
    """Two models do not contain each other's fields."""
    session = SessionState(session_id="sess-4")
    turn = TurnContext()
    # SessionState now has steps for duck-type compatibility with ConversationState
    assert session.steps == []
    assert not hasattr(session, "loop_iterations")
    assert not hasattr(turn, "session_id")
    assert not hasattr(turn, "authenticated_user_id")


def test_session_state_has_steps_and_add_step() -> None:
    session = SessionState(session_id="sess-5")
    assert session.steps == []
    session.add_step("test_node", status="ok", key="val")
    assert len(session.steps) == 1
    assert session.steps[0].node == "test_node"
    assert session.steps[0].status == "ok"
    assert session.steps[0].detail == {"status": "ok", "key": "val"}


def test_agent_turn_result_construction() -> None:
    turn = TurnContext(loop_iterations=2, termination="final_response")
    result = AgentTurnResult(
        assistant_message="Hello",
        turn=turn,
        pending_action_set=False,
    )
    assert result.assistant_message == "Hello"
    assert result.turn.loop_iterations == 2
    assert result.turn.termination == "final_response"
    assert result.pending_action_set is False


def test_agent_turn_result_with_pending() -> None:
    result = AgentTurnResult(
        assistant_message="Should I cancel order O1?",
        turn=TurnContext(),
        pending_action_set=True,
    )
    assert result.pending_action_set is True


def test_session_state_stores_current_action_candidate() -> None:
    from app.agent.models import ActionCandidate

    candidate = ActionCandidate(
        tool_name="cancel_pending_order",
        confidence="high",
        reason="User asked to cancel an order.",
        order_id="#W1000001",
        required_read_tools=["get_order_details"],
    )
    session = SessionState(session_id="s1", current_action_candidate=candidate)

    assert session.current_action_candidate.tool_name == "cancel_pending_order"
    assert session.current_action_candidate.order_id == "#W1000001"
    assert session.current_action_candidate.required_read_tools == ["get_order_details"]
