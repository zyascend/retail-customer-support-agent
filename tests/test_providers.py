from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.agent.providers import (
    DeepSeekProvider,
    _parse_json_maybe_repaired,
    build_default_provider,
    normalize_tool_calling_message,
)


class ProviderHelpersTests(unittest.TestCase):
    def test_parse_json_accepts_plain_json(self) -> None:
        parsed = _parse_json_maybe_repaired('{"order_id":"#W1","ok":true}')
        self.assertEqual(parsed, {"order_id": "#W1", "ok": True})

    def test_parse_json_accepts_markdown_fence_and_trailing_comma(self) -> None:
        parsed = _parse_json_maybe_repaired(
            '```json\n{"order_id":"#W1","item_ids":["1",],}\n```'
        )
        self.assertEqual(parsed, {"order_id": "#W1", "item_ids": ["1"]})

    def test_parse_json_repairs_python_literals(self) -> None:
        parsed = _parse_json_maybe_repaired('{"confirmed": True, "value": None}')
        self.assertEqual(parsed, {"confirmed": True, "value": None})

    def test_parse_json_falls_back_to_literal_eval_for_single_quotes(self) -> None:
        parsed = _parse_json_maybe_repaired("{'order_id': '#W1', 'item_ids': ['1']}")
        self.assertEqual(parsed, {"order_id": "#W1", "item_ids": ["1"]})

    def test_normalize_tool_calling_message_falls_back_to_empty_dict(self) -> None:
        response = normalize_tool_calling_message(
            message={
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "cancel_pending_order",
                            "arguments": '{"order_id": ',
                        },
                    }
                ],
            },
            finish_reason="tool_calls",
            token_usage=None,
        )
        self.assertEqual(response.tool_calls[0].arguments, {})
        self.assertEqual(response.tool_calls[0].raw_arguments, '{"order_id": ')


class DeepSeekProviderTests(unittest.TestCase):
    def _make_provider(self, max_retries: int = 2) -> DeepSeekProvider:
        with patch("app.agent.providers.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            return DeepSeekProvider(
                api_key="test-key",
                base_url="https://example.com",
                model="deepseek-test",
                max_retries=max_retries,
            )

    @patch("app.agent.providers.random.uniform", return_value=0.0)
    @patch("app.agent.providers.time.sleep")
    def test_rate_limit_retry_uses_retry_after_header(
        self,
        sleep_mock: MagicMock,
        _uniform_mock: MagicMock,
    ) -> None:
        provider = self._make_provider(max_retries=1)

        class FakeRateLimitError(Exception):
            def __init__(self) -> None:
                self.response = SimpleNamespace(headers={"Retry-After": "3"})

        success_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )
        provider._is_rate_limit_error = lambda exc: isinstance(exc, FakeRateLimitError)
        provider.client.chat.completions.create.side_effect = [
            FakeRateLimitError(),
            success_response,
        ]

        result = provider.chat([{"role": "user", "content": "hi"}])

        self.assertEqual(result, "ok")
        sleep_mock.assert_called_once_with(3.0)

    @patch("app.agent.providers.random.uniform", return_value=0.0)
    @patch("app.agent.providers.time.sleep")
    def test_timeout_retry_uses_exponential_backoff(
        self,
        sleep_mock: MagicMock,
        _uniform_mock: MagicMock,
    ) -> None:
        provider = self._make_provider(max_retries=1)

        class FakeTimeoutError(Exception):
            pass

        success_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )
        provider._is_timeout_error = lambda exc: isinstance(exc, FakeTimeoutError)
        provider.client.chat.completions.create.side_effect = [
            FakeTimeoutError(),
            success_response,
        ]

        result = provider.chat([{"role": "user", "content": "hi"}])

        self.assertEqual(result, "ok")
        sleep_mock.assert_called_once_with(0.5)

    @patch("app.agent.providers.random.uniform", return_value=0.0)
    @patch("app.agent.providers.time.sleep")
    def test_retry_stops_after_max_retries(
        self,
        sleep_mock: MagicMock,
        _uniform_mock: MagicMock,
    ) -> None:
        provider = self._make_provider(max_retries=1)

        class FakeTimeoutError(Exception):
            pass

        provider._is_timeout_error = lambda exc: isinstance(exc, FakeTimeoutError)
        provider.client.chat.completions.create.side_effect = [
            FakeTimeoutError(),
            FakeTimeoutError(),
        ]

        with self.assertRaises(FakeTimeoutError):
            provider.chat([{"role": "user", "content": "hi"}])

        sleep_mock.assert_called_once_with(0.5)

    @patch("app.agent.providers.time.sleep")
    def test_non_transient_error_does_not_retry(self, sleep_mock: MagicMock) -> None:
        provider = self._make_provider(max_retries=2)
        provider.client.chat.completions.create.side_effect = ValueError("boom")

        with self.assertRaises(ValueError):
            provider.chat([{"role": "user", "content": "hi"}])

        sleep_mock.assert_not_called()

    @patch("app.agent.providers.random.uniform", return_value=0.0)
    @patch("app.agent.providers.time.sleep")
    def test_json_retries_on_parse_failure_then_succeeds(
        self,
        _sleep_mock: MagicMock,
        _uniform_mock: MagicMock,
    ) -> None:
        provider = self._make_provider(max_retries=1)
        bad_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"value": '))]
        )
        good_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"value": 1}'))]
        )
        provider.client.chat.completions.create.side_effect = [bad_response, good_response]

        result = provider.json([{"role": "user", "content": "hi"}], schema={})

        self.assertEqual(result, {"value": 1})

    def test_chat_with_tools_preserves_reasoning_usage_and_parsed_args(self) -> None:
        provider = self._make_provider(max_retries=0)
        tool_call = SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(
                name="cancel_pending_order",
                arguments="{'order_id': '#W1', 'reason': 'no longer needed'}",
            ),
        )
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[tool_call],
                        reasoning_content="reasoning",
                    ),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )
        provider.client.chat.completions.create.return_value = response

        result = provider.chat_with_tools(
            [{"role": "user", "content": "hi"}],
            [{"type": "function", "function": {"name": "cancel_pending_order"}}],
        )

        self.assertEqual(result.reasoning_content, "reasoning")
        self.assertEqual(result.token_usage, {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})
        self.assertEqual(
            result.tool_calls[0].arguments,
            {"order_id": "#W1", "reason": "no longer needed"},
        )


class BuildDefaultProviderTests(unittest.TestCase):
    def test_build_default_provider_returns_none_when_llm_not_required(self) -> None:
        provider = build_default_provider(
            api_key="",
            base_url="https://example.com",
            model="deepseek-test",
            require_llm=False,
        )
        self.assertIsNone(provider)

    def test_build_default_provider_raises_when_llm_required(self) -> None:
        with self.assertRaises(ValueError):
            build_default_provider(
                api_key="",
                base_url="https://example.com",
                model="deepseek-test",
                require_llm=True,
            )


if __name__ == "__main__":
    unittest.main()
