from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from app.agent.confirmation import ConfirmationResolver
from app.agent.context_builder import ContextBuilder
from app.agent.extraction import extract_email, extract_name_zip
from app.agent.llm_agent import AgentLoop
from app.agent.models import Message, SessionState
from app.agent.prompts import prompt_metadata
from app.agent.providers import (
    LLMProvider,
    build_default_provider,
)
from app.agent.security import is_explicit_human_transfer
from app.config import AppConfig
from app.ops.tracing import TraceWriter, final_state_summary
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry
from app.tools.retail_adapter import RetailAdapter, RetailRuntime

# _HUMAN_TRANSFER_RE 已迁至 app.agent.security（与 llm_agent 的重复正则合并为一份）。

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


def _pending_action_prompt_injection_pattern_ids(
    arguments: Dict[str, Any],
) -> list[str]:
    value = arguments.get("_prompt_injection_pattern_ids")
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if str(item)})


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
        self.registry = ToolRegistry(
            self.retail_runtime.tools,
            enable_think_tool=config.enable_think_tool,
        )
        self.gateway = ToolGateway(registry=self.registry, runtime=self.retail_runtime)
        self._resolver = ConfirmationResolver()

        self.provider = provider or build_default_provider(
                api_key=config.deepseek_api_key,
                base_url=config.deepseek_base_url,
                model=config.default_agent_model,
                timeout=config.agent_llm_timeout_seconds,
                max_retries=config.agent_llm_max_retries,
                require_llm=require_llm,
                provider_type=config.llm_provider_type,
                ollama_model=config.ollama_model,
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
                "runtime_backend": "llm_tool_calling",
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
                "prompt_injection_signal_count": sum(
                    turn_ctx.prompt_injection_signal_count
                    for turn_ctx in self._turn_contexts
                ),
                "prompt_injection_signals": [
                    signal
                    for turn_ctx in self._turn_contexts
                    for signal in turn_ctx.prompt_injection_signals
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
        session.current_action_candidate = None
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

        # 2b. Human transfer shortcut. If the user explicitly asks for a human,
        # transfer before the LLM can choose a same-turn write request instead.
        transfer_msg = self._preflight_human_transfer(session, content)
        if transfer_msg is not None:
            session.messages.append(Message(role="assistant", content=transfer_msg))
            session.step_durations["handle_user_message"] = round(
                (time.perf_counter() - t0) * 1000, 1
            )
            return transfer_msg

        # 3. LLM agent loop
        provider = self.provider
        if provider is None:
            msg = (
                "I'm unable to process this request without an LLM provider. "
                "Let me transfer you to a human agent."
            )
            session.add_step("provider_unavailable")
            session.messages.append(Message(role="assistant", content=msg))
            session.step_durations["handle_user_message"] = round(
                (time.perf_counter() - t0) * 1000, 1
            )
            return msg

        loop = AgentLoop(
            provider=provider,
            gateway=self.gateway,
            registry=self.registry,
            context_builder=self._context_builder,
            injection_llm_secondary=self.config.injection_llm_secondary,
            injection_llm_timeout=self.config.injection_llm_timeout,
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

    def _preflight_human_transfer(
        self,
        session: SessionState,
        content: str,
    ) -> Optional[str]:
        if not is_explicit_human_transfer(content):
            return None
        record = self.gateway.execute(
            state=session,
            tool_name="transfer_to_human_agents",
            arguments={"summary": content[:500]},
        )
        session.add_step(
            "preflight_human_transfer",
            status=record.status,
            tool_name="transfer_to_human_agents",
        )
        if record.status == "success":
            return "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
        return "I'm unable to transfer you right now. Please try again or contact support."

    def _preflight_confirmation(
        self, session: SessionState, content: str
    ) -> Optional[str]:
        from app.agent.confirmation import has_competing_signal

        resolution = self._resolver.resolve(content)

        # 干净确认 → 秒级短路执行（现有路径不变）
        if resolution == "confirmed" and not has_competing_signal(content):
            session.confirmation_status = "confirmed"
            session.add_step("preflight_confirmation", resolution="confirmed")
            action = session.pending_action
            injection_pattern_ids = _pending_action_prompt_injection_pattern_ids(
                action.arguments
            )
            if injection_pattern_ids:
                safe_arguments = {
                    key: value
                    for key, value in action.arguments.items()
                    if key != "_prompt_injection_pattern_ids"
                }
                AgentLoop._record_prompt_injection_write_block(
                    session=session,
                    tool_name=action.action_name,
                    arguments=safe_arguments,
                    pattern_ids=injection_pattern_ids,
                )
                session.pending_action = None
                msg = (
                    "I can't continue with that account or order change because "
                    "the request included instruction-bypassing language. Please "
                    "restate the request without those instructions, or I can help "
                    "check the order or transfer you to a human agent."
                )
                session.messages.append(Message(role="assistant", content=msg))
                return msg
            record = self.gateway.execute(
                state=session,
                tool_name=action.action_name,
                arguments={
                    key: value
                    for key, value in action.arguments.items()
                    if key != "_prompt_injection_pattern_ids"
                },
                confirmed=True,
            )
            session.pending_action = None
            if record.status == "success":
                continued = self._continue_after_confirmed_action(session)
                if continued is not None:
                    return continued
                msg = "Done. I have completed the requested update."
            else:
                msg = _map_guard_error_to_user_message(str(record.error))
            session.messages.append(Message(role="assistant", content=msg))
            return msg

        # confirmed + competing → 放行 LLM，pending 保持（NEW）
        if resolution == "confirmed":
            session.add_step(
                "preflight_confirmation_fallback",
                resolution="confirmed_competing",
            )
            return None

        # denied → 丢弃 pending（现有路径不变）
        if resolution == "denied":
            session.confirmation_status = "denied"
            session.pending_action = None
            session.add_step("preflight_confirmation", resolution="denied")
            if has_competing_signal(content):
                # denied + 提问/穿插 → 丢弃后放行 LLM 答问题（NEW）
                return None
            msg = "No changes were made."
            session.messages.append(Message(role="assistant", content=msg))
            return msg

        # changed → 独立分支，逐字节不动（保护 generalized_mvp changed case 不回归）
        if resolution == "changed":
            session.confirmation_status = "changed"
            session.pending_action = None
            session.add_step("preflight_confirmation", resolution="changed")
            msg = "I discarded the previous request. Please provide updated details."
            session.messages.append(Message(role="assistant", content=msg))
            return msg

        # unknown → 放行 LLM（现有路径不变）
        return None

    def _continue_after_confirmed_action(self, session: SessionState) -> Optional[str]:
        provider = self.provider
        if provider is None:
            return None

        completed_action = session.tool_results[-1] if session.tool_results else None
        loop = AgentLoop(
            provider=provider,
            gateway=self.gateway,
            registry=self.registry,
            context_builder=self._context_builder,
            injection_llm_secondary=self.config.injection_llm_secondary,
            injection_llm_timeout=self.config.injection_llm_timeout,
        )
        result = loop.run_turn(
            session,
            self._confirmed_action_continuation_prompt(session),
        )
        self._turn_contexts.append(result.turn)
        repeated_pending = self._is_repeated_confirmed_action(
            session=session,
            completed_action=completed_action,
        )
        if repeated_pending:
            session.pending_action = None
            session.confirmation_status = "confirmed"
            return "Done. I have completed the requested update."
        session.messages.append(Message(role="assistant", content=result.assistant_message))
        if result.pending_action_set:
            session.confirmation_status = "required"
        elif not session.pending_action:
            session.confirmation_status = "confirmed"
        return result.assistant_message

    def _is_repeated_confirmed_action(
        self,
        *,
        session: SessionState,
        completed_action: ToolCallRecord | None,
    ) -> bool:
        pending = session.pending_action
        if completed_action is None or pending is None:
            return False
        if completed_action.status != "success":
            return False
        if pending.action_name != completed_action.tool_name:
            return False
        return dict(pending.arguments) == dict(completed_action.arguments)

    def _confirmed_action_continuation_prompt(self, session: SessionState) -> str:
        """Build a continuation prompt that prevents redoing the completed action."""
        original_request = self._original_user_request_context(session)
        completed_action = session.tool_results[-1] if session.tool_results else None
        completed_desc = ""
        if completed_action and completed_action.status == "success":
            tool_name = completed_action.tool_name.replace("_", " ")
            order_id = completed_action.arguments.get("order_id", "")
            completed_desc = (
                f"The just-completed action was: {tool_name}"
                + (f" for {order_id}" if order_id else "")
                + ". "
            )
        if original_request:
            return (
                f"The user confirmed and {completed_action.tool_name if completed_action else 'the pending action'} "
                "has been successfully executed. "
                + completed_desc
                + "Do NOT repeat or re-execute this already-completed action. "
                "Check if any independent remaining parts of the original request "
                "still need to be handled. "
                f"Original request:\n\n{original_request}\n\n"
                "If all parts are done, provide a concise final summary of what was completed."
            )
        return (
            f"The user confirmed and {completed_action.tool_name if completed_action else 'the pending action'} "
            "has been successfully executed. "
            + completed_desc
            + "Do NOT repeat or re-execute this already-completed action. "
            "If nothing else remains from the user's original request, "
            "provide a concise final summary of what was completed."
        )

    def _original_user_request_context(self, session: SessionState) -> str:
        candidates: list[str] = []
        for message in session.messages:
            if message.role != "user":
                continue
            content = message.content.strip()
            if not content:
                continue
            if len(content) < 40 and self._resolver.resolve(content) != "unknown":
                continue
            candidates.append(content)
        if not candidates:
            return ""
        return max(candidates, key=len)

    def _preflight_identity(self, session: SessionState, content: str) -> None:
        # Email shortcut
        email = extract_email(content)
        if email:
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
        name_zip = extract_name_zip(content)
        if name_zip:
            first_name, last_name, zip_code = name_zip
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
