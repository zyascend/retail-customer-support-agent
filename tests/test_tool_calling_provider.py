from __future__ import annotations

from app.agent.models import ToolCallRequest, ToolCallResponse, ToolExecutionError


def test_tool_call_response_defaults_to_no_tool_calls() -> None:
    response = ToolCallResponse()

    assert response.assistant_content is None
    assert response.tool_calls == []
    assert response.finish_reason is None
    assert response.token_usage is None


def test_tool_call_request_preserves_raw_arguments() -> None:
    request = ToolCallRequest(
        id="call_1",
        tool_name="get_order_details",
        arguments={"order_id": "ORDER-1"},
        raw_arguments='{"order_id":"ORDER-1"}',
    )

    assert request.id == "call_1"
    assert request.tool_name == "get_order_details"
    assert request.arguments == {"order_id": "ORDER-1"}
    assert request.raw_arguments == '{"order_id":"ORDER-1"}'


def test_tool_execution_error_has_retry_metadata() -> None:
    error = ToolExecutionError(
        error_type="missing_required_args",
        message_for_llm="The tool call is missing order_id.",
        retryable=True,
        missing_args=["order_id"],
    )

    assert error.status == "error"
    assert error.retryable is True
    assert error.missing_args == ["order_id"]
