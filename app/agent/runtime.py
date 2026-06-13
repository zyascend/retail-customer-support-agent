from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app.agent.action_specs import (
    WRITE_INTENTS,
)
from app.agent.builders import (
    merge_slots,
    normalize_llm_action_arguments,
    pending_action_has_required_args,
    pending_prompt,
)
from app.agent.confirmation import ConfirmationResolver
from app.agent.graph import PHASE1_NODES, build_linear_graph
from app.agent.llm_client import (
    apply_llm_action_plan,
    apply_llm_intent_slots,
    llm_chat,
    llm_json,
    llm_policy_decision,
)
from app.agent.models import (
    ConversationState,
    Message,
)
from app.agent.parsers import (
    NAME_ZIP_RE,
    clean_llm_list,
    clean_llm_scalar,
    code_missing_slots,
    has_assistant_response,
    infer_intent,
    last_assistant_message,
    merge_policy_decisions,
    parse_address,
    parse_item_replacement_pairs,
)
from app.agent.pipeline import (
    action_planner,
    context_loader,
    conversation_gate,
    identity_resolver,
    intent_and_slot_extractor,
    observation_reducer,
    policy_reasoner,
    receive_message,
    response_generator,
    run_logger,
    tool_executor,
    write_action_guard,
)
from app.agent.plan_handlers import (
    plan_address_change,
    plan_cancel,
    plan_exchange,
    plan_modify_items,
    plan_modify_payment,
    plan_return,
    plan_user_address,
    respond_with_order_lookup,
    set_pending,
    transfer_to_human,
)
from app.agent.prompts import (
    INTENT_SLOT_SYSTEM,
    prompt_metadata,
)
from app.agent.providers import DisabledLLMProvider, LLMProvider, build_default_provider
from app.config import AppConfig
from app.ops.tracing import TraceWriter, final_state_summary
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry
from app.tools.retail_adapter import RetailAdapter, RetailRuntime, get_order_from_db

GUARD_USER_MESSAGES = {
    "replacement_item_product_mismatch": "I can only replace an item with another available option from the same product.",
    "replacement_item_unavailable": "That replacement item is not available.",
    "replacement_item_count_mismatch": "The number of replacement items must match the number of items being replaced.",
    "replacement_item_not_found": "That replacement item could not be found in the catalog.",
    "order_item_not_found": "The item you want to replace is not in that order.",
    "payment_method_not_owned": "I can only use payment methods saved on your account.",
    "gift_card_balance_insufficient": "That gift card does not have enough balance for this order.",
    "same_payment_method": "The new payment method must be different from the current one.",
    "non_pending_order_cannot_be_modified": "I can only modify orders that are still pending.",
    "non_pending_order_cannot_be_cancelled": "I can only cancel orders that are still pending.",
    "non_delivered_order_cannot_be_returned": "I can only create returns for delivered orders.",
    "non_delivered_order_cannot_be_exchanged": "I can only create exchanges for delivered orders.",
    "exchange_item_count_mismatch": "The number of new items must match the number of items being exchanged.",
    "ownership_violation": "I cannot access or modify orders for another account.",
    "read_before_write_required": "I need to review the order details before making changes. Please ask me to look up the order first.",
    "authentication_required": "Please verify your identity before making changes.",
    "user_not_found": "I could not verify your account. Please provide different credentials.",
    "invalid_cancel_reason": "Please provide a valid cancellation reason: no longer needed or ordered by mistake.",
    "duplicate_write_lock": "A similar change is already in progress for this order.",
    "order_already_cancelled_or_locked": "This order has already been cancelled.",
    "order_items_already_modified": "The items in this order have already been modified.",
    "item_already_returned_or_exchanged": "One or more of these items has already been returned or exchanged.",
    "unsupported_in_mvp": "That write operation is not yet supported.",
    "unknown_write_action": "That update type is not recognised.",
    "explicit_confirmation_required": "Please confirm the requested update before proceeding.",
    "same_shipping_method": "That is already the current shipping method for this order.",
    "unknown_shipping_method": "That shipping method is not available. We offer standard, express, and overnight.",
    "payment_method_required_for_upgrade": "Upgrading to a faster shipping method requires a payment method. Please provide one.",
    "order_not_found": "That order could not be found.",
}


def _map_guard_error_to_user_message(error: str) -> str:
    """Return a user-readable message for a guard block reason."""
    return GUARD_USER_MESSAGES.get(
        str(error),
        "I could not complete that update. Please try again or contact support.",
    )


@dataclass
class AgentRunResult:
    run_id: str
    state: ConversationState
    trace_artifact_path: Path

    def as_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "termination_reason": self.state.termination_reason,
            "final_state": final_state_summary(self.state),
            "trace_artifact_path": str(self.trace_artifact_path),
        }


class AgentRuntime:
    def __init__(
        self,
        config: AppConfig,
        provider: Optional[LLMProvider] = None,
        require_llm: bool = False,
        runtime: Optional[RetailRuntime] = None,
    ) -> None:
        self.config = config
        if runtime is not None:
            self.retail_runtime = runtime
        else:
            self.retail_runtime = RetailAdapter(config).create_runtime()
        self.registry = ToolRegistry(self.retail_runtime.tools)
        self.gateway = ToolGateway(registry=self.registry, runtime=self.retail_runtime)
        self.confirmation_resolver = ConfirmationResolver()
        if isinstance(provider, DisabledLLMProvider):
            self.provider = None
        else:
            self.provider = provider or build_default_provider(
                api_key=config.deepseek_api_key,
                base_url=config.deepseek_base_url,
                model=config.default_agent_model,
                timeout=config.agent_llm_timeout_seconds,
                max_retries=config.agent_llm_max_retries,
                require_llm=require_llm,
            )
        self.graph = build_linear_graph(self._graph_node)

    def run_script(
        self,
        *,
        messages: Iterable[Dict[str, str]],
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        max_turns: int = 20,
    ) -> AgentRunResult:
        run_id = session_id or f"agent-{uuid.uuid4().hex[:12]}"
        state = ConversationState(session_id=run_id, task_id=task_id)
        initial_db_hash = self.retail_runtime.db_hash()
        for index, message in enumerate(messages):
            if index >= max_turns:
                state.termination_reason = "max_turns"
                break
            if message.get("role") != "user":
                continue
            self.handle_user_message(state, message.get("content", ""))
        if not state.termination_reason:
            state.termination_reason = "script_completed"
        trace_path = TraceWriter(self.config.run_artifact_dir).write(
            run_id=run_id,
            state=state,
            metadata={
                "runtime_source": self.retail_runtime.source,
                "model": self.config.default_agent_model,
                "llm_enabled": self.provider is not None,
                "llm_timeout_seconds": self.config.agent_llm_timeout_seconds,
                "llm_max_retries": self.config.agent_llm_max_retries,
                "initial_db_hash": initial_db_hash,
                "final_db_hash": self.retail_runtime.db_hash(),
                "tau2_bench_root": str(self.config.tau2_bench_root),
                "tau3_retail_root": str(self.config.tau3_retail_root),
                "retail_db_path": str(self.config.retail_db_path),
                "prompts": prompt_metadata(),
            },
        )
        return AgentRunResult(
            run_id=run_id,
            state=state,
            trace_artifact_path=trace_path,
        )

    def handle_user_message(self, state: ConversationState, content: str) -> str:
        state.messages.append(Message(role="user", content=content))
        if self.graph is not None:
            self.graph.invoke({"state": state, "content": content})
            if state.messages and state.messages[-1].role == "assistant":
                return state.messages[-1].content
            return ""
        for node in PHASE1_NODES:
            t0 = time.perf_counter()
            getattr(self, f"_{node}")(state, content)
            state.step_durations[node] = round((time.perf_counter() - t0) * 1000, 1)
        return self._last_assistant_message(state)

    def _graph_node(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        node = payload["current_node"]
        getattr(self, f"_{node}")(payload["state"], payload["content"])
        return payload

    def _receive_message(self, state: ConversationState, content: str) -> None:
        receive_message(state, content)

    def _conversation_gate(self, state: ConversationState, content: str) -> None:
        conversation_gate(
            state,
            content,
            self.confirmation_resolver,
            self.gateway,
            self._assistant,
            _map_guard_error_to_user_message,
        )

    def _identity_resolver(self, state: ConversationState, content: str) -> None:
        identity_resolver(
            state,
            content,
            self._has_assistant_response,
            self._assistant,
            self.gateway,
            self._identity_resolver_name_zip,
        )

    def _identity_resolver_name_zip(
        self, state: ConversationState, content: str
    ) -> bool:
        if state.authenticated_user_id or self._has_assistant_response(state):
            return False
        name_zip_match = NAME_ZIP_RE.search(content)
        if not name_zip_match:
            return False
        first_name, last_name, zip_code = name_zip_match.groups()
        record = self.gateway.execute(
            state=state,
            tool_name="find_user_id_by_name_zip",
            arguments={
                "first_name": first_name,
                "last_name": last_name,
                "zip": zip_code,
            },
        )
        if record.status != "success":
            self._assistant(state, "I could not verify that name and zip code.")
            return False
        user_id = str(record.observation)
        state.authenticated_user_id = user_id
        state.auth_method = "name_zip"
        state.active_user_identity = {
            "first_name": first_name,
            "last_name": last_name,
            "zip": zip_code,
            "user_id": user_id,
        }
        user_record = self.gateway.execute(
            state=state,
            tool_name="get_user_details",
            arguments={"user_id": user_id},
        )
        if user_record.status == "success":
            state.loaded_context.users[user_id] = user_record.observation
        state.add_step(
            "identity_resolver",
            status="authenticated",
            user_id=user_id,
            method="name_zip",
        )
        return True

    def _intent_and_slot_extractor(
        self, state: ConversationState, content: str
    ) -> None:
        intent_and_slot_extractor(
            state,
            content,
            has_assistant_fn=self._has_assistant_response,
            infer_intent_fn=self._infer_intent,
            llm_json_fn=self._llm_json,
            INTENT_SLOT_SYSTEM=INTENT_SLOT_SYSTEM,
            apply_llm_intent_slots_fn=self._apply_llm_intent_slots,
            parse_address_fn=self._parse_address,
            parse_item_replacement_pairs_fn=self._parse_item_replacement_pairs,
            parse_shipping_method_fn=self._parse_shipping_method,
            merge_slots_fn=self._merge_slots,
        )

    def _context_loader(self, state: ConversationState, content: str) -> None:
        context_loader(
            state,
            content,
            self._has_assistant_response,
            self.gateway,
            self._assistant,
        )

    def _code_missing_slots(self, state: ConversationState) -> list[str]:
        return code_missing_slots(state)

    def _merge_policy_decisions(
        self,
        *,
        code_decision: str,
        llm_decision: Optional[str],
    ) -> str:
        return merge_policy_decisions(
            code_decision=code_decision, llm_decision=llm_decision
        )

    def _policy_reasoner(self, state: ConversationState, content: str) -> None:
        policy_reasoner(
            state,
            content,
            has_assistant_fn=self._has_assistant_response,
            WRITE_INTENTS=WRITE_INTENTS,
            code_missing_slots_fn=self._code_missing_slots,
            llm_policy_decision_fn=self._llm_policy_decision,
            merge_policy_decisions_fn=self._merge_policy_decisions,
            clean_llm_scalar_fn=self._clean_llm_scalar,
        )

    def _action_planner(self, state: ConversationState, content: str) -> None:
        action_planner(
            state,
            content,
            has_assistant_fn=self._has_assistant_response,
            assistant_fn=self._assistant,
            transfer_to_human_fn=self._transfer_to_human,
            apply_llm_action_plan_fn=self._apply_llm_action_plan,
            respond_with_order_lookup_fn=self._respond_with_order_lookup,
            plan_cancel_fn=self._plan_cancel,
            plan_address_change_fn=self._plan_address_change,
            plan_modify_items_fn=self._plan_modify_items,
            plan_modify_payment_fn=self._plan_modify_payment,
            plan_user_address_fn=self._plan_user_address,
            plan_return_fn=self._plan_return,
            plan_exchange_fn=self._plan_exchange,
            plan_shipping_method_fn=self._plan_shipping_method,
        )

    def _transfer_to_human(self, state: ConversationState, content: str) -> None:
        transfer_to_human(state, content, self.gateway)

    def _write_action_guard(self, state: ConversationState, content: str) -> None:
        write_action_guard(state, content)

    def _tool_executor(self, state: ConversationState, content: str) -> None:
        tool_executor(state, content)

    def _observation_reducer(self, state: ConversationState, content: str) -> None:
        observation_reducer(state, content)

    def _response_generator(self, state: ConversationState, content: str) -> None:
        response_generator(
            state, content, self._has_assistant_response, self._assistant
        )

    def _run_logger(self, state: ConversationState, content: str) -> None:
        run_logger(state, content)

    def _plan_cancel(self, state: ConversationState) -> None:
        plan_cancel(state, self._assistant, self._set_pending)

    def _plan_address_change(self, state: ConversationState) -> None:
        plan_address_change(state, self._assistant, self._set_pending)

    def _plan_return(self, state: ConversationState) -> None:
        plan_return(state, self._assistant, self._set_pending)

    def _plan_exchange(self, state: ConversationState) -> None:
        plan_exchange(state, self._assistant, self._set_pending)

    def _plan_modify_items(self, state: ConversationState) -> None:
        plan_modify_items(state, self._assistant, self._set_pending)

    def _plan_modify_payment(self, state: ConversationState) -> None:
        plan_modify_payment(state, self._assistant, self._set_pending)

    def _plan_user_address(self, state: ConversationState) -> None:
        plan_user_address(state, self._assistant, self._set_pending)

    def _plan_shipping_method(self, state: ConversationState) -> None:
        from app.agent.plan_handlers import plan_shipping_method
        plan_shipping_method(state, self._assistant, self._set_pending)

    def _respond_with_order_lookup(self, state: ConversationState) -> None:
        respond_with_order_lookup(
            state,
            self._assistant,
            lambda oid: get_order_from_db(self.retail_runtime.db, oid),
        )

    def _set_pending(
        self,
        state: ConversationState,
        action_name: str,
        arguments: Dict[str, Any],
        prompt: str,
    ) -> None:
        set_pending(state, action_name, arguments, prompt, self._assistant)

    def _llm_json(
        self,
        state: ConversationState,
        node_name: str,
        system_prompt: str,
        payload: Dict[str, Any],
        schema: Dict[str, Any],
    ) -> Dict[str, Any]:
        return llm_json(state, node_name, system_prompt, payload, schema, self.provider)

    def _llm_chat(self, state: ConversationState, node_name: str, draft: str) -> str:
        return llm_chat(state, node_name, draft, self.provider)

    def _apply_llm_intent_slots(
        self, state: ConversationState, payload: Dict[str, Any]
    ) -> None:
        apply_llm_intent_slots(state, payload)

    def _merge_slots(
        self,
        *,
        code_slots: Dict[str, Any],
        llm_slots: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return merge_slots(
            code_slots=code_slots,
            llm_slots=llm_slots,
            clean_llm_scalar_fn=self._clean_llm_scalar,
        )

    def _llm_policy_decision(
        self, state: ConversationState, content: str, fallback_decision: str
    ) -> Dict[str, Any]:
        return llm_policy_decision(
            state,
            content,
            fallback_decision,
            self.retail_runtime.policy,
            self._llm_json,
        )

    def _apply_llm_action_plan(self, state: ConversationState, content: str) -> bool:
        return apply_llm_action_plan(
            state,
            content,
            llm_json_fn=self._llm_json,
            clean_llm_scalar_fn=self._clean_llm_scalar,
            normalize_fn=self._normalize_llm_action_arguments,
            has_required_args_fn=self._pending_action_has_required_args,
            pending_prompt_fn=self._pending_prompt,
            set_pending_fn=self._set_pending,
            transfer_fn=self._transfer_to_human,
            order_lookup_fn=self._respond_with_order_lookup,
            assistant_fn=self._assistant,
            tool_catalog=self.gateway.registry.tool_catalog_for_llm(),
        )

    def _pending_action_has_required_args(
        self, action_name: str, arguments: Dict[str, Any]
    ) -> bool:
        return pending_action_has_required_args(action_name, arguments)

    def _normalize_llm_action_arguments(
        self, action_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        return normalize_llm_action_arguments(
            action_name, arguments, self._clean_llm_scalar
        )

    def _pending_prompt(self, action_name: str, arguments: Dict[str, Any]) -> str:
        return pending_prompt(action_name, arguments)

    def _infer_intent(self, lowered: str) -> str:
        return infer_intent(lowered)

    def _parse_address(self, content: str) -> Optional[Dict[str, str]]:
        return parse_address(content)

    def _parse_item_replacement_pairs(self, lowered: str) -> list[tuple[str, str]]:
        return parse_item_replacement_pairs(lowered)

    def _parse_shipping_method(self, content: str) -> Optional[str]:
        from app.agent.parsers import parse_shipping_method
        return parse_shipping_method(content)

    def _assistant(
        self, state: ConversationState, content: str, allow_llm: bool = True
    ) -> None:
        final_content = content
        if allow_llm:
            final_content = (
                self._llm_chat(state, "response_generator", content) or content
            )
        state.messages.append(Message(role="assistant", content=final_content))

    def _has_assistant_response(self, state: ConversationState) -> bool:
        return has_assistant_response(state)

    def _last_assistant_message(self, state: ConversationState) -> str:
        return last_assistant_message(state)

    def _clean_llm_scalar(self, value: Any) -> Optional[str]:
        return clean_llm_scalar(value)

    def _clean_llm_list(self, value: Any) -> list[str]:
        return clean_llm_list(value)
