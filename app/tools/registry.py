from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Dict

from app.agent.action_specs import WRITE_TOOL_NAMES
from app.agent.action_specs import tool_constraints_for_llm as _spec_constraints
from app.agent.action_specs import tool_params_for_llm as _spec_params
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
            "transfer_to_human_agents": "summary (string)",
        }
        if name in params_map:
            return params_map[name]
        return _spec_params(name)

    def _tool_constraints_for_llm(self, name: str, kind: str) -> str:
        if kind == "read":
            return "read-only, no confirmation needed"
        if name == "transfer_to_human_agents" or name == "calculate":
            return "no special constraints"
        if name in WRITE_TOOL_NAMES:
            return _spec_constraints(name)
        return "requires user confirmation"

    def tool_schemas_for_llm(self) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for name in sorted(self._tools):
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": self._tool_description_for_llm(name),
                        "parameters": self._json_schema_for_tool(name),
                    },
                }
            )
        return schemas

    def _tool_description_for_llm(self, name: str) -> str:
        constraints = self._tool_constraints_for_llm(name, self.kind(name))
        return f"{name}. {constraints}"

    def _json_schema_for_tool(self, name: str) -> dict[str, Any]:
        required = self.required_args_for_tool(name)
        properties = {arg: self._property_schema(name, arg) for arg in required}
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    def required_args_for_tool(self, name: str) -> list[str]:
        explicit: dict[str, list[str]] = {
            "find_user_id_by_email": ["email"],
            "find_user_id_by_name_zip": ["first_name", "last_name", "zip"],
            "get_user_details": ["user_id"],
            "get_order_details": ["order_id"],
            "get_product_details": ["product_id"],
            "get_item_details": ["item_id"],
            "calculate": ["expression"],
            "transfer_to_human_agents": ["summary"],
        }
        if name in explicit:
            return explicit[name]
        params_text = self._tool_params_for_llm(name)
        if params_text == "(none)":
            return []
        if params_text != "(see function signature)":
            return [part.strip().split(" ")[0] for part in params_text.split(",")]
        signature = inspect.signature(self.get(name).func)
        return [
            param_name
            for param_name, param in signature.parameters.items()
            if param.default is inspect.Parameter.empty
        ]

    def _property_schema(self, tool_name: str, arg_name: str) -> dict[str, Any]:
        if arg_name in {"item_ids", "new_item_ids"}:
            return {"type": "array", "items": {"type": "string"}}
        if tool_name == "cancel_pending_order" and arg_name == "reason":
            return {
                "type": "string",
                "enum": ["no longer needed", "ordered by mistake"],
            }
        if tool_name == "modify_pending_order_shipping_method" and arg_name == "shipping_method":
            return {"type": "string", "enum": ["standard", "express", "overnight"]}
        return {"type": "string"}
