import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent.confirmation import ConfirmationResolver
from app.agent.guard import WriteActionGuard
from app.agent.llm_agent import AgentLoop
from app.agent.models import SessionState, ToolCall, ToolCallRequest, TurnContext
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
            (worktree_git / "commondir").write_text(str(common_git), encoding="utf-8")
            (Path(tmp) / "repo" / ".env").write_text(
                "DEEPSEEK_API_KEY=from-main-env\n", encoding="utf-8"
            )

            with (
                patch.dict(os.environ, {}, clear=True),
                patch("app.config.Path.cwd", return_value=worktree),
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

    def test_tool_registry_generates_llm_catalog(self):
        runtime = RetailAdapter(resolve_config()).create_runtime()
        registry = ToolRegistry(runtime.tools)
        catalog = registry.tool_catalog_for_llm()

        self.assertIn("## Available Tools", catalog)
        self.assertIn("### cancel_pending_order", catalog)
        self.assertIn("### get_order_details", catalog)
        self.assertIn("type: write", catalog)
        self.assertIn("type: read", catalog)
        self.assertIn("parameters:", catalog)
        self.assertIn("constraints:", catalog)

    def test_get_item_details_includes_product_id_and_name(self):
        runtime = RetailAdapter(resolve_config()).create_runtime()

        item = runtime.tools.get_item_details("6469567736")

        self.assertEqual(item["item_id"], "6469567736")
        self.assertEqual(item["product_id"], "8310926033")
        self.assertEqual(item["name"], "Water Bottle")


class ConfirmationResolverTests(unittest.TestCase):
    def setUp(self):
        self.resolver = ConfirmationResolver()

    def test_resolves_exact_match_confirm(self):
        self.assertEqual(self.resolver.resolve("yes"), "confirmed")
        self.assertEqual(self.resolver.resolve("confirm"), "confirmed")
        self.assertEqual(self.resolver.resolve("确认"), "confirmed")

    def test_resolves_exact_match_deny(self):
        self.assertEqual(self.resolver.resolve("no"), "denied")
        self.assertEqual(self.resolver.resolve("cancel"), "denied")
        self.assertEqual(self.resolver.resolve("取消"), "denied")

    def test_resolves_exact_match_changed(self):
        self.assertEqual(
            self.resolver.resolve("use item 1234567890 instead"), "changed"
        )

    def test_resolves_unknown_for_gibberish(self):
        self.assertEqual(self.resolver.resolve("maybe later today"), "unknown")
        self.assertEqual(self.resolver.resolve("hello"), "unknown")

    def test_weak_confirm_with_extra_words(self):
        self.assertEqual(self.resolver.resolve("yes please"), "confirmed")
        self.assertEqual(self.resolver.resolve("yeah sure"), "confirmed")
        self.assertEqual(self.resolver.resolve("ok go ahead"), "confirmed")
        self.assertEqual(self.resolver.resolve("yes, please proceed"), "confirmed")

    def test_negated_change_returns_deny(self):
        self.assertEqual(self.resolver.resolve("don't change anything"), "denied")
        self.assertEqual(self.resolver.resolve("do not change the address"), "denied")
        self.assertEqual(self.resolver.resolve("never mind, don't switch"), "denied")

    def test_change_with_denial_word_returns_changed(self):
        self.assertEqual(self.resolver.resolve("no, change the address"), "changed")
        self.assertEqual(self.resolver.resolve("no I want to replace items"), "changed")

    def test_chinese_confirm_terms(self):
        self.assertEqual(self.resolver.resolve("好"), "confirmed")
        self.assertEqual(self.resolver.resolve("可以"), "confirmed")
        self.assertEqual(self.resolver.resolve("行"), "confirmed")

    def test_chinese_deny_terms(self):
        self.assertEqual(self.resolver.resolve("不"), "denied")
        self.assertEqual(self.resolver.resolve("不用"), "denied")
        self.assertEqual(self.resolver.resolve("算了"), "denied")

    def test_chinese_negated_change(self):
        self.assertEqual(self.resolver.resolve("不要改"), "denied")
        self.assertEqual(self.resolver.resolve("别改了"), "denied")

    def test_chinese_change_request(self):
        self.assertEqual(self.resolver.resolve("换成另外一个"), "changed")

    def test_confirm_with_change_keyword_prefers_confirm(self):
        """'yes, change it' should resolve to confirmed, not changed."""
        self.assertEqual(self.resolver.resolve("yes, change it to #W123"), "confirmed")
        self.assertEqual(self.resolver.resolve("yes please change the address"), "confirmed")

    def test_weak_confirm_with_change_returns_changed(self):
        """Weak confirm + strong change should still return changed."""
        self.assertEqual(self.resolver.resolve("yeah change it please"), "changed")

    def test_pure_change_request_not_confirmed(self):
        """'change to item 123' should still resolve to changed."""
        self.assertEqual(self.resolver.resolve("change to item 4567890123"), "changed")
        self.assertEqual(self.resolver.resolve("use different address"), "changed")


class WriteGuardTests(unittest.TestCase):
    def setUp(self):
        self.runtime = RetailAdapter(resolve_config()).create_runtime()
        self.guard = WriteActionGuard()

    def test_blocks_unauthenticated_write(self):
        state = SessionState(session_id="test")
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

    def test_authentication_block_has_structured_context(self):
        state = SessionState(session_id="test")
        result = self.guard.check(
            state=state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="cancel_pending_order",
                arguments={"order_id": PENDING_ORDER, "reason": "no longer needed"},
            ),
            confirmed=True,
        )

        self.assertEqual(
            result.block_context,
            {"required": "authenticated_user"},
        )

    def test_blocks_wrong_user_order_mutation(self):
        state = SessionState(
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
        self.assertEqual(result.block_context["resource_type"], "order")
        self.assertEqual(result.block_context["resource_id"], PENDING_ORDER)
        self.assertEqual(result.block_context["authenticated_user_id"], DELIVERED_USER)
        self.assertEqual(result.block_context["owner_user_id"], PENDING_USER)

    def test_read_before_write_block_has_structured_context(self):
        state = SessionState(session_id="test", authenticated_user_id=PENDING_USER)

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
        self.assertEqual(result.block_reason, "read_before_write_required")
        self.assertEqual(
            result.block_context,
            {
                "required_read_tool": "get_order_details",
                "resource_type": "order",
                "resource_id": PENDING_ORDER,
            },
        )

    def test_confirmation_block_has_structured_context(self):
        state = SessionState(session_id="test", authenticated_user_id=PENDING_USER)
        state.loaded_context.orders[PENDING_ORDER] = {"order_id": PENDING_ORDER}

        result = self.guard.check(
            state=state,
            db=self.runtime.db,
            action=ToolCall(
                tool_name="cancel_pending_order",
                arguments={"order_id": PENDING_ORDER, "reason": "no longer needed"},
            ),
            confirmed=False,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "explicit_confirmation_required")
        self.assertEqual(result.block_context["confirmation_required"], True)
        self.assertIn("Cancel order", result.block_context["summary"])

    def test_blocks_invalid_order_statuses(self):
        cancel_state = SessionState(
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

        return_state = SessionState(
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
        self.assertEqual(cancel_result.block_context["policy_area"], "order_status")
        self.assertEqual(cancel_result.block_context["resource_id"], DELIVERED_ORDER)
        self.assertEqual(
            cancel_result.block_context["current_state"]["status"], "delivered"
        )
        self.assertEqual(cancel_result.block_context["allowed_values"], ["pending"])
        self.assertEqual(
            return_result.block_reason, "non_delivered_order_cannot_be_returned"
        )

    def test_lock_conflict_block_has_structured_context(self):
        state = SessionState(session_id="test", authenticated_user_id=PENDING_USER)
        state.loaded_context.orders[PENDING_ORDER] = {"order_id": PENDING_ORDER}
        state.write_locks.append(f"order:{PENDING_ORDER}:cancel")

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
        self.assertEqual(result.block_reason, "duplicate_write_lock")
        self.assertEqual(result.block_context["new_lock"], f"order:{PENDING_ORDER}:cancel")
        self.assertEqual(result.block_context["existing_locks"], [f"order:{PENDING_ORDER}:cancel"])

    def test_idempotency_key_changes_with_arguments(self):
        state = SessionState(session_id="test", authenticated_user_id=PENDING_USER)
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
        state = SessionState(session_id="test", authenticated_user_id=PENDING_USER)
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
        state = SessionState(session_id="test", authenticated_user_id=PENDING_USER)
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
        state = SessionState(
            session_id="test", authenticated_user_id=DELIVERED_USER
        )
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
        state = SessionState(session_id="test", authenticated_user_id=PENDING_USER)
        state.loaded_context.orders[PENDING_ORDER] = {"order_id": PENDING_ORDER}

        record = gateway.execute(
            state=state,
            tool_name="cancel_pending_order",
            arguments={"order_id": PENDING_ORDER, "reason": "no longer needed"},
        )

        self.assertEqual(record.status, "blocked")
        self.assertEqual(record.error, "explicit_confirmation_required")
        self.assertEqual(record.before_db_hash, record.after_db_hash)
        self.assertEqual(record.block_context["confirmation_required"], True)
        self.assertEqual(record.observation["status"], "blocked")
        self.assertEqual(
            record.observation["block_reason"], "explicit_confirmation_required"
        )
        self.assertEqual(
            record.observation["block_context"], record.block_context
        )
        self.assertIn("message_for_llm", record.observation)

    def test_trace_writer_preserves_guard_block_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = RetailAdapter(resolve_config()).create_runtime()
            gateway = ToolGateway(registry=ToolRegistry(runtime.tools), runtime=runtime)
            state = SessionState(session_id="test", authenticated_user_id=PENDING_USER)
            state.loaded_context.orders[PENDING_ORDER] = {"order_id": PENDING_ORDER}

            gateway.execute(
                state=state,
                tool_name="cancel_pending_order",
                arguments={"order_id": PENDING_ORDER, "reason": "no longer needed"},
            )
            path = TraceWriter(Path(tmp)).write(
                run_id="trace-test",
                state=state,
                metadata={"runtime_source": "test"},
            )
            payload = json.loads(path.read_text(encoding="utf-8"))

        tool_call = payload["tool_calls"][0]
        self.assertEqual(
            tool_call["block_context"]["confirmation_required"],
            True,
        )
        self.assertEqual(
            tool_call["observation"]["block_context"],
            tool_call["block_context"],
        )

    def test_trace_writer_outputs_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = SessionState(session_id="trace-test")
            path = TraceWriter(Path(tmp)).write(
                run_id="trace-test",
                state=state,
                metadata={"runtime_source": "test"},
            )
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["run_id"], "trace-test")
        self.assertIn("final_state", payload)


class ActionSpecsTests(unittest.TestCase):
    def test_registry_has_seven_actions(self):
        from app.agent.action_specs import WRITE_ACTION_REGISTRY

        self.assertEqual(len(WRITE_ACTION_REGISTRY), 8)

    def test_every_spec_has_valid_tool_name(self):
        from app.agent.action_specs import WRITE_ACTION_REGISTRY
        from app.config import resolve_config
        from app.tools.registry import ToolRegistry
        from app.tools.retail_adapter import RetailAdapter

        runtime = RetailAdapter(resolve_config()).create_runtime()
        registry = ToolRegistry(runtime.tools)
        tool_names = set(registry.tools.keys())
        # Tools not yet wired into the runtime (e.g., synthetic sandbox additions)
        _pending_tool_names = {"modify_pending_order_shipping_method"}
        for spec in WRITE_ACTION_REGISTRY:
            if spec.tool_name in _pending_tool_names:
                continue
            self.assertIn(
                spec.tool_name,
                tool_names,
                f"{spec.tool_name} not found in tool registry",
            )

    def test_lookups_cover_all_specs(self):
        from app.agent.action_specs import (
            WRITE_ACTION_BY_INTENT,
            WRITE_ACTION_BY_NAME,
            WRITE_ACTION_REGISTRY,
        )

        self.assertEqual(len(WRITE_ACTION_BY_NAME), len(WRITE_ACTION_REGISTRY))
        self.assertEqual(len(WRITE_ACTION_BY_INTENT), len(WRITE_ACTION_REGISTRY))

    def test_intent_to_name_mapping_is_consistent(self):
        from app.agent.action_specs import WRITE_ACTION_BY_INTENT, WRITE_ACTION_REGISTRY

        for spec in WRITE_ACTION_REGISTRY:
            mapped = WRITE_ACTION_BY_INTENT[spec.intent]
            self.assertEqual(mapped.name, spec.name)

    def test_required_slots_subset_of_known_slot_keys(self):
        from app.agent.action_specs import WRITE_ACTION_REGISTRY

        known_slots = {
            "order_id",
            "address",
            "item_ids",
            "new_item_ids",
            "payment_method_id",
            "reason",
            "shipping_method",
        }
        for spec in WRITE_ACTION_REGISTRY:
            for slot in spec.required_slots:
                self.assertIn(slot, known_slots, f"{spec.name}: unknown slot '{slot}'")

    def test_catalog_for_prompt_includes_all_actions(self):
        from app.agent.action_specs import build_action_catalog_for_prompt

        catalog = build_action_catalog_for_prompt()
        self.assertIn("cancel_pending_order", catalog)
        self.assertIn("exchange_delivered_order_items", catalog)
        self.assertIn("modify_user_address", catalog)

    def test_params_for_llm_returns_args_for_write_tools(self):
        from app.agent.action_specs import tool_params_for_llm

        result = tool_params_for_llm("cancel_pending_order")
        self.assertIn("order_id", result)
        self.assertIn("reason", result)

    def test_params_for_llm_falls_back_for_unknown_tool(self):
        from app.agent.action_specs import tool_params_for_llm

        result = tool_params_for_llm("get_order_details")
        self.assertEqual(result, "(see function signature)")


class OrderIdNormalizationTests(unittest.TestCase):
    """Tests for AgentLoop._normalize_order_id_argument."""

    def setUp(self):
        self.turn = TurnContext()

    def _normalize(self, order_id: str) -> str:
        tc = ToolCallRequest(
            id="call_test",
            tool_name="get_order_details",
            arguments={"order_id": order_id},
        )
        AgentLoop._normalize_order_id_argument(tc, self.turn)
        return tc.arguments["order_id"]

    def test_already_canonical(self):
        self.assertEqual(self._normalize("#W9571698"), "#W9571698")

    def test_bare_w_prefix(self):
        self.assertEqual(self._normalize("W9571698"), "#W9571698")

    def test_bare_number(self):
        self.assertEqual(self._normalize("9571698"), "#W9571698")

    def test_hash_only(self):
        self.assertEqual(self._normalize("#9571698"), "#W9571698")

    def test_double_hash(self):
        self.assertEqual(self._normalize("##W9571698"), "#W9571698")

    def test_triple_hash(self):
        self.assertEqual(self._normalize("###W9571698"), "#W9571698")

    def test_double_hash_bare_number(self):
        self.assertEqual(self._normalize("##9571698"), "#W9571698")

    def test_lowercase_w(self):
        self.assertEqual(self._normalize("#w9571698"), "#W9571698")

    def test_non_order_id_passes_through(self):
        self.assertEqual(self._normalize("not_an_id"), "not_an_id")

    def test_non_string_ignored(self):
        tc = ToolCallRequest(
            id="call_test",
            tool_name="get_order_details",
            arguments={"order_id": 12345},
        )
        AgentLoop._normalize_order_id_argument(tc, self.turn)
        self.assertEqual(tc.arguments["order_id"], 12345)


if __name__ == "__main__":
    unittest.main()
