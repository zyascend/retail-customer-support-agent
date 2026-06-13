from __future__ import annotations

import unittest

from app.agent.models import TurnContext, ToolCallResponse, ToolCallRequest


class TurnContextRecordingTests(unittest.TestCase):
    def test_turn_context_has_llm_responses_field(self):
        turn = TurnContext()
        self.assertEqual(turn.llm_responses, [])

    def test_turn_context_can_store_llm_response(self):
        turn = TurnContext()
        response = ToolCallResponse(
            assistant_content="I found your order.",
            finish_reason="stop",
            token_usage={"total_tokens": 100},
        )
        turn.llm_responses.append(response.model_dump())
        self.assertEqual(len(turn.llm_responses), 1)
        self.assertEqual(turn.llm_responses[0]["finish_reason"], "stop")
        self.assertEqual(turn.llm_responses[0]["assistant_content"], "I found your order.")

    def test_turn_context_stores_multiple_llm_responses_per_turn(self):
        turn = TurnContext()
        r1 = ToolCallResponse(
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    tool_name="get_order_details",
                    arguments={"order_id": "W123"},
                )
            ],
            finish_reason="tool_calls",
        )
        r2 = ToolCallResponse(
            assistant_content="Done.",
            finish_reason="stop",
        )
        turn.llm_responses.append(r1.model_dump())
        turn.llm_responses.append(r2.model_dump())
        self.assertEqual(len(turn.llm_responses), 2)
        self.assertEqual(turn.llm_responses[0]["finish_reason"], "tool_calls")
        self.assertEqual(turn.llm_responses[1]["finish_reason"], "stop")
