from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from app.agent.confirmation import ConfirmationResolver
from app.agent.context_builder import ContextBuilder
from app.agent.llm_agent import AgentLoop
from app.agent.models import Message, PendingAction, SessionState
from app.agent.parsers import EMAIL_RE, NAME_ZIP_RE
from app.agent.prompts import prompt_metadata
from app.agent.providers import (
    DeterministicProvider,
    DisabledLLMProvider,
    LLMProvider,
    build_default_provider,
)
from app.config import AppConfig
from app.ops.tracing import TraceWriter, final_state_summary
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry
from app.tools.retail_adapter import RetailAdapter, RetailRuntime

GUARD_USER_MESSAGES: dict[str, str] = {
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
    return GUARD_USER_MESSAGES.get(
        str(error),
        "I could not complete that update. Please try again or contact support.",
    )


@dataclass
class AgentRunResult:
    run_id: str
    state: SessionState
    trace_artifact_path: Path
    turn_contexts: list = field(default_factory=list)

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
        self._resolver = ConfirmationResolver()

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

        policy_path = config.retail_policy_path
        policy_text = policy_path.read_text()[:500] if policy_path.exists() else ""
        self._context_builder = ContextBuilder(policy_text=policy_text)
        self._turn_contexts: list = []

    def run_script(
        self,
        *,
        messages: Iterable[Dict[str, str]],
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        max_turns: int = 20,
        user_simulator_callback: Optional[Callable[[str], Optional[str]]] = None,
    ) -> AgentRunResult:
        self._turn_contexts = []
        run_id = session_id or f"agent-{uuid.uuid4().hex[:12]}"
        session = SessionState(session_id=run_id, task_id=task_id)
        initial_db_hash = self.retail_runtime.db_hash()
        turn = 0
        message_list = list(messages)
        message_index = 0
        while message_index < len(message_list) and turn < max_turns:
            message = message_list[message_index]
            message_index += 1
            turn += 1
            if message.get("role") != "user":
                continue
            assistant_msg = self.handle_user_message(session, message.get("content", ""))
            if user_simulator_callback and assistant_msg and not session.termination_reason:
                next_user_msg = user_simulator_callback(assistant_msg)
                if next_user_msg:
                    message_list.append({"role": "user", "content": next_user_msg})
        if not session.termination_reason:
            session.termination_reason = "script_completed"
        trace_path = TraceWriter(self.config.run_artifact_dir).write(
            run_id=run_id,
            state=session,
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
                "llm_responses": [
                    resp
                    for turn_ctx in self._turn_contexts
                    for resp in turn_ctx.llm_responses
                ],
            },
        )
        return AgentRunResult(
            run_id=run_id,
            state=session,
            trace_artifact_path=trace_path,
            turn_contexts=list(self._turn_contexts),
        )

    def handle_user_message(self, session: SessionState, content: str) -> str:
        t0 = time.perf_counter()
        session.messages.append(Message(role="user", content=content))
        session.add_step("receive_message", content=content)

        # 1. Pre-flight: pending confirmation short-circuit
        if session.pending_action:
            result = self._preflight_confirmation(session, content)
            if result is not None:
                return result

        # 2. Pre-flight: identity shortcut
        if not session.authenticated_user_id:
            self._preflight_identity(session, content)

        # 3. LLM agent loop
        # Phase 7: fall back to deterministic provider when no LLM configured
        provider = self.provider
        if provider is None or isinstance(provider, DeterministicProvider):
            # Deterministic mode: handle write intents directly before AgentLoop.
            # DeterministicProvider.chat_with_tools() never returns tool_calls,
            # so the confirmation flow (pending_action → guard → confirm) never
            # activates through AgentLoop alone.  This fast path bridges the gap.
            write_result = self._deterministic_write_intent(session, content)
            if write_result is not None:
                session.step_durations["handle_user_message"] = round(
                    (time.perf_counter() - t0) * 1000, 1
                )
                return write_result

            provider = DeterministicProvider()
            session.add_step("deterministic_fallback")

        loop = AgentLoop(
            provider=provider,
            gateway=self.gateway,
            registry=self.registry,
            context_builder=self._context_builder,
        )
        result = loop.run_turn(session, content)

        # Phase 5: capture TurnContext for eval metrics
        self._turn_contexts.append(result.turn)

        # 4. Post-process
        session.messages.append(Message(role="assistant", content=result.assistant_message))

        # Phase 4 compat: populate deprecated fields for eval runner
        if result.pending_action_set:
            session.confirmation_status = "required"
        elif not session.pending_action:
            session.confirmation_status = "not_required"

        session.step_durations["handle_user_message"] = round(
            (time.perf_counter() - t0) * 1000, 1
        )
        return result.assistant_message

    # ── Pre-flight helpers ──

    def _preflight_confirmation(
        self, session: SessionState, content: str
    ) -> Optional[str]:
        resolution = self._resolver.resolve(content)
        if resolution == "unknown":
            return None

        session.confirmation_status = resolution
        session.add_step("preflight_confirmation", resolution=resolution)

        if resolution == "confirmed":
            action = session.pending_action
            record = self.gateway.execute(
                state=session,
                tool_name=action.action_name,
                arguments=action.arguments,
                confirmed=True,
            )
            session.pending_action = None
            if record.status == "success":
                msg = "Done. I have completed the requested update."
            else:
                msg = _map_guard_error_to_user_message(str(record.error))
            session.messages.append(Message(role="assistant", content=msg))
            return msg
        elif resolution == "denied":
            session.pending_action = None
            msg = "No changes were made."
            session.messages.append(Message(role="assistant", content=msg))
            return msg
        elif resolution == "changed":
            session.pending_action = None
            msg = "I discarded the previous request. Please provide updated details."
            session.messages.append(Message(role="assistant", content=msg))
            return msg

        return None

    def _preflight_identity(self, session: SessionState, content: str) -> None:
        # Email shortcut
        email_match = EMAIL_RE.search(content)
        if email_match:
            email = email_match.group(0)
            record = self.gateway.execute(
                state=session,
                tool_name="find_user_id_by_email",
                arguments={"email": email},
            )
            if record.status == "success":
                user_id = str(record.observation)
                session.authenticated_user_id = user_id
                session.auth_method = "email"
                session.active_user_identity = {"email": email, "user_id": user_id}
                user_record = self.gateway.execute(
                    state=session,
                    tool_name="get_user_details",
                    arguments={"user_id": user_id},
                )
                if user_record.status == "success":
                    session.loaded_context.users[user_id] = user_record.observation
                session.add_step("preflight_identity", method="email", user_id=user_id)
            return

        # Name+zip shortcut
        name_zip_match = NAME_ZIP_RE.search(content)
        if name_zip_match:
            first_name, last_name, zip_code = name_zip_match.groups()
            record = self.gateway.execute(
                state=session,
                tool_name="find_user_id_by_name_zip",
                arguments={
                    "first_name": first_name,
                    "last_name": last_name,
                    "zip": zip_code,
                },
            )
            if record.status == "success":
                user_id = str(record.observation)
                session.authenticated_user_id = user_id
                session.auth_method = "name_zip"
                session.active_user_identity = {
                    "first_name": first_name,
                    "last_name": last_name,
                    "zip": zip_code,
                    "user_id": user_id,
                }
                user_record = self.gateway.execute(
                    state=session,
                    tool_name="get_user_details",
                    arguments={"user_id": user_id},
                )
                if user_record.status == "success":
                    session.loaded_context.users[user_id] = user_record.observation
                session.add_step(
                    "preflight_identity", method="name_zip", user_id=user_id
                )

    # ── Deterministic write intent: bridges the gap when no LLM is available ──

    _ORDER_RE = re.compile(r"#W\d+")
    _ITEM_RE = re.compile(r"\b\d{10}\b")
    _PAYMENT_RE = re.compile(
        r"(credit_card_\d+|gift_card_\d+)", re.IGNORECASE
    )
    _REASON_RE = re.compile(
        r"(no longer needed|ordered by mistake)", re.IGNORECASE
    )
    _ADDRESS_RE = re.compile(
        r"address\s+(?:to|for)\s+(.+?)(?:\s*$|\.\s|,\s*(?:using|with|$))",
        re.IGNORECASE,
    )

    def _deterministic_write_intent(
        self, session: SessionState, content: str
    ) -> Optional[str]:
        """Detect write intents from user message and execute via gateway.

        Returns an assistant message string if a write intent was handled,
        or None to fall through to AgentLoop for read-only operations.
        """
        text = content.lower()

        # ── Unsupported requests → transfer ──
        if any(word in text for word in ("discount", "coupon", "compensat", "refund")):
            return self._det_call(
                session, "transfer_to_human_agents",
                {"summary": f"User requested unsupported operation: {content[:100]}"},
                read_only=True,
            )

        # ── Transfer ──
        if "human agent" in text:
            return self._det_call(
                session, "transfer_to_human_agents",
                {"summary": "User requested human agent."},
                read_only=True,
            )

        # ── Order lookup ──
        if "status" in text or "look" in text or "what is" in text:
            match = self._ORDER_RE.search(content)
            if match:
                return self._det_call(
                    session, "get_order_details",
                    {"order_id": match.group(0)},
                    read_only=True,
                )

        # ── Cancel ──
        if "cancel" in text or "void" in text:
            match = self._ORDER_RE.search(content)
            reason_match = self._REASON_RE.search(content)
            if match:
                return self._det_call(
                    session, "cancel_pending_order",
                    {
                        "order_id": match.group(0),
                        "reason": reason_match.group(1) if reason_match else "no longer needed",
                    },
                )

        # ── Modify user address (no order_id) ──
        if ("change" in text or "modify" in text) and "address" in text and "order" not in text:
            user_id = session.authenticated_user_id
            if not user_id:
                return None
            addr_parts = self._parse_address(content)
            if addr_parts:
                return self._det_call(
                    session, "modify_user_address",
                    {"user_id": user_id, **addr_parts},
                )

        order_match = self._ORDER_RE.search(content)
        order_id = order_match.group(0) if order_match else None

        if order_id is None:
            return None

        # ── Modify order address ──
        if "address" in text and ("change" in text or "modify" in text):
            addr_parts = self._parse_address(content)
            if addr_parts:
                return self._det_call(
                    session, "modify_pending_order_address",
                    {"order_id": order_id, **addr_parts},
                )

        item_ids = self._ITEM_RE.findall(content)
        payment_match = self._PAYMENT_RE.search(content)
        payment_id = payment_match.group(0) if payment_match else None

        # ── Return ──
        if "return" in text and item_ids:
            return self._det_call(
                session, "return_delivered_order_items",
                {
                    "order_id": order_id,
                    "item_ids": item_ids,
                    "payment_method_id": payment_id or "",
                },
            )

        # ── Exchange ──
        if "exchange" in text and len(item_ids) >= 2:
            # Handle multi-item exchange: "items X to Y, A to B, and C to D"
            # Even-indexed items are old, odd-indexed are new.
            old_items = item_ids[0::2]
            new_items = item_ids[1::2]
            return self._det_call(
                session, "exchange_delivered_order_items",
                {
                    "order_id": order_id,
                    "item_ids": old_items,
                    "new_item_ids": new_items,
                    "payment_method_id": payment_id or "",
                },
            )

        # ── Modify order items ──
        if ("change" in text or "modify" in text) and "item" in text and len(item_ids) >= 2:
            return self._det_call(
                session, "modify_pending_order_items",
                {
                    "order_id": order_id,
                    "item_ids": [item_ids[0]],
                    "new_item_ids": [item_ids[1]],
                },
            )

        # ── Modify order payment ──
        if ("change" in text or "modify" in text) and "payment" in text and payment_id:
            return self._det_call(
                session, "modify_pending_order_payment",
                {
                    "order_id": order_id,
                    "payment_method_id": payment_id,
                },
            )

        # ── Modify shipping method ──
        if ("shipping" in text or "ship" in text) and ("change" in text or "modify" in text or "upgrade" in text):
            method = "standard"
            if "overnight" in text:
                method = "overnight"
            elif "express" in text:
                method = "express"
            return self._det_call(
                session, "modify_pending_order_shipping_method",
                {
                    "order_id": order_id,
                    "shipping_method": method,
                    "payment_method_id": payment_id or "",
                },
            )

        return None

    def _det_call(
        self,
        session: SessionState,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        read_only: bool = False,
    ) -> Optional[str]:
        """Execute a deterministic tool call and handle guard/confirmation flow."""
        # Auto-load order context before write
        order_id = arguments.get("order_id")
        if order_id and tool_name != "transfer_to_human_agents":
            clean_id = str(order_id).lstrip("#")
            if clean_id not in session.loaded_context.orders:
                load_record = self.gateway.execute(
                    state=session,
                    tool_name="get_order_details",
                    arguments={"order_id": f"#{clean_id}"},
                )
                if load_record.status == "success" and isinstance(load_record.observation, dict):
                    session.loaded_context.orders[clean_id] = load_record.observation
                    session.loaded_context.orders[f"#{clean_id}"] = load_record.observation

        # For write tools: check guard first, create pending_action on confirmation
        # block, or call gateway for other blocks (to create ToolCallRecord).
        if not read_only and tool_name != "transfer_to_human_agents":
            from app.agent.guard import WriteActionGuard
            from app.agent.models import ToolCall as GuardToolCall
            guard = WriteActionGuard()
            guard_result = guard.check(
                state=session,
                db=self.retail_runtime.db,
                action=GuardToolCall(tool_name=tool_name, arguments=arguments),
                confirmed=False,
            )
            if not guard_result.allowed:
                if guard_result.block_reason == "explicit_confirmation_required":
                    session.pending_action = PendingAction(
                        action_name=tool_name,
                        arguments=arguments,
                        user_facing_summary=f"{tool_name}: {', '.join(f'{k}={v}' for k, v in arguments.items())}",
                    )
                    session.confirmation_status = "required"
                    session.add_step(
                        "deterministic_write_intent",
                        tool_name=tool_name,
                        status="pending_confirmation",
                    )
                    msg = (
                        f"I'd like to {tool_name.replace('_', ' ')}. "
                        "Can you confirm? Reply yes or no."
                    )
                    session.messages.append(Message(role="assistant", content=msg))
                    return msg
                else:
                    # For policy/ownership blocks, call gateway so a blocked
                    # ToolCallRecord is created (needed by eval assertions).
                    record = self.gateway.execute(
                        state=session,
                        tool_name=tool_name,
                        arguments=arguments,
                        confirmed=False,
                    )
                    msg = _map_guard_error_to_user_message(str(record.error))
                    session.messages.append(Message(role="assistant", content=msg))
                    return msg

        # For read-only tools or when guard passes: execute normally
        record = self.gateway.execute(
            state=session,
            tool_name=tool_name,
            arguments=arguments,
            confirmed=False,
        )

        if record.status == "blocked":
            msg = _map_guard_error_to_user_message(str(record.error))
            session.messages.append(Message(role="assistant", content=msg))
            return msg

        if record.status == "success":
            if tool_name == "transfer_to_human_agents":
                msg = "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
                session.messages.append(Message(role="assistant", content=msg))
                return msg
            if read_only:
                obs = record.observation
                if isinstance(obs, dict) and "status" in obs:
                    # Format order lookup into a readable message
                    order_id = arguments.get("order_id", obs.get("order_id", ""))
                    status = obs.get("status", "unknown")
                    msg = f"Order {order_id} is {status}."
                else:
                    msg = str(obs)[:300] if obs else "Done."
                session.messages.append(Message(role="assistant", content=msg))
                return msg
            msg = "Done. I have completed the requested update."
            session.messages.append(Message(role="assistant", content=msg))
            return msg

        # Error
        msg = _map_guard_error_to_user_message(str(record.error))
        session.messages.append(Message(role="assistant", content=msg))
        return msg

    _ADDR_CITY_STATE_RE = re.compile(
        r"(\d+[^,]*),"
        r"\s*(?:((?:apt|unit|suite)\s*\.?\s*\d+[^,]*),\s*)?"
        r"([a-zA-Z\s]+?),"
        r"\s*([A-Z]{2}),?"
        r"\s*(?:USA|US)?,?"
        r"\s*(\d{5}(?:-\d{4})?)",
        re.IGNORECASE,
    )

    def _parse_address(self, content: str) -> Optional[Dict[str, str]]:
        """Extract address fields from user message."""
        # Search from the last occurrence of "address" to avoid matching
        # digits in email addresses or other unrelated content.
        addr_keyword = content.lower().rfind("address")
        search_start = max(addr_keyword, 0)
        match = self._ADDR_CITY_STATE_RE.search(content, search_start)
        if match:
            return {
                "address1": match.group(1).strip(),
                "address2": match.group(2).strip() if match.group(2) else "",
                "city": match.group(3).strip(),
                "state": match.group(4).strip(),
                "country": "USA",
                "zip": match.group(5).strip(),
            }
        return None
