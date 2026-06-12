from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

from app.agent.models import ToolKind


@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: ToolKind
    func: Callable[..., Any]


class ToolRegistry:
    def __init__(self, toolkit: Any) -> None:
        self.toolkit = toolkit
        self._tools = self._discover(toolkit)

    @property
    def tools(self) -> Dict[str, ToolSpec]:
        return self._tools.copy()

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")
        return self._tools[name]

    def kind(self, name: str) -> ToolKind:
        return self.get(name).kind

    def _discover(self, toolkit: Any) -> Dict[str, ToolSpec]:
        raw_tools = getattr(toolkit, "tools", None)
        if raw_tools is None:
            raw_tools = {
                name: getattr(toolkit, name)
                for name in dir(toolkit)
                if not name.startswith("_") and callable(getattr(toolkit, name))
            }
        specs: Dict[str, ToolSpec] = {}
        for name, func in raw_tools.items():
            kind = self._tool_kind(toolkit, name)
            specs[name] = ToolSpec(name=name, kind=kind, func=func)
        return specs

    def _tool_kind(self, toolkit: Any, name: str) -> ToolKind:
        if hasattr(toolkit, "tool_type"):
            raw_kind = toolkit.tool_type(name)
            value = getattr(raw_kind, "value", raw_kind)
            if value in {"read", "write", "generic", "think"}:
                return value
        if name.startswith(("get_", "find_", "list_")):
            return "read"
        if name == "transfer_to_human_agents" or name == "calculate":
            return "generic"
        return "write"

    def tool_catalog_for_llm(self) -> str:
        """Generate LLM-visible tool descriptions from the registry.
        Single source of truth — no manual duplication needed.
        """
        entries: list[str] = []
        for name in sorted(self._tools):
            kind = self.kind(name)
            params = self._tool_params_for_llm(name)
            constraints = self._tool_constraints_for_llm(name, kind)
            entries.append(
                f"### {name}\n"
                f"- type: {kind}\n"
                f"- parameters: {params}\n"
                f"- constraints: {constraints}\n"
            )
        return "## Available Tools\n\n" + "\n".join(entries)

    def _tool_params_for_llm(self, name: str) -> str:
        params_map: Dict[str, str] = {
            "find_user_id_by_email": "email (string)",
            "find_user_id_by_name_zip": "first_name (string), last_name (string), zip (string)",
            "get_user_details": "user_id (string)",
            "get_order_details": "order_id (string)",
            "get_product_details": "product_id (string)",
            "get_item_details": "item_id (string)",
            "list_all_product_types": "(none)",
            "calculate": "expression (string)",
            "cancel_pending_order": "order_id (string), reason (string: no longer needed | ordered by mistake)",
            "modify_pending_order_address": "order_id (string), address1 (string), address2 (string), city (string), state (string), country (string), zip (string)",
            "modify_pending_order_items": "order_id (string), item_ids (list of strings), new_item_ids (list of strings)",
            "modify_pending_order_payment": "order_id (string), payment_method_id (string)",
            "modify_user_address": "user_id (string), address1 (string), address2 (string), city (string), state (string), country (string), zip (string)",
            "return_delivered_order_items": "order_id (string), item_ids (list of strings), payment_method_id (string)",
            "exchange_delivered_order_items": "order_id (string), item_ids (list of strings), new_item_ids (list of strings), payment_method_id (string)",
            "transfer_to_human_agents": "summary (string)",
        }
        return params_map.get(name, "(see function signature)")

    def _tool_constraints_for_llm(self, name: str, kind: str) -> str:
        if kind == "read":
            return "read-only, no confirmation needed"
        if name == "transfer_to_human_agents" or name == "calculate":
            return "no special constraints"
        constraint_map: Dict[str, str] = {
            "cancel_pending_order": "order must be pending; requires user confirmation; reason must be 'no longer needed' or 'ordered by mistake'",
            "modify_pending_order_address": "order must be pending; requires user confirmation",
            "modify_pending_order_items": "order must be pending; new items must be same product as old; new items must be available; count must match; requires user confirmation",
            "modify_pending_order_payment": "order must be pending; payment method must belong to user; must differ from current; gift card must have sufficient balance; requires user confirmation",
            "modify_user_address": "target user must be authenticated user; address passed to user_id argument; requires user confirmation",
            "return_delivered_order_items": "order must be delivered; items must be in the order; payment method must belong to user; requires user confirmation",
            "exchange_delivered_order_items": "order must be delivered; old and new item counts must match; new items must be same product as old; new items must be available; payment method must belong to user; requires user confirmation",
        }
        return constraint_map.get(name, "requires user confirmation")
