from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app.agent.confirmation import ConfirmationResolver
from app.agent.graph import PHASE1_NODES, build_linear_graph
from app.agent.models import (
    ConversationState,
    Message,
    PendingAction,
    PolicyDecision,
)
from app.agent.prompts import (
    ACTION_PLANNER_SYSTEM,
    INTENT_SLOT_SYSTEM,
    POLICY_SYSTEM,
    RESPONSE_SYSTEM,
    prompt_metadata,
    user_json_prompt,
)
from app.agent.providers import DisabledLLMProvider, LLMProvider, build_default_provider
from app.config import AppConfig
from app.ops.tracing import TraceWriter, final_state_summary
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry
from app.tools.retail_adapter import RetailAdapter, get_order_from_db

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
NAME_ZIP_RE = re.compile(
    r"(?:my name is|i am|i'm)\s+([A-Za-z]+)\s+([A-Za-z]+).*?\bzip(?: code)? is\s+(\d{5}(?:-\d{4})?)",
    re.IGNORECASE,
)
ORDER_RE = re.compile(r"#W\d+")
ITEM_RE = re.compile(r"\b\d{8,}\b")
PAYMENT_RE = re.compile(r"\b(?:gift_card|credit_card|paypal)_\d+\b")
SUPPORTED_INTENTS = {
    "lookup",
    "cancel_order",
    "modify_order_address",
    "modify_order_items",
    "modify_order_payment",
    "modify_user_address",
    "return_items",
    "exchange_items",
    "transfer",
    "unknown",
}
SUPPORTED_PENDING_ACTIONS = {
    "cancel_pending_order",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
    "exchange_delivered_order_items",
}

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
    ) -> None:
        self.config = config
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
            getattr(self, f"_{node}")(state, content)
        return self._last_assistant_message(state)

    def _graph_node(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        node = payload["current_node"]
        getattr(self, f"_{node}")(payload["state"], payload["content"])
        return payload

    def _receive_message(self, state: ConversationState, content: str) -> None:
        state.add_step("receive_message", content=content)

    def _conversation_gate(self, state: ConversationState, content: str) -> None:
        if state.pending_action:
            resolution = self.confirmation_resolver.resolve(content)
            state.confirmation_status = {
                "confirm": "confirmed",
                "deny": "denied",
                "changed": "changed",
                "unknown": "unknown",
            }[resolution]
            state.add_step("conversation_gate", confirmation=resolution)
            if resolution == "confirm":
                action = state.pending_action
                record = self.gateway.execute(
                    state=state,
                    tool_name=action.action_name,
                    arguments=action.arguments,
                    confirmed=True,
                )
                state.pending_action = None
                if record.status == "success":
                    self._assistant(
                        state,
                        "Done. I have completed the requested update.",
                    )
                else:
                    self._assistant(
                        state,
                        _map_guard_error_to_user_message(str(record.error)),
                    )
            elif resolution == "deny":
                state.pending_action = None
                self._assistant(state, "No changes were made.")
            elif resolution == "changed":
                state.pending_action = None
                state.slots = {}
                self._assistant(
                    state,
                    "I discarded the previous request. Please provide updated details.",
                )
            else:
                self._assistant(
                    state,
                    "Please confirm yes or no: "
                    f"{state.pending_action.user_facing_summary}",
                )
            return
        state.add_step(
            "conversation_gate",
            authenticated=bool(state.authenticated_user_id),
        )

    def _identity_resolver(self, state: ConversationState, content: str) -> None:
        if state.authenticated_user_id or self._has_assistant_response(state):
            return
        email_match = EMAIL_RE.search(content)
        if not email_match:
            if self._identity_resolver_name_zip(state, content):
                return
            self._assistant(
                state,
                "Please provide the email address on your account so I can verify you.",
            )
            state.add_step("identity_resolver", status="need_user_info")
            return
        email = email_match.group(0)
        record = self.gateway.execute(
            state=state,
            tool_name="find_user_id_by_email",
            arguments={"email": email},
        )
        if record.status != "success":
            self._assistant(state, "I could not verify that email address.")
            return
        user_id = str(record.observation)
        state.authenticated_user_id = user_id
        state.auth_method = "email"
        state.active_user_identity = {"email": email, "user_id": user_id}
        user_record = self.gateway.execute(
            state=state,
            tool_name="get_user_details",
            arguments={"user_id": user_id},
        )
        if user_record.status == "success":
            state.loaded_context.users[user_id] = user_record.observation
        state.add_step("identity_resolver", status="authenticated", user_id=user_id)

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
        state.active_user_identity = {"first_name": first_name, "last_name": last_name, "zip": zip_code, "user_id": user_id}
        user_record = self.gateway.execute(
            state=state,
            tool_name="get_user_details",
            arguments={"user_id": user_id},
        )
        if user_record.status == "success":
            state.loaded_context.users[user_id] = user_record.observation
        state.add_step("identity_resolver", status="authenticated", user_id=user_id, method="name_zip")
        return True

    def _intent_and_slot_extractor(
        self, state: ConversationState, content: str
    ) -> None:
        if self._has_assistant_response(state):
            return
        lowered = content.lower()
        # Preserve existing intent when message is a bare confirmation/denial
        bare_response = lowered.strip() in {
            "yes", "no", "confirm", "ok", "y", "n", "go ahead",
            "proceed", "sure", "yeah", "yep", "nope", "cancel",
        }
        if bare_response and state.current_intent and state.current_intent != "unknown":
            pass  # keep prior intent rather than resetting to unknown
        else:
            state.current_intent = self._infer_intent(lowered)
        llm_payload = self._llm_json(
            state,
            "intent_and_slot_extractor",
            INTENT_SLOT_SYSTEM,
            {
                "user_message": content,
                "known_slots": state.slots,
                "authenticated_user_id": state.authenticated_user_id,
            },
            {
                "type": "object",
                "properties": {
                    "intent": {"type": "string"},
                    "slots": {"type": "object"},
                },
            },
        )
        if llm_payload:
            llm_intent = str(llm_payload.get("intent") or "").strip()
            if llm_intent and llm_intent != state.current_intent:
                state.add_step(
                    "intent_and_slot_extractor_divergence",
                    code_intent=state.current_intent,
                    llm_intent=llm_intent,
                    resolved=state.current_intent,
                )
            self._apply_llm_intent_slots(state, llm_payload)
        llm_slots = (llm_payload.get("slots") or {}) if llm_payload else {}
        code_slots: Dict[str, Any] = dict(state.slots)

        order_match = ORDER_RE.search(content)
        if order_match:
            code_slots["order_id"] = order_match.group(0)
        payment_match = PAYMENT_RE.search(content)
        if payment_match:
            code_slots["payment_method_id"] = payment_match.group(0)
        item_ids = [
            item
            for item in ITEM_RE.findall(content)
            if not item.startswith("000") and len(item) >= 8
        ]
        if item_ids:
            code_slots["item_ids"] = item_ids
        if "ordered by mistake" in lowered:
            code_slots["reason"] = "ordered by mistake"
        elif "no longer needed" in lowered or "don't need" in lowered:
            code_slots["reason"] = "no longer needed"
        address = self._parse_address(content)
        if address:
            code_slots["address"] = address
        item_pairs = self._parse_item_replacement_pairs(lowered)
        if item_pairs:
            code_slots["item_ids"] = [old for old, _new in item_pairs]
            code_slots["new_item_ids"] = [new for _old, new in item_pairs]

        new_item_marker = re.search(
            r"(?:new items?|exchange for|instead|to new item|"
            r"for new items?)\s+(\d{8,})",
            lowered,
        )
        if new_item_marker:
            new_item_id = new_item_marker.group(1)
            code_slots["new_item_ids"] = [new_item_id]
            if "item_ids" in code_slots:
                code_slots["item_ids"] = [
                    iid for iid in code_slots["item_ids"]
                    if iid != new_item_id
                ]

        state.slots = self._merge_slots(
            code_slots=code_slots,
            llm_slots=llm_slots,
        )

    def _context_loader(self, state: ConversationState, content: str) -> None:
        if self._has_assistant_response(state):
            return
        order_id = state.slots.get("order_id")
        if order_id and order_id not in state.loaded_context.orders:
            record = self.gateway.execute(
                state=state,
                tool_name="get_order_details",
                arguments={"order_id": order_id},
            )
            if record.status == "success":
                order = record.observation
                state.loaded_context.orders[order_id] = order
                if order.get("user_id") != state.authenticated_user_id:
                    self._assistant(
                        state,
                        "I cannot access or modify orders for another account.",
                    )
            else:
                self._assistant(state, f"I could not find order {order_id}.")
        state.add_step(
            "context_loader",
            loaded_orders=list(state.loaded_context.orders),
        )

    def _code_missing_slots(self, state: ConversationState) -> list[str]:
        """Code-side check for missing required slots per intent."""
        required_map: Dict[str, tuple[str, ...]] = {
            "cancel_order": ("order_id", "reason"),
            "modify_order_address": ("order_id", "address"),
            "modify_order_items": ("order_id", "item_ids", "new_item_ids"),
            "modify_order_payment": ("order_id", "payment_method_id"),
            "modify_user_address": ("address",),
            "return_items": ("order_id", "item_ids", "payment_method_id"),
            "exchange_items": (
                "order_id", "item_ids", "new_item_ids", "payment_method_id",
            ),
        }
        required = required_map.get(state.current_intent, ())
        return [key for key in required if not state.slots.get(key)]

    def _merge_policy_decisions(
        self,
        *,
        code_decision: str,
        llm_decision: Optional[str],
    ) -> str:
        """Conservative dual-track merge.
        Any deny → deny. Any ask → ask. Transfer needs both to agree.
        Only allow when both allow.
        """
        if llm_decision is None:
            return code_decision
        # Code-level transfer (unsupported requests) overrides LLM deny
        if code_decision == "transfer" and llm_decision == "deny":
            return "transfer"
        if "deny" in (code_decision, llm_decision):
            return "deny"
        if "ask_clarification" in (code_decision, llm_decision):
            return "ask_clarification"
        if code_decision == "transfer" and llm_decision == "transfer":
            return "transfer"
        if code_decision == "transfer" or llm_decision == "transfer":
            return "ask_clarification"
        return "allow"

    def _policy_reasoner(self, state: ConversationState, content: str) -> None:
        if self._has_assistant_response(state):
            return
        write_intents = {
            "cancel_order",
            "modify_order_address",
            "modify_order_items",
            "modify_order_payment",
            "modify_user_address",
            "return_items",
            "exchange_items",
        }

        # ── Code track ──
        if state.current_intent == "transfer":
            code_decision = "transfer"
        elif state.current_intent == "lookup":
            code_decision = "allow"
        elif state.current_intent in write_intents:
            if self._code_missing_slots(state):
                code_decision = "ask_clarification"
            else:
                code_decision = "allow"
        else:
            code_decision = "ask_clarification"

        # ── LLM track ──
        llm_payload = self._llm_policy_decision(state, content, code_decision)
        llm_decision = llm_payload.get("decision") if llm_payload else None

        # ── Conservative merge ──
        final_decision = self._merge_policy_decisions(
            code_decision=code_decision,
            llm_decision=llm_decision,
        )

        # Log divergence for audit
        if llm_decision and llm_decision != code_decision:
            state.add_step(
                "policy_reasoner_divergence",
                code=code_decision,
                llm=llm_decision,
                merged=final_decision,
            )

        explanation = ""
        if llm_payload and final_decision == "deny":
            explanation = self._clean_llm_scalar(
                llm_payload.get("explanation_for_user")
            ) or ""

        state.policy_decision = PolicyDecision(
            decision=final_decision,
            intent=(
                llm_payload.get("intent", state.current_intent)
                if llm_payload
                else state.current_intent
            ),
            missing_slots=(
                llm_payload.get("missing_slots")
                if llm_payload and isinstance(llm_payload.get("missing_slots"), list)
                else []
            ),
            user_confirmation_required=(
                llm_payload.get("user_confirmation_required", False)
                if llm_payload
                else state.current_intent in write_intents
            ),
            explanation_for_user=explanation,
            internal_reasoning_summary=(
                llm_payload.get("internal_reasoning_summary", "")
                if llm_payload
                else ""
            ),
        )
        state.add_step(
            "policy_reasoner",
            decision=final_decision,
            llm_used=bool(llm_payload),
            code_decision=code_decision,
        )

    def _action_planner(self, state: ConversationState, content: str) -> None:
        if self._has_assistant_response(state):
            return
        if state.policy_decision and state.policy_decision.decision == "deny":
            self._assistant(
                state,
                state.policy_decision.explanation_for_user
                or "I cannot complete that request under the retail policy.",
            )
            return
        if state.policy_decision and state.policy_decision.decision == "transfer":
            self._transfer_to_human(state, content)
            return
        if self._apply_llm_action_plan(state, content):
            return
        intent = state.current_intent
        if intent == "transfer":
            self._transfer_to_human(state, content)
            return
        if intent == "lookup":
            self._respond_with_order_lookup(state)
            return
        if intent == "cancel_order":
            self._plan_cancel(state)
            return
        if intent == "modify_order_address":
            self._plan_address_change(state)
            return
        if intent == "modify_order_items":
            self._plan_modify_items(state)
            return
        if intent == "modify_order_payment":
            self._plan_modify_payment(state)
            return
        if intent == "modify_user_address":
            self._plan_user_address(state)
            return
        if intent == "return_items":
            self._plan_return(state)
            return
        if intent == "exchange_items":
            self._plan_exchange(state)
            return
        self._assistant(
            state,
            "Please tell me which order or retail support action you need help with.",
        )

    def _transfer_to_human(self, state: ConversationState, content: str) -> None:
        self.gateway.execute(
            state=state,
            tool_name="transfer_to_human_agents",
            arguments={"summary": content[:500]},
        )
        self._assistant(
            state,
            "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.",
            allow_llm=False,
        )

    def _write_action_guard(self, state: ConversationState, content: str) -> None:
        state.add_step(
            "write_action_guard",
            pending_action=(
                state.pending_action.model_dump() if state.pending_action else None
            ),
        )

    def _tool_executor(self, state: ConversationState, content: str) -> None:
        state.add_step(
            "tool_executor",
            deferred_pending_write=bool(state.pending_action),
        )

    def _observation_reducer(self, state: ConversationState, content: str) -> None:
        state.add_step("observation_reducer", tool_result_count=len(state.tool_results))

    def _response_generator(self, state: ConversationState, content: str) -> None:
        if not self._has_assistant_response(state):
            self._assistant(state, "I need a bit more information to help with that.")
        state.add_step("response_generator", last_message=state.messages[-1].content)

    def _run_logger(self, state: ConversationState, content: str) -> None:
        state.add_step("run_logger", message_count=len(state.messages))

    def _plan_cancel(self, state: ConversationState) -> None:
        order_id = state.slots.get("order_id")
        reason = state.slots.get("reason")
        if not order_id:
            self._assistant(state, "Which order would you like to cancel?")
            return
        if not reason:
            self._assistant(
                state,
                "Please provide a cancellation reason: no longer needed "
                "or ordered by mistake.",
            )
            return
        self._set_pending(
            state,
            "cancel_pending_order",
            {"order_id": order_id, "reason": reason},
            f"Cancel order {order_id} because {reason}. Please confirm yes or no.",
        )

    def _plan_address_change(self, state: ConversationState) -> None:
        order_id = state.slots.get("order_id")
        address = state.slots.get("address")
        if not order_id:
            self._assistant(
                state,
                "Which order should have its shipping address changed?",
            )
            return
        if not address:
            self._assistant(
                state,
                "Please provide the new address as: address to line1, line2, "
                "city, state, country, zip.",
            )
            return
        args = {"order_id": order_id, **address}
        self._set_pending(
            state,
            "modify_pending_order_address",
            args,
            f"Modify the shipping address for order {order_id}. "
            "Please confirm yes or no.",
        )

    def _plan_return(self, state: ConversationState) -> None:
        required = ["order_id", "item_ids", "payment_method_id"]
        missing = [key for key in required if not state.slots.get(key)]
        if missing:
            self._assistant(
                state,
                "Please provide return details: order id, item id, "
                "and refund payment method.",
            )
            return
        self._set_pending(
            state,
            "return_delivered_order_items",
            {
                "order_id": state.slots["order_id"],
                "item_ids": state.slots["item_ids"],
                "payment_method_id": state.slots["payment_method_id"],
            },
            f"Request a return for order {state.slots['order_id']}. "
            "Please confirm yes or no.",
        )

    def _plan_exchange(self, state: ConversationState) -> None:
        required = ["order_id", "item_ids", "new_item_ids", "payment_method_id"]
        missing = [key for key in required if not state.slots.get(key)]
        if missing:
            self._assistant(
                state,
                "Please provide exchange details: order id, old item id, "
                "new item id, and payment method.",
            )
            return
        self._set_pending(
            state,
            "exchange_delivered_order_items",
            {
                "order_id": state.slots["order_id"],
                "item_ids": state.slots["item_ids"],
                "new_item_ids": state.slots["new_item_ids"],
                "payment_method_id": state.slots["payment_method_id"],
            },
            f"Request an exchange for order {state.slots['order_id']}. "
            "Please confirm yes or no.",
        )

    def _plan_modify_items(self, state: ConversationState) -> None:
        order_id = state.slots.get("order_id")
        item_ids = state.slots.get("item_ids")
        new_item_ids = state.slots.get("new_item_ids")
        if not order_id:
            self._assistant(state, "Which order would you like to modify items for?")
            return
        if not item_ids:
            self._assistant(state, "Which item would you like to replace?")
            return
        if not new_item_ids:
            self._assistant(state, "Please provide the new item id for the replacement.")
            return
        self._set_pending(
            state,
            "modify_pending_order_items",
            {
                "order_id": order_id,
                "item_ids": item_ids,
                "new_item_ids": new_item_ids,
            },
            f"Replace items in order {order_id}. Please confirm yes or no.",
        )

    def _plan_modify_payment(self, state: ConversationState) -> None:
        order_id = state.slots.get("order_id")
        payment_method_id = state.slots.get("payment_method_id")
        if not order_id:
            self._assistant(state, "Which order would you like to change payment for?")
            return
        if not payment_method_id:
            self._assistant(state, "Which payment method would you like to use?")
            return
        self._set_pending(
            state,
            "modify_pending_order_payment",
            {
                "order_id": order_id,
                "payment_method_id": payment_method_id,
            },
            f"Change payment for order {order_id}. Please confirm yes or no.",
        )

    def _plan_user_address(self, state: ConversationState) -> None:
        address = state.slots.get("address")
        if not address:
            self._assistant(
                state,
                "Please provide the new address as: address to line1, line2, "
                "city, state, country, zip.",
            )
            return
        user_id = state.authenticated_user_id
        if not user_id:
            self._assistant(state, "Please verify your identity first.")
            return
        args = {"user_id": user_id, **address}
        self._set_pending(
            state,
            "modify_user_address",
            args,
            "Modify your default address. Please confirm yes or no.",
        )

    def _respond_with_order_lookup(self, state: ConversationState) -> None:
        order_id = state.slots.get("order_id")
        if not order_id:
            self._assistant(state, "Which order would you like me to look up?")
            return
        order = state.loaded_context.orders.get(order_id) or get_order_from_db(
            self.retail_runtime.db, order_id
        )
        if not order:
            self._assistant(state, f"I could not find order {order_id}.")
            return
        self._assistant(
            state,
            f"Order {order_id} is currently {order.get('status')}.",
        )

    def _set_pending(
        self,
        state: ConversationState,
        action_name: str,
        arguments: Dict[str, Any],
        prompt: str,
    ) -> None:
        state.pending_action = PendingAction(
            action_name=action_name,
            arguments=arguments,
            user_facing_summary=prompt.replace(" Please confirm yes or no.", ""),
        )
        state.confirmation_status = "required"
        self._assistant(state, prompt)

    def _llm_json(
        self,
        state: ConversationState,
        node_name: str,
        system_prompt: str,
        payload: Dict[str, Any],
        schema: Dict[str, Any],
    ) -> Dict[str, Any]:
        if self.provider is None:
            return {}
        try:
            result = self.provider.json(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_json_prompt(node_name, payload),
                    },
                ],
                schema,
            )
        except Exception as exc:
            state.add_step(
                f"{node_name}_llm",
                status="error",
                error=str(exc),
            )
            return {}
        if not isinstance(result, dict):
            state.add_step(
                f"{node_name}_llm",
                status="error",
                error="provider returned non-object JSON",
            )
            return {}
        state.add_step(f"{node_name}_llm", status="ok", result=result)
        return result

    def _llm_chat(
        self, state: ConversationState, node_name: str, draft: str
    ) -> str:
        if self.provider is None:
            return ""
        try:
            response = self.provider.chat(
                [
                    {"role": "system", "content": RESPONSE_SYSTEM},
                    {"role": "user", "content": f"Draft response:\n{draft}"},
                ]
            )
        except Exception as exc:
            state.add_step(
                f"{node_name}_llm",
                status="error",
                error=str(exc),
            )
            return ""
        response = response.strip()
        if response:
            state.add_step(f"{node_name}_llm", status="ok")
        return response

    def _apply_llm_intent_slots(
        self, state: ConversationState, payload: Dict[str, Any]
    ) -> None:
        intent = str(payload.get("intent") or "").strip()
        if intent in SUPPORTED_INTENTS and (
            intent != "unknown" or state.current_intent == "unknown"
        ):
            state.current_intent = intent
        slots = payload.get("slots") or {}
        if not isinstance(slots, dict):
            return
        for key in (
            "order_id",
            "payment_method_id",
            "reason",
        ):
            value = self._clean_llm_scalar(slots.get(key))
            if value:
                state.slots[key] = value
        for key in ("item_ids", "new_item_ids"):
            values = self._clean_llm_list(slots.get(key))
            if values:
                state.slots[key] = values
        address = slots.get("address")
        if isinstance(address, dict):
            cleaned_address = {
                key: self._clean_llm_scalar(address.get(key)) or ""
                for key in ("address1", "address2", "city", "state", "country", "zip")
            }
            if cleaned_address["address1"] and cleaned_address["zip"]:
                state.slots["address"] = cleaned_address

    def _merge_slots(
        self,
        *,
        code_slots: Dict[str, Any],
        llm_slots: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Merge code and LLM slots. Code wins for ID formats; LLM for semantic."""
        if not llm_slots:
            return dict(code_slots)
        merged = dict(code_slots)
        for key, value in llm_slots.items():
            if key not in merged or not merged[key]:
                if value:
                    merged[key] = value
                continue
            if key == "reason":
                cleaned = self._clean_llm_scalar(value)
                if cleaned and cleaned.lower() in {
                    "no longer needed",
                    "ordered by mistake",
                }:
                    merged[key] = cleaned.lower()
            if key == "address" and isinstance(value, dict):
                cleaned_address = {
                    k: self._clean_llm_scalar(value.get(k)) or ""
                    for k in ("address1", "address2", "city", "state",
                              "country", "zip")
                }
                if cleaned_address.get("address1") and cleaned_address.get("zip"):
                    merged["address"] = cleaned_address
        return merged

    def _llm_policy_decision(
        self, state: ConversationState, content: str, fallback_decision: str
    ) -> Dict[str, Any]:
        payload = self._llm_json(
            state,
            "policy_reasoner",
            POLICY_SYSTEM,
            {
                "user_message": content,
                "policy_excerpt": self.retail_runtime.policy[:6000],
                "current_intent": state.current_intent,
                "slots": state.slots,
                "loaded_context": state.loaded_context.model_dump(),
                "authenticated_user_id": state.authenticated_user_id,
                "fallback_decision": fallback_decision,
            },
            {
                "type": "object",
                "properties": {
                    "decision": {"type": "string"},
                    "intent": {"type": "string"},
                    "missing_slots": {"type": "array"},
                    "user_confirmation_required": {"type": "boolean"},
                    "explanation_for_user": {"type": "string"},
                    "internal_reasoning_summary": {"type": "string"},
                },
            },
        )
        decision = payload.get("decision")
        if decision not in {"allow", "ask_clarification", "deny", "transfer"}:
            return {}
        if payload.get("intent") not in SUPPORTED_INTENTS:
            payload["intent"] = state.current_intent
        missing_slots = payload.get("missing_slots")
        if not isinstance(missing_slots, list):
            payload["missing_slots"] = []
        return payload

    def _apply_llm_action_plan(
        self, state: ConversationState, content: str
    ) -> bool:
        plan = self._llm_json(
            state,
            "action_planner",
            ACTION_PLANNER_SYSTEM,
            {
                "user_message": content,
                "policy_decision": (
                    state.policy_decision.model_dump()
                    if state.policy_decision
                    else None
                ),
                "current_intent": state.current_intent,
                "slots": state.slots,
                "loaded_context": state.loaded_context.model_dump(),
                "tool_catalog": self.gateway.registry.tool_catalog_for_llm(),
            },
            {
                "type": "object",
                "properties": {
                    "plan_type": {"type": "string"},
                    "action_name": {"type": "string"},
                    "arguments": {"type": "object"},
                    "response": {"type": "string"},
                },
            },
        )
        if not plan:
            return False
        plan_type = plan.get("plan_type") or plan.get("type")
        response = self._clean_llm_scalar(plan.get("response")) or ""
        if plan_type == "lookup_order":
            self._respond_with_order_lookup(state)
            return True
        if plan_type == "transfer":
            self._transfer_to_human(state, content)
            return True
        if plan_type in {"ask_clarification", "respond"} and response:
            self._assistant(state, response)
            return True
        if plan_type != "pending_write":
            return False
        action_name = self._clean_llm_scalar(plan.get("action_name")) or ""
        arguments = plan.get("arguments") or {}
        if action_name not in SUPPORTED_PENDING_ACTIONS:
            return False
        if not isinstance(arguments, dict):
            return False
        arguments = self._normalize_llm_action_arguments(action_name, arguments)
        if not self._pending_action_has_required_args(action_name, arguments):
            return False
        prompt = response or self._pending_prompt(action_name, arguments)
        if "confirm" not in prompt.lower():
            prompt = prompt.rstrip(".") + ". Please confirm yes or no."
        self._set_pending(state, action_name, arguments, prompt)
        return True

    def _pending_action_has_required_args(
        self, action_name: str, arguments: Dict[str, Any]
    ) -> bool:
        required = {
            "cancel_pending_order": ("order_id", "reason"),
            "modify_pending_order_address": (
                "order_id",
                "address1",
                "city",
                "state",
                "country",
                "zip",
            ),
            "modify_pending_order_items": (
                "order_id",
                "item_ids",
                "new_item_ids",
            ),
            "modify_pending_order_payment": (
                "order_id",
                "payment_method_id",
            ),
            "modify_user_address": (
                "user_id",
                "address1",
                "city",
                "state",
                "country",
                "zip",
            ),
            "return_delivered_order_items": (
                "order_id",
                "item_ids",
                "payment_method_id",
            ),
            "exchange_delivered_order_items": (
                "order_id",
                "item_ids",
                "new_item_ids",
                "payment_method_id",
            ),
        }[action_name]
        return all(arguments.get(key) for key in required)

    def _normalize_llm_action_arguments(
        self, action_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        normalized = dict(arguments)
        if action_name == "modify_pending_order_address":
            address = normalized.pop("address", None)
            if isinstance(address, dict):
                for key in ("address1", "address2", "city", "state", "country", "zip"):
                    if key not in normalized and address.get(key) is not None:
                        normalized[key] = address.get(key)
        for key in ("item_ids", "new_item_ids"):
            value = normalized.get(key)
            if isinstance(value, str):
                normalized[key] = [value]
        for key, value in list(normalized.items()):
            if isinstance(value, str):
                cleaned = self._clean_llm_scalar(value)
                if cleaned is None:
                    normalized.pop(key)
                else:
                    normalized[key] = cleaned
        return normalized

    def _pending_prompt(self, action_name: str, arguments: Dict[str, Any]) -> str:
        order_id = arguments.get("order_id")
        if action_name == "cancel_pending_order":
            return (
                f"Cancel order {order_id} because {arguments.get('reason')}. "
                "Please confirm yes or no."
            )
        if action_name == "modify_pending_order_address":
            return (
                f"Modify the shipping address for order {order_id}. "
                "Please confirm yes or no."
            )
        if action_name == "modify_pending_order_items":
            return (
                f"Replace items in order {order_id}. "
                "Please confirm yes or no."
            )
        if action_name == "modify_pending_order_payment":
            return (
                f"Change payment for order {order_id}. "
                "Please confirm yes or no."
            )
        if action_name == "modify_user_address":
            return "Modify your default address. Please confirm yes or no."
        if action_name == "return_delivered_order_items":
            return f"Request a return for order {order_id}. Please confirm yes or no."
        return f"Request an exchange for order {order_id}. Please confirm yes or no."

    def _infer_intent(self, lowered: str) -> str:
        # Policy questions are lookups, not operations
        if re.search(r'\b(return|exchange|cancel|refund)\s+policy\b', lowered):
            return "lookup"

        # Explicit human transfer request — multiple patterns
        # Pattern 1: verb + human/agent/representative
        if re.search(
            r'\b(?:talk|speak|connect|transfer|want|need|get|like|'
            r'speak)\s+(?:to|with|a|an)?\s*'
            r'(?:human|agent|representative|person)\b',
            lowered,
        ):
            return "transfer"
        # Pattern 2: standalone unambiguous transfer signals
        if re.search(
            r'\b(?:customer\s+service|support\s+agent|real\s+person'
            r'|human\s+agent|human\s+representative)\b',
            lowered,
        ):
            return "transfer"
        # Pattern 3: unsupported request types
        if "discount" in lowered:
            return "transfer"

        # Cancel — must mention order
        if re.search(r'\bcancel\b', lowered):
            if re.search(r'\border\b', lowered) or ORDER_RE.search(lowered):
                return "cancel_order"
            return "cancel_order"

        # Exchange — exclude "exchange rate" and "exchange policy"
        if re.search(r'\bexchange\b', lowered):
            if not re.search(r'\bexchange\s+(?:rate|policy)\b', lowered):
                if re.search(r'\bitems?\b', lowered) or ITEM_RE.search(lowered):
                    return "exchange_items"
                return "exchange_items"

        # Return — must mention item or order, not "return policy"
        if re.search(r'\breturn\b', lowered):
            if re.search(r'\breturn\s+policy\b', lowered):
                pass
            elif re.search(r'\bitems?\b', lowered) or ORDER_RE.search(lowered):
                return "return_items"

        # Payment modification
        if "payment" in lowered and re.search(r'\b(change|modify|update|switch)\b',
                                               lowered):
            return "modify_order_payment"

        # Item modification (pending order)
        if re.search(r'\b(items?|products?)\b', lowered) and re.search(
            r'\b(change|modify|replace|switch|swap)\b', lowered):
            return "modify_order_items"

        # User default address
        if re.search(r'\bmy\b.*\bdefault\b.*\baddress\b', lowered):
            return "modify_user_address"
        if "default address" in lowered:
            return "modify_user_address"

        # Order address modification
        if "address" in lowered and re.search(r'\b(change|modify|update)\b',
                                               lowered):
            if "my" in lowered and "default" in lowered:
                return "modify_user_address"
            return "modify_order_address"

        # Order mention → lookup
        if "order" in lowered or ORDER_RE.search(lowered):
            return "lookup"

        return "unknown"

    def _parse_address(self, content: str) -> Optional[Dict[str, str]]:
        marker = re.search(r"(?:default )?address to\s+(.+)$", content, re.IGNORECASE)
        if not marker:
            return None
        parts = [
            part.strip().rstrip(".")
            for part in marker.group(1).split(",")
        ]
        if len(parts) == 5:
            address1, city, state, country, zip_code = parts
            address2 = ""
        elif len(parts) >= 6:
            address1, address2, city, state, country, zip_code = parts[:6]
        else:
            return None
        return {
            "address1": address1,
            "address2": address2,
            "city": city,
            "state": state,
            "country": country,
            "zip": zip_code,
        }

    def _parse_item_replacement_pairs(self, lowered: str) -> list[tuple[str, str]]:
        pairs = re.findall(r"\b(\d{8,})\s+(?:to|for|instead)\s+(\d{8,})\b", lowered)
        if pairs:
            return pairs
        return re.findall(
            r"\bitem\s+(\d{8,}).*?\b(?:new item|instead)\s+(\d{8,})\b",
            lowered,
        )

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
        return bool(state.messages and state.messages[-1].role == "assistant")

    def _last_assistant_message(self, state: ConversationState) -> str:
        for message in reversed(state.messages):
            if message.role == "assistant":
                return message.content
        return ""

    def _clean_llm_scalar(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"null", "none", "n/a"}:
            return None
        return text

    def _clean_llm_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned = []
        for item in value:
            text = self._clean_llm_scalar(item)
            if text:
                cleaned.append(text)
        return cleaned
