from __future__ import annotations

import pytest

from app.agent.models import ToolCallRequest, ToolCallResponse, ToolExecutionError
from app.agent.providers import (
    FakeFailingProvider,
    ScriptedToolCallingProvider,
    normalize_tool_calling_message,
)


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


def test_scripted_provider_returns_scripted_tool_call() -> None:
    provider = ScriptedToolCallingProvider(
        responses=[
            ToolCallResponse(
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        tool_name="get_order_details",
                        arguments={"order_id": "ORDER-1"},
                    )
                ],
                finish_reason="tool_calls",
            )
        ]
    )

    response = provider.chat_with_tools(messages=[], tools=[])

    assert response.tool_calls[0].tool_name == "get_order_details"
    assert response.finish_reason == "tool_calls"


def test_scripted_provider_returns_final_text() -> None:
    provider = ScriptedToolCallingProvider(
        responses=[
            ToolCallResponse(
                assistant_content="I found your order.",
                finish_reason="stop",
            )
        ]
    )

    response = provider.chat_with_tools(messages=[], tools=[])

    assert response.assistant_content == "I found your order."
    assert response.tool_calls == []


def test_scripted_provider_raises_when_script_exhausted() -> None:
    provider = ScriptedToolCallingProvider(responses=[])

    with pytest.raises(RuntimeError, match="No scripted tool-calling responses remain"):
        provider.chat_with_tools(messages=[], tools=[])


def test_fake_failing_provider_timeout() -> None:
    provider = FakeFailingProvider(error_type="timeout")

    with pytest.raises(TimeoutError):
        provider.chat_with_tools(messages=[], tools=[])


def test_fake_failing_provider_malformed_arguments_response() -> None:
    provider = FakeFailingProvider(error_type="malformed_arguments")

    response = provider.chat_with_tools(messages=[], tools=[])

    assert response.tool_calls[0].tool_name == "get_order_details"
    assert response.tool_calls[0].arguments == {}
    assert response.tool_calls[0].raw_arguments == "{not-json"


def test_normalize_openai_style_tool_call_message() -> None:
    message = {
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "function": {
                    "name": "get_order_details",
                    "arguments": '{"order_id":"ORDER-1"}',
                },
            }
        ],
    }

    response = normalize_tool_calling_message(
        message=message,
        finish_reason="tool_calls",
        token_usage={"prompt_tokens": 10, "completion_tokens": 5},
        raw={"id": "chatcmpl_1"},
    )

    assert response.tool_calls[0].id == "call_1"
    assert response.tool_calls[0].tool_name == "get_order_details"
    assert response.tool_calls[0].arguments == {"order_id": "ORDER-1"}
    assert response.tool_calls[0].raw_arguments == '{"order_id":"ORDER-1"}'
    assert response.finish_reason == "tool_calls"
    assert response.token_usage == {"prompt_tokens": 10, "completion_tokens": 5}


def test_normalize_malformed_tool_arguments_preserves_raw() -> None:
    message = {
        "content": None,
        "tool_calls": [
            {
                "id": "call_bad",
                "function": {
                    "name": "get_order_details",
                    "arguments": "{not-json",
                },
            }
        ],
    }

    response = normalize_tool_calling_message(
        message=message,
        finish_reason="tool_calls",
        token_usage=None,
        raw={},
    )

    assert response.tool_calls[0].arguments == {}
    assert response.tool_calls[0].raw_arguments == "{not-json"


def test_normalize_final_assistant_message() -> None:
    response = normalize_tool_calling_message(
        message={"content": "Done.", "tool_calls": []},
        finish_reason="stop",
        token_usage=None,
        raw={},
    )

    assert response.assistant_content == "Done."
    assert response.tool_calls == []
