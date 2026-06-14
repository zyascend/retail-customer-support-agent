from __future__ import annotations

import re
from typing import Any, Callable, Optional

from app.agent.guard import WriteActionGuard
from app.agent.models import Message, PendingAction, SessionState, ToolCall
from app.tools.gateway import ToolGateway
from app.tools.retail_adapter import RetailRuntime


class OfflineDemoHarness:
    """Demo-only rule parser used when offline_demo=True.

    This harness keeps scripted demos and CI smoke tests useful without making
    rule parsing look like a production fallback path in AgentRuntime.
    """

    _ORDER_RE = re.compile(r"#W\d+")
    _ITEM_RE = re.compile(r"\b\d{10}\b")
    _PAYMENT_RE = re.compile(r"(credit_card_\d+|gift_card_\d+)", re.IGNORECASE)
    _REASON_RE = re.compile(
        r"(no longer needed|ordered by mistake)", re.IGNORECASE
    )
    _ADDR_CITY_STATE_RE = re.compile(
        r"(\d+[^,]*),"
        r"\s*(?:((?:apt|unit|suite)\s*\.?\s*\d+[^,]*),\s*)?"
        r"([a-zA-Z\s]+?),"
        r"\s*([A-Z]{2}),?"
        r"\s*(?:USA|US)?,?"
        r"\s*(\d{5}(?:-\d{4})?)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        gateway: ToolGateway,
        retail_runtime: RetailRuntime,
        guard_error_to_user_message: Callable[[str], str],
    ) -> None:
        self.gateway = gateway
        self.retail_runtime = retail_runtime
        self._guard_error_to_user_message = guard_error_to_user_message

    def handle(self, session: SessionState, content: str) -> Optional[str]:
        """Handle a demo-mode intent, or return None for AgentLoop fallback."""
        text = content.lower()

        if any(word in text for word in ("discount", "coupon", "compensat", "refund")):
            return self._det_call(
                session,
                "transfer_to_human_agents",
                {"summary": f"User requested unsupported operation: {content[:100]}"},
                read_only=True,
            )

        if "human agent" in text:
            return self._det_call(
                session,
                "transfer_to_human_agents",
                {"summary": "User requested human agent."},
                read_only=True,
            )

        if "status" in text or "look" in text or "what is" in text:
            match = self._ORDER_RE.search(content)
            if match:
                return self._det_call(
                    session,
                    "get_order_details",
                    {"order_id": match.group(0)},
                    read_only=True,
                )

        if "cancel" in text or "void" in text:
            match = self._ORDER_RE.search(content)
            reason_match = self._REASON_RE.search(content)
            if match:
                return self._det_call(
                    session,
                    "cancel_pending_order",
                    {
                        "order_id": match.group(0),
                        "reason": (
                            reason_match.group(1)
                            if reason_match
                            else "no longer needed"
                        ),
                    },
                )

        if (
            ("change" in text or "modify" in text)
            and "address" in text
            and "order" not in text
        ):
            user_id = session.authenticated_user_id
            if not user_id:
                return None
            addr_parts = self._parse_address(content)
            if addr_parts:
                return self._det_call(
                    session,
                    "modify_user_address",
                    {"user_id": user_id, **addr_parts},
                )

        order_match = self._ORDER_RE.search(content)
        order_id = order_match.group(0) if order_match else None

        if order_id is None:
            return None

        if "address" in text and ("change" in text or "modify" in text):
            addr_parts = self._parse_address(content)
            if addr_parts:
                return self._det_call(
                    session,
                    "modify_pending_order_address",
                    {"order_id": order_id, **addr_parts},
                )

        item_ids = self._ITEM_RE.findall(content)
        payment_match = self._PAYMENT_RE.search(content)
        payment_id = payment_match.group(0) if payment_match else None

        if "return" in text and item_ids:
            return self._det_call(
                session,
                "return_delivered_order_items",
                {
                    "order_id": order_id,
                    "item_ids": item_ids,
                    "payment_method_id": payment_id or "",
                },
            )

        if "exchange" in text and len(item_ids) >= 2:
            return self._det_call(
                session,
                "exchange_delivered_order_items",
                {
                    "order_id": order_id,
                    "item_ids": item_ids[0::2],
                    "new_item_ids": item_ids[1::2],
                    "payment_method_id": payment_id or "",
                },
            )

        if (
            ("change" in text or "modify" in text)
            and "item" in text
            and len(item_ids) >= 2
        ):
            return self._det_call(
                session,
                "modify_pending_order_items",
                {
                    "order_id": order_id,
                    "item_ids": [item_ids[0]],
                    "new_item_ids": [item_ids[1]],
                },
            )

        if ("change" in text or "modify" in text) and "payment" in text and payment_id:
            return self._det_call(
                session,
                "modify_pending_order_payment",
                {
                    "order_id": order_id,
                    "payment_method_id": payment_id,
                },
            )

        if (
            ("shipping" in text or "ship" in text)
            and ("change" in text or "modify" in text or "upgrade" in text)
        ):
            method = "standard"
            if "overnight" in text:
                method = "overnight"
            elif "express" in text:
                method = "express"
            return self._det_call(
                session,
                "modify_pending_order_shipping_method",
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
        arguments: dict[str, Any],
        *,
        read_only: bool = False,
    ) -> Optional[str]:
        order_id = arguments.get("order_id")
        if order_id and tool_name != "transfer_to_human_agents":
            clean_id = str(order_id).lstrip("#")
            if clean_id not in session.loaded_context.orders:
                load_record = self.gateway.execute(
                    state=session,
                    tool_name="get_order_details",
                    arguments={"order_id": f"#{clean_id}"},
                )
                if load_record.status == "success" and isinstance(
                    load_record.observation, dict
                ):
                    session.loaded_context.orders[clean_id] = load_record.observation
                    session.loaded_context.orders[f"#{clean_id}"] = (
                        load_record.observation
                    )

        if not read_only and tool_name != "transfer_to_human_agents":
            guard_result = WriteActionGuard().check(
                state=session,
                db=self.retail_runtime.db,
                action=ToolCall(tool_name=tool_name, arguments=arguments),
                confirmed=False,
            )
            if not guard_result.allowed:
                if guard_result.block_reason == "explicit_confirmation_required":
                    session.pending_action = PendingAction(
                        action_name=tool_name,
                        arguments=arguments,
                        user_facing_summary=(
                            f"{tool_name}: "
                            + ", ".join(f"{k}={v}" for k, v in arguments.items())
                        ),
                    )
                    session.confirmation_status = "required"
                    session.add_step(
                        "offline_demo_intent",
                        tool_name=tool_name,
                        status="pending_confirmation",
                    )
                    msg = (
                        f"I'd like to {tool_name.replace('_', ' ')}. "
                        "Can you confirm? Reply yes or no."
                    )
                    session.messages.append(Message(role="assistant", content=msg))
                    return msg

                record = self.gateway.execute(
                    state=session,
                    tool_name=tool_name,
                    arguments=arguments,
                    confirmed=False,
                )
                msg = self._guard_error_to_user_message(str(record.error))
                session.messages.append(Message(role="assistant", content=msg))
                return msg

        record = self.gateway.execute(
            state=session,
            tool_name=tool_name,
            arguments=arguments,
            confirmed=False,
        )

        if record.status == "blocked":
            msg = self._guard_error_to_user_message(str(record.error))
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
                    returned_order_id = arguments.get("order_id", obs.get("order_id", ""))
                    msg = f"Order {returned_order_id} is {obs.get('status', 'unknown')}."
                else:
                    msg = str(obs)[:300] if obs else "Done."
                session.messages.append(Message(role="assistant", content=msg))
                return msg
            msg = "Done. I have completed the requested update."
            session.messages.append(Message(role="assistant", content=msg))
            return msg

        msg = self._guard_error_to_user_message(str(record.error))
        session.messages.append(Message(role="assistant", content=msg))
        return msg

    def _parse_address(self, content: str) -> Optional[dict[str, str]]:
        addr_keyword = content.lower().rfind("address")
        search_start = max(addr_keyword, 0)
        match = self._ADDR_CITY_STATE_RE.search(content, search_start)
        if not match:
            return None
        return {
            "address1": match.group(1).strip(),
            "address2": match.group(2).strip() if match.group(2) else "",
            "city": match.group(3).strip(),
            "state": match.group(4).strip(),
            "country": "USA",
            "zip": match.group(5).strip(),
        }
