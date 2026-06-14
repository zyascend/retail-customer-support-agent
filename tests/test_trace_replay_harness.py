from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.agent.models import (
    AgentTurnResult,
    SessionState,
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
                block_context={"confirmation_required": True},
            ),
        ]
        gateway = ScriptedToolGateway(results=results)

        r1 = gateway.execute(state=None, tool_name="get_order_details", arguments={"order_id": "W123"})
        self.assertEqual(r1.status, "success")
        self.assertEqual(r1.tool_name, "get_order_details")

        r2 = gateway.execute(state=None, tool_name="cancel_pending_order", arguments={"order_id": "W123", "reason": "no longer needed"})
        self.assertEqual(r2.status, "blocked")
        self.assertEqual(r2.error, "explicit_confirmation_required")
        self.assertEqual(r2.block_context, {"confirmation_required": True})

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

    def test_scripted_gateway_raises_on_argument_mismatch(self):
        from app.agent.replay import ScriptedToolGateway

        results = [
            ToolCallRecord(
                tool_name="get_order_details",
                arguments={"order_id": "W123"},
                tool_kind="read",
                status="success",
            ),
        ]
        gateway = ScriptedToolGateway(results=results)
        with self.assertRaises(RuntimeError) as ctx:
            gateway.execute(
                state=None,
                tool_name="get_order_details",
                arguments={"order_id": "W999"},
            )
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


class TraceReplayHarnessTests(unittest.TestCase):
    def _make_trace(self, tmp: str, llm_responses: list[dict], tool_calls: list[dict]) -> Path:
        trace = {
            "run_id": "test-replay",
            "llm_responses": llm_responses,
            "tool_calls": tool_calls,
            "messages": [],
            "steps": [],
        }
        path = Path(tmp) / "trace.json"
        path.write_text(json.dumps(trace))
        return path

    def _make_registry(self):
        from app.tools.registry import ToolRegistry
        registry = MagicMock(spec=ToolRegistry)
        registry.tools = {"get_order_details", "find_user_id_by_email", "cancel_pending_order"}
        registry.tool_schemas_for_llm.return_value = []
        registry.tool_catalog_for_llm.return_value = ""
        registry.required_args_for_tool.return_value = []
        return registry

    def _make_context_builder(self):
        from app.agent.context_builder import ContextBuilder
        builder = MagicMock(spec=ContextBuilder)
        builder.build.return_value = "state_summary_placeholder"
        builder.policy_text = ""
        return builder

    def test_replay_harness_loads_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = self._make_trace(tmp, [], [])
            registry = self._make_registry()
            from app.agent.replay import TraceReplayHarness
            harness = TraceReplayHarness(trace_path, registry)
            self.assertIsNotNone(harness)
            self.assertEqual(len(harness._responses), 0)
            self.assertEqual(len(harness._tool_results), 0)

    def test_replay_read_turn_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            responses = [
                ToolCallResponse(
                    assistant_content="I'll look up that order for you.",
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="get_order_details",
                            arguments={"order_id": "W123"},
                        )
                    ],
                    finish_reason="tool_calls",
                ).model_dump(),
                ToolCallResponse(
                    assistant_content="Your order #W123 is pending.",
                    finish_reason="stop",
                ).model_dump(),
            ]
            tool_calls = [
                ToolCallRecord(
                    tool_name="get_order_details",
                    arguments={"order_id": "W123"},
                    tool_kind="read",
                    status="success",
                    observation={"order_id": "W123", "status": "pending"},
                ).model_dump(),
            ]
            trace_path = self._make_trace(tmp, responses, tool_calls)
            registry = self._make_registry()
            context_builder = self._make_context_builder()

            from app.agent.replay import TraceReplayHarness
            harness = TraceReplayHarness(trace_path, registry)
            session = SessionState(session_id="replay-test")
            result = harness.replay(
                session,
                "What is the status of order #W123?",
                context_builder=context_builder,
            )
            self.assertIsInstance(result, AgentTurnResult)
            self.assertIn("pending", result.assistant_message)

    def test_replay_exhausted_llm_responses_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            responses = [
                ToolCallResponse(
                    assistant_content="Done.",
                    finish_reason="stop",
                ).model_dump(),
            ]
            trace_path = self._make_trace(tmp, responses, [])
            registry = self._make_registry()
            context_builder = self._make_context_builder()

            from app.agent.replay import TraceReplayHarness
            harness = TraceReplayHarness(trace_path, registry)
            session = SessionState(session_id="replay-test")
            result = harness.replay(
                session, "hello", context_builder=context_builder
            )
            self.assertIsInstance(result, AgentTurnResult)
            self.assertEqual(result.assistant_message, "Done.")

    def test_replay_with_write_pending_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            responses = [
                ToolCallResponse(
                    assistant_content="I'll cancel that order.",
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="cancel_pending_order",
                            arguments={"order_id": "W123", "reason": "no longer needed"},
                        )
                    ],
                    finish_reason="tool_calls",
                ).model_dump(),
            ]
            tool_calls = [
                ToolCallRecord(
                    tool_name="cancel_pending_order",
                    arguments={"order_id": "W123", "reason": "no longer needed"},
                    tool_kind="write",
                    status="blocked",
                    error="explicit_confirmation_required",
                ).model_dump(),
            ]
            trace_path = self._make_trace(tmp, responses, tool_calls)
            registry = self._make_registry()
            # Ensure cancel_pending_order is in the registry tools
            registry.tools.add("cancel_pending_order")
            context_builder = self._make_context_builder()

            from app.agent.replay import TraceReplayHarness
            harness = TraceReplayHarness(trace_path, registry)
            session = SessionState(session_id="replay-test")
            result = harness.replay(
                session, "Cancel order #W123", context_builder=context_builder
            )
            self.assertTrue(result.pending_action_set)
            self.assertIsNotNone(session.pending_action)
            self.assertEqual(session.pending_action.action_name, "cancel_pending_order")

    def test_replay_harness_rejects_out_of_order_repeated_tool_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            responses = [
                ToolCallResponse(
                    assistant_content="I'll check the second order.",
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="get_order_details",
                            arguments={"order_id": "W124"},
                        )
                    ],
                    finish_reason="tool_calls",
                ).model_dump(),
                ToolCallResponse(
                    assistant_content="Order W124 is pending.",
                    finish_reason="stop",
                ).model_dump(),
            ]
            tool_calls = [
                ToolCallRecord(
                    tool_name="get_order_details",
                    arguments={"order_id": "W123"},
                    tool_kind="read",
                    status="success",
                    observation={"order_id": "W123", "status": "pending"},
                ).model_dump(),
                ToolCallRecord(
                    tool_name="get_order_details",
                    arguments={"order_id": "W124"},
                    tool_kind="read",
                    status="success",
                    observation={"order_id": "W124", "status": "pending"},
                ).model_dump(),
            ]
            trace_path = self._make_trace(tmp, responses, tool_calls)
            registry = self._make_registry()

            from app.agent.replay import TraceReplayHarness

            with self.assertRaises(RuntimeError) as ctx:
                TraceReplayHarness(trace_path, registry)
            self.assertIn("Replay trace tool mismatch", str(ctx.exception))
