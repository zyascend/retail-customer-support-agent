from __future__ import annotations

import unittest

from app.agent.models import (
    ToolCallRecord,
    ToolCallRequest,
    ToolCallResponse,
    TurnContext,
)


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


class ScriptedToolGatewayTests(unittest.TestCase):
    def test_scripted_gateway_returns_recorded_results_in_order(self):
        from app.agent.replay import ScriptedToolGateway

        results = [
            ToolCallRecord(
                tool_name="get_order_details",
                arguments={"order_id": "W123"},
                tool_kind="read",
                status="success",
                observation={"status": "pending"},
            ),
            ToolCallRecord(
                tool_name="cancel_pending_order",
                arguments={"order_id": "W123", "reason": "no longer needed"},
                tool_kind="write",
                status="blocked",
                error="explicit_confirmation_required",
            ),
        ]
        gateway = ScriptedToolGateway(results=results)

        r1 = gateway.execute(state=None, tool_name="get_order_details", arguments={"order_id": "W123"})
        self.assertEqual(r1.status, "success")
        self.assertEqual(r1.tool_name, "get_order_details")

        r2 = gateway.execute(state=None, tool_name="cancel_pending_order", arguments={"order_id": "W123", "reason": "no longer needed"})
        self.assertEqual(r2.status, "blocked")
        self.assertEqual(r2.error, "explicit_confirmation_required")

    def test_scripted_gateway_raises_when_exhausted(self):
        from app.agent.replay import ScriptedToolGateway

        gateway = ScriptedToolGateway(results=[])
        with self.assertRaises(RuntimeError) as ctx:
            gateway.execute(state=None, tool_name="any_tool", arguments={})
        self.assertIn("No scripted tool results remain", str(ctx.exception))

    def test_scripted_gateway_raises_on_tool_name_mismatch(self):
        from app.agent.replay import ScriptedToolGateway

        results = [
            ToolCallRecord(
                tool_name="get_order_details",
                arguments={},
                tool_kind="read",
                status="success",
            ),
        ]
        gateway = ScriptedToolGateway(results=results)
        with self.assertRaises(RuntimeError) as ctx:
            gateway.execute(state=None, tool_name="wrong_tool", arguments={})
        self.assertIn("Tool mismatch", str(ctx.exception))

    def test_scripted_gateway_tracks_all_calls(self):
        from app.agent.replay import ScriptedToolGateway

        results = [
            ToolCallRecord(
                tool_name="find_user_id_by_email",
                arguments={"email": "test@test.com"},
                tool_kind="read",
                status="success",
                observation="user_1",
            ),
        ]
        gateway = ScriptedToolGateway(results=results)
        gateway.execute(state=None, tool_name="find_user_id_by_email", arguments={"email": "test@test.com"})

        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(gateway.calls[0]["tool_name"], "find_user_id_by_email")
        self.assertEqual(gateway.calls[0]["arguments"], {"email": "test@test.com"})
