import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent.confirmation import ConfirmationResolver
from app.agent.guard import WriteActionGuard
from app.agent.models import ConversationState, ToolCall
from app.agent.providers import DisabledLLMProvider
from app.agent.runtime import AgentRuntime
from app.config import resolve_config
from app.ops.tracing import TraceWriter
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry
from app.tools.retail_adapter import RetailAdapter

PENDING_ORDER = "#W5918442"
PENDING_EMAIL = "sofia.rossi2645@example.com"
PENDING_USER = "sofia_rossi_8776"
DELIVERED_ORDER = "#W4817420"
DELIVERED_EMAIL = "ava.moore6020@example.com"
DELIVERED_USER = "ava_moore_2033"
DELIVERED_ITEM = "6777246137"
EXCHANGE_NEW_ITEM = "4579334072"
DELIVERED_PAYMENT = "gift_card_8168843"


class FakeLLMProvider:
    def __init__(self):
        self.json_nodes = []
        self.chat_calls = 0

    def json(self, messages, schema):
        system = messages[0]["content"]
        if "intent_and_slot_extractor" in system:
            self.json_nodes.append("intent_and_slot_extractor")
            return {
                "intent": "cancel_order",
                "slots": {
                    "order_id": PENDING_ORDER,
                    "reason": "ordered by mistake",
                },
            }
        if "policy_reasoner" in system:
            self.json_nodes.append("policy_reasoner")
            return {
                "decision": "allow",
                "intent": "cancel_order",
                "missing_slots": [],
                "user_confirmation_required": True,
                "explanation_for_user": "",
                "internal_reasoning_summary": "Pending cancellation is allowed.",
            }
        if "action_planner" in system:
            self.json_nodes.append("action_planner")
            return {
                "plan_type": "pending_write",
                "action_name": "cancel_pending_order",
                "arguments": {
                    "order_id": PENDING_ORDER,
                    "reason": "ordered by mistake",
                },
                "response": (
                    f"Cancel order {PENDING_ORDER} because ordered by mistake. "
                    "Please confirm yes or no."
                ),
            }
        return {}

    def chat(self, messages):
        self.chat_calls += 1
        draft = messages[-1]["content"].split("Draft response:\n", 1)[-1]
        return draft


class UnknownIntentLLMProvider:
    def json(self, messages, schema):
        system = messages[0]["content"]
        if "intent_and_slot_extractor" in system:
            return {"intent": "unknown", "slots": {}}
        if "policy_reasoner" in system:
            return {
                "decision": "transfer",
                "intent": "unknown",
                "missing_slots": [],
                "user_confirmation_required": False,
            }
        return {}

    def chat(self, messages):
        return messages[-1]["content"].split("Draft response:\n", 1)[-1]


class DenyingPolicyLLMProvider:
    def json(self, messages, schema):
        system = messages[0]["content"]
        if "intent_and_slot_extractor" in system:
            return {
                "intent": "cancel_order",
                "slots": {
                    "order_id": PENDING_ORDER,
                    "reason": "no longer needed",
                },
            }
        if "policy_reasoner" in system:
            return {
                "decision": "deny",
                "intent": "cancel_order",
                "missing_slots": [],
            }
        if "action_planner" in system:
            return {
                "plan_type": "pending_write",
                "action_name": "cancel_pending_order",
                "arguments": {
                    "order_id": PENDING_ORDER,
                    "reason": "no longer needed",
                },
            }
        return {}

    def chat(self, messages):
        return messages[-1]["content"].split("Draft response:\n", 1)[-1]


class AppConfigTests(unittest.TestCase):
    def test_resolves_env_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "TAU3_RETAIL_ROOT": str(Path(tmp) / "retail"),
                    "AGENT_ARTIFACT_DIR": str(Path(tmp) / "artifacts"),
                    "DEFAULT_AGENT_MODEL": "test-model",
                    "AGENT_LLM_TIMEOUT_SECONDS": "12.5",
                    "AGENT_LLM_MAX_RETRIES": "0",
                },
            ):
                config = resolve_config()

        self.assertEqual(config.default_agent_model, "test-model")
        self.assertEqual(config.agent_llm_timeout_seconds, 12.5)
        self.assertEqual(config.agent_llm_max_retries, 0)
        self.assertTrue(str(config.tau3_retail_root).endswith("retail"))
        self.assertTrue(str(config.artifact_dir).endswith("artifacts"))

    def test_loads_env_from_worktree_common_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp) / "repo" / ".worktrees" / "feature"
            common_git = Path(tmp) / "repo" / ".git"
            worktree_git = worktree / ".git"
            worktree.mkdir(parents=True)
            common_git.mkdir(parents=True)
            worktree_git.mkdir()
            (worktree_git / "commondir").write_text(
                str(common_git), encoding="utf-8"
            )
            (Path(tmp) / "repo" / ".env").write_text(
                "DEEPSEEK_API_KEY=from-main-env\n", encoding="utf-8"
            )

            with patch.dict(os.environ, {}, clear=True), patch(
                "app.config.Path.cwd", return_value=worktree
            ):
                config = resolve_config()

        self.assertEqual(config.deepseek_api_key, "from-main-env")


class RetailAdapterTests(unittest.TestCase):
    def test_adapter_loads_current_retail_runtime(self):
        config = resolve_config()
        runtime = RetailAdapter(config).create_runtime()

        self.assertIn(runtime.source, {"tau2-runtime", "local-fallback"})
        self.assertIn("Retail agent policy", runtime.policy[:200])
        self.assertIsNotNone(runtime.db_hash())

    def test_registry_classifies_tools(self):
        runtime = RetailAdapter(resolve_config()).create_runtime()
        registry = ToolRegistry(runtime.tools)

        self.assertEqual(registry.kind("get_order_details"), "read")
        self.assertEqual(registry.kind("cancel_pending_order"), "write")
        self.assertEqual(registry.kind("transfer_to_human_agents"), "generic")

    def test_local_tools_modify_pending_order_items(self):
        config = resolve_config()
        tools = RetailAdapter(config)._create_local_runtime("policy").tools

        updated = tools.modify_pending_order_items(
            order_id=PENDING_ORDER,
            item_ids=["1586641416"],
            new_item_ids=["5925362855"],
        )

        self.assertEqual(updated["status"], "pending (item modified)")
        self.assertIn("5925362855", [item["item_id"] for item in updated["items"]])
        self.assertNotIn("1586641416", [item["item_id"] for item in updated["items"]])

    def test_local_tools_modify_pending_order_payment(self):
        config = resolve_config()
        tools = RetailAdapter(config)._create_local_runtime("policy").tools

        updated = tools.modify_pending_order_payment(
            order_id="#W8855135",
            payment_method_id="credit_card_8105988",
        )

        self.assertEqual(updated["status"], "pending")
        self.assertEqual(
            updated["payment_history"][-1]["payment_method_id"],
            "credit_card_8105988",
        )
        self.assertEqual(updated["payment_history"][-1]["transaction_type"], "payment")


class ConfirmationResolverTests(unittest.TestCase):
    def test_resolves_confirmation_intents(self):
        resolver = ConfirmationResolver()

        self.assertEqual(resolver.resolve("yes"), "confirm")
        self.assertEqual(resolver.resolve("cancel"), "deny")
        self.assertEqual(resolver.resolve("use item 1234567890 instead"), "changed")
        self.assertEqual(resolver.resolve("maybe later today"), "unknown")


class WriteGuardTests(unittest.TestCase):
    def setUp(self):
        self.runtime = RetailAdapter(resolve_config()).create_runtime()
        self.guard = WriteActionGuard()

    def test_blocks_unauthenticated_write(self):
        state = ConversationState(session_id="test")
        result = self.guard.check(
            state=state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="cancel_pending_order",
                arguments={"order_id": PENDING_ORDER, "reason": "no longer needed"},
            ),
            confirmed=True,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "authentication_required")

    def test_blocks_wrong_user_order_mutation(self):
        state = ConversationState(
            session_id="test", authenticated_user_id=DELIVERED_USER
        )
        state.loaded_context.orders[PENDING_ORDER] = {"order_id": PENDING_ORDER}

        result = self.guard.check(
            state=state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="cancel_pending_order",
                arguments={"order_id": PENDING_ORDER, "reason": "no longer needed"},
            ),
            confirmed=True,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "ownership_violation")

    def test_blocks_invalid_order_statuses(self):
        cancel_state = ConversationState(
            session_id="test", authenticated_user_id=DELIVERED_USER
        )
        cancel_state.loaded_context.orders[DELIVERED_ORDER] = {
            "order_id": DELIVERED_ORDER
        }
        cancel_result = self.guard.check(
            state=cancel_state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="cancel_pending_order",
                arguments={"order_id": DELIVERED_ORDER, "reason": "no longer needed"},
            ),
            confirmed=True,
        )

        return_state = ConversationState(
            session_id="test", authenticated_user_id=PENDING_USER
        )
        return_state.loaded_context.orders[PENDING_ORDER] = {"order_id": PENDING_ORDER}
        return_result = self.guard.check(
            state=return_state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="return_delivered_order_items",
                arguments={
                    "order_id": PENDING_ORDER,
                    "item_ids": ["1725100896"],
                    "payment_method_id": "credit_card_5051208",
                },
            ),
            confirmed=True,
        )

        self.assertEqual(
            cancel_result.block_reason, "non_pending_order_cannot_be_cancelled"
        )
        self.assertEqual(
            return_result.block_reason, "non_delivered_order_cannot_be_returned"
        )

    def test_idempotency_key_changes_with_arguments(self):
        state = ConversationState(session_id="test", authenticated_user_id=PENDING_USER)
        state.loaded_context.orders[PENDING_ORDER] = {"order_id": PENDING_ORDER}

        first = self.guard.check(
            state=state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="cancel_pending_order",
                arguments={"order_id": PENDING_ORDER, "reason": "no longer needed"},
            ),
            confirmed=True,
        )
        second = self.guard.check(
            state=state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="cancel_pending_order",
                arguments={"order_id": PENDING_ORDER, "reason": "ordered by mistake"},
            ),
            confirmed=True,
        )

        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertNotEqual(first.idempotency_key, second.idempotency_key)

    def test_blocks_item_replacement_across_products(self):
        state = ConversationState(session_id="test", authenticated_user_id=PENDING_USER)
        state.loaded_context.orders[PENDING_ORDER] = {"order_id": PENDING_ORDER}

        result = self.guard.check(
            state=state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="modify_pending_order_items",
                arguments={
                    "order_id": PENDING_ORDER,
                    "item_ids": ["1586641416"],
                    "new_item_ids": ["9612497925"],
                },
            ),
            confirmed=True,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "replacement_item_product_mismatch")

    def test_blocks_payment_method_not_owned(self):
        state = ConversationState(session_id="test", authenticated_user_id=PENDING_USER)
        state.loaded_context.orders[PENDING_ORDER] = {"order_id": PENDING_ORDER}

        result = self.guard.check(
            state=state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="modify_pending_order_payment",
                arguments={
                    "order_id": PENDING_ORDER,
                    "payment_method_id": "gift_card_8168843",
                },
            ),
            confirmed=True,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "payment_method_not_owned")

    def test_blocks_exchange_across_products(self):
        state = ConversationState(session_id="test", authenticated_user_id=DELIVERED_USER)
        state.loaded_context.orders[DELIVERED_ORDER] = {"order_id": DELIVERED_ORDER}

        result = self.guard.check(
            state=state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="exchange_delivered_order_items",
                arguments={
                    "order_id": DELIVERED_ORDER,
                    "item_ids": [DELIVERED_ITEM],
                    "new_item_ids": ["5925362855"],
                    "payment_method_id": DELIVERED_PAYMENT,
                },
            ),
            confirmed=True,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "replacement_item_product_mismatch")


class GatewayAndTraceTests(unittest.TestCase):
    def test_gateway_blocks_write_without_confirmation(self):
        runtime = RetailAdapter(resolve_config()).create_runtime()
        gateway = ToolGateway(registry=ToolRegistry(runtime.tools), runtime=runtime)
        state = ConversationState(session_id="test", authenticated_user_id=PENDING_USER)
        state.loaded_context.orders[PENDING_ORDER] = {"order_id": PENDING_ORDER}

        record = gateway.execute(
            state=state,
            tool_name="cancel_pending_order",
            arguments={"order_id": PENDING_ORDER, "reason": "no longer needed"},
        )

        self.assertEqual(record.status, "blocked")
        self.assertEqual(record.error, "explicit_confirmation_required")
        self.assertEqual(record.before_db_hash, record.after_db_hash)

    def test_trace_writer_outputs_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = ConversationState(session_id="trace-test")
            path = TraceWriter(Path(tmp)).write(
                run_id="trace-test",
                state=state,
                metadata={"runtime_source": "test"},
            )
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["run_id"], "trace-test")
        self.assertIn("final_state", payload)


class RuntimeSmokeTests(unittest.TestCase):
    def _runtime(self, tmp: str) -> AgentRuntime:
        return AgentRuntime(
            resolve_config(artifact_dir=tmp),
            provider=DisabledLLMProvider(),
        )

    def test_scripted_authentication_and_order_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._runtime(tmp).run_script(
                session_id="lookup",
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"My email is {PENDING_EMAIL}. What is the status "
                            f"of order {PENDING_ORDER}?"
                        ),
                    }
                ],
            )

        assistant_messages = [
            message.content
            for message in result.state.messages
            if message.role == "assistant"
        ]
        self.assertIn("currently pending", assistant_messages[-1])
        self.assertEqual(result.state.authenticated_user_id, PENDING_USER)

    def test_scripted_pending_order_cancellation_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._runtime(tmp).run_script(
                session_id="cancel",
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"My email is {PENDING_EMAIL}. Cancel order "
                            f"{PENDING_ORDER} because no longer needed."
                        ),
                    },
                    {"role": "user", "content": "yes"},
                ],
            )
            self.assertTrue(result.trace_artifact_path.exists())

        self.assertIn("order:#W5918442:cancel", result.state.write_locks)
        self.assertEqual(result.state.confirmation_status, "confirmed")

    def test_scripted_address_modification(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._runtime(tmp).run_script(
                session_id="address",
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"My email is {PENDING_EMAIL}. Change address for "
                            f"order {PENDING_ORDER} address to 1 Main St, Apt 2, "
                            "Boston, MA, USA, 02108."
                        ),
                    },
                    {"role": "user", "content": "yes"},
                ],
            )

        self.assertIn("order:#W5918442:modify_address", result.state.write_locks)

    def test_scripted_delivered_order_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._runtime(tmp).run_script(
                session_id="return",
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"My email is {DELIVERED_EMAIL}. Return item "
                            f"{DELIVERED_ITEM} from order {DELIVERED_ORDER} "
                            f"to {DELIVERED_PAYMENT}."
                        ),
                    },
                    {"role": "user", "content": "confirm"},
                ],
            )

        self.assertTrue(
            any(
                lock.startswith(f"item:{DELIVERED_ITEM}:return")
                for lock in result.state.write_locks
            )
        )

    def test_scripted_human_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._runtime(tmp).run_script(
                session_id="transfer",
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"My email is {PENDING_EMAIL}. I want a human agent."
                        ),
                    }
                ],
            )

        self.assertEqual(
            result.state.messages[-1].content,
            "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.",
        )

    def test_llm_provider_drives_intent_policy_planner_and_response(self):
        provider = FakeLLMProvider()
        with tempfile.TemporaryDirectory() as tmp:
            runtime = AgentRuntime(
                resolve_config(artifact_dir=tmp),
                provider=provider,
            )
            result = runtime.run_script(
                session_id="llm-cancel",
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"My email is {PENDING_EMAIL}. I bought the wrong "
                            f"thing for order {PENDING_ORDER}."
                        ),
                    },
                    {"role": "user", "content": "yes"},
                ],
            )

        self.assertEqual(
            provider.json_nodes,
            [
                "intent_and_slot_extractor",
                "policy_reasoner",
                "action_planner",
            ],
        )
        self.assertGreaterEqual(provider.chat_calls, 1)
        self.assertIn("order:#W5918442:cancel", result.state.write_locks)
        self.assertEqual(result.state.slots["reason"], "ordered by mistake")

    def test_llm_unknown_intent_does_not_override_rule_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = AgentRuntime(
                resolve_config(artifact_dir=tmp),
                provider=UnknownIntentLLMProvider(),
            )
            result = runtime.run_script(
                session_id="llm-transfer",
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"My email is {PENDING_EMAIL}. I want a human agent."
                        ),
                    }
                ],
            )

        self.assertEqual(result.state.current_intent, "transfer")
        self.assertEqual(
            result.state.messages[-1].content,
            "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.",
        )

    def test_supported_write_policy_denial_defers_to_guard_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = AgentRuntime(
                resolve_config(artifact_dir=tmp),
                provider=DenyingPolicyLLMProvider(),
            )
            result = runtime.run_script(
                session_id="llm-deny-write",
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"My email is {PENDING_EMAIL}. Cancel order "
                            f"{PENDING_ORDER} because no longer needed."
                        ),
                    }
                ],
            )

        self.assertEqual(result.state.policy_decision.decision, "allow")
        self.assertIsNotNone(result.state.pending_action)
        self.assertEqual(
            result.state.pending_action.action_name,
            "cancel_pending_order",
        )


class AgentRuntimePhase5Tests(unittest.TestCase):
    def _runtime(self, tmp: str) -> AgentRuntime:
        return AgentRuntime(
            resolve_config(artifact_dir=tmp),
            provider=DisabledLLMProvider(),
        )

    def test_authenticates_by_name_and_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self._runtime(tmp)
            state = ConversationState(session_id="test")

            response = runtime.handle_user_message(
                state,
                "My name is Sofia Rossi and my zip code is 78784. What is the status of order #W5918442?",
            )

            self.assertIn("pending", response.lower())
            self.assertEqual(state.authenticated_user_id, "sofia_rossi_8776")
            self.assertEqual(state.auth_method, "name_zip")

    def test_plans_modify_order_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self._runtime(tmp)
            state = ConversationState(session_id="test")

            response = runtime.handle_user_message(
                state,
                (
                    f"My email is {PENDING_EMAIL}. Change item 1586641416 "
                    f"in order {PENDING_ORDER} to new item 5925362855."
                ),
            )

            self.assertIn("confirm", response.lower())
            self.assertEqual(state.current_intent, "modify_order_items")
            self.assertEqual(state.pending_action.action_name, "modify_pending_order_items")

    def test_plans_modify_order_payment(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self._runtime(tmp)
            state = ConversationState(session_id="test")

            response = runtime.handle_user_message(
                state,
                (
                    f"My email is {PENDING_EMAIL}. Change payment for "
                    f"order {PENDING_ORDER} to credit_card_8105988."
                ),
            )

            self.assertIn("confirm", response.lower())
            self.assertEqual(state.current_intent, "modify_order_payment")
            self.assertEqual(state.pending_action.action_name, "modify_pending_order_payment")

    def test_plans_modify_user_default_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self._runtime(tmp)
            state = ConversationState(session_id="test")

            response = runtime.handle_user_message(
                state,
                (
                    f"My email is {PENDING_EMAIL}. Change my default address to "
                    "12 Oak St, Unit 4, Austin, TX, USA, 78701."
                ),
            )

            self.assertIn("confirm", response.lower())
            self.assertEqual(state.current_intent, "modify_user_address")
            self.assertEqual(state.pending_action.action_name, "modify_user_address")

    def test_guard_block_response_is_user_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = self._runtime(tmp)
            state = ConversationState(session_id="test")

            runtime.handle_user_message(
                state,
                (
                    f"My email is {PENDING_EMAIL}. Change item 1586641416 in order "
                    f"{PENDING_ORDER} to new item 9612497925."
                ),
            )
            response = runtime.handle_user_message(state, "yes")

            self.assertIn("same product", response.lower())
            self.assertNotIn("replacement_item_product_mismatch", response)


if __name__ == "__main__":
    unittest.main()
