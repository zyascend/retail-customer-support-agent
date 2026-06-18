from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Dict

from app.agent.action_specs import WRITE_TOOL_NAMES
from app.agent.action_specs import tool_constraints_for_llm as _spec_constraints
from app.agent.action_specs import tool_params_for_llm as _spec_params
from app.agent.models import ToolKind

# Experimental `think` tool — a no-side-effect reasoning slot the model can call
# before a write to decide which tool/params to use. Gated behind
# ``enable_think_tool`` (default OFF) pending a live-eval A/B; see spec §2.2.
THINK_TOOL_NAME = "think"
_THINK_TOOL_DESCRIPTION = (
    "Reason step-by-step about which tool to call, whether enough facts are "
    "loaded, or whether the request needs clarification — BEFORE issuing a write "
    "tool. No side effects; returns {\"status\": \"ok\"}. Do NOT use as a "
    "substitute for loading facts with read tools."
)


def _think(reasoning: str) -> dict[str, str]:
    """No-op reasoning slot. Always succeeds; the value is the act of thinking."""
    return {"status": "ok"}


# Attach the description via the Task B attribute contract so it is the single
# source of truth (highest-priority in _raw_description), rather than relying on
# a separate dict entry that could drift from the implementation.
_think.__tool_description__ = _THINK_TOOL_DESCRIPTION


# US 50 states + DC excluded — domain only ships to 50 states per policy.
# Kept sorted so the generated JSON-schema `enum` is stable across runs.
_US_STATES: tuple[str, ...] = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: ToolKind
    func: Callable[..., Any]


class ToolRegistry:
    _TOOL_DESCRIPTIONS: dict[str, str] = {
        "get_order_details": "Look up order status, items, shipping address, and payment info by order ID. Use before any order modification. Returns order dict with status, items, address, payment fields.",
        "get_user_details": "Look up user profile by user_id. Use after find_user_id_by_email or find_user_id_by_name_zip to get user info. Returns user dict with name, email, address, payment_methods.",
        "get_item_details": "Look up item details including product ID and price by item_id. Returns item dict with item_id, product_id, price, name.",
        "get_product_details": "Look up product info by product_id. Returns all variants with item_id, availability, price, and options. Use this to choose exact replacement variants.",
        "find_user_id_by_email": "Find a user's internal ID by email address. Use when the user provides their email. Returns user_id string.",
        "find_user_id_by_name_zip": "Find a user's internal ID by first name, last name, and zip code. Use when user provides name+zip instead of email. Returns user_id string.",
        "cancel_pending_order": "Cancel a pending order. Only works on orders with status 'pending'. Reason must be 'no longer needed' or 'ordered by mistake'. Requires explicit user confirmation.",
        "modify_pending_order_address": "Change shipping address for a pending order. Requires full address (address1, city, state, country, zip). Requires user confirmation.",
        "modify_pending_order_items": "Replace one or more items in a pending order with different items. For multiple replacements in the same order, call once with parallel item_ids and new_item_ids arrays. New items must be same product type as originals, available, and count must match. After this succeeds, calculate any gift-card balance or price difference instead of calling modify_pending_order_payment for replacement charges. Requires user confirmation.",
        "modify_pending_order_payment": "Change payment method for a pending order. New payment must differ from current, belong to the user. Do not use after modify_pending_order_items just to cover replacement charges or answer balance questions. Gift cards must have sufficient balance. Requires user confirmation.",
        "modify_pending_order_shipping_method": "Change shipping method for a pending order. Valid methods: standard, express, overnight. Upgrading from standard may require payment method. Requires user confirmation.",
        "return_delivered_order_items": "Return one or more items from a delivered order for refund. Every returned item_id must come from get_order_details for that exact order, not from product/catalog variants. Refund to specified payment method that belongs to user; if the user has exactly one eligible payment method, use it instead of asking. Requires user confirmation.",
        "exchange_delivered_order_items": "Exchange items from a delivered order for new items. Old item_ids must come from get_order_details for that exact order; catalog variant IDs are only valid as new_item_ids. Old and new counts must match. New items must be same product type and available; match all requested options such as canister/bagless when present. Any price difference processed via payment method; if the user has exactly one eligible payment method, use it instead of asking. Requires user confirmation.",
        "modify_user_address": "Change the default address for the authenticated user. Requires full address fields. Requires user confirmation.",
        "calculate": "Evaluate a mathematical expression. For internal calculations only.",
        "transfer_to_human_agents": "Transfer the conversation to a human support agent. Use when the request cannot be handled by available tools.",
        "list_all_product_types": "List all available product categories in the catalog. Read-only. Returns list of product type names.",
    }

    _ARG_DESCRIPTIONS: dict[str, str] = {
        "order_id": "Order ID starting with #W (e.g. #W5918442)",
        "user_id": "Internal user ID returned by find_user_id_by_email or find_user_id_by_name_zip",
        "email": "User's email address",
        "first_name": "User's first name",
        "last_name": "User's last name",
        "zip": "5-digit ZIP code",
        "item_id": "Item ID (numeric string from order items list)",
        "item_ids": "List of existing order item IDs to modify/return/exchange (numeric strings from get_order_details for the exact order). Include all target items for the same order in one call when possible.",
        "new_item_ids": "List of replacement catalog/variant item IDs, same count and order as item_ids; use parallel arrays old_item_ids[i] -> new_item_ids[i].",
        "product_id": "Product ID from catalog",
        "payment_method_id": "Payment method ID from user profile (e.g. credit_card_XXXX or gift_card_XXXX)",
        "reason": "Cancellation reason: 'no longer needed' or 'ordered by mistake'",
        "address1": "Street address line 1",
        "address2": "Apartment/unit number (optional)",
        "city": "City name",
        "state": "2-letter state abbreviation (e.g. TX, CA)",
        "country": "Country name (e.g. USA)",
        "shipping_method": "Shipping method: 'standard', 'express', or 'overnight'",
        "summary": "Brief summary of the conversation and reason for transfer",
        "expression": "Mathematical expression to evaluate",
    }

    def __init__(self, toolkit: Any, enable_think_tool: bool = False) -> None:
        self.toolkit = toolkit
        self._tools = self._discover(toolkit)
        if enable_think_tool:
            # Inject the experimental think tool as a pure registry-level
            # function (not part of any toolkit/db), so it never contaminates
            # test data or the tau/synthetic adapters.
            self._tools[THINK_TOOL_NAME] = ToolSpec(
                name=THINK_TOOL_NAME, kind="think", func=_think
            )

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
            THINK_TOOL_NAME: "reasoning (string)",
        }
        if name in params_map:
            return params_map[name]
        return _spec_params(name)

    def _tool_constraints_for_llm(self, name: str, kind: str) -> str:
        if kind == "read":
            return "read-only, no confirmation needed"
        if name == "transfer_to_human_agents" or name == "calculate":
            return "no special constraints"
        if name == THINK_TOOL_NAME:
            return "no side effects, no confirmation needed"
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

    def _raw_description(self, name: str) -> str:
        """Authoritative tool description with single-source-of-truth fallback.

        Resolution order (first non-empty wins), so a function's own metadata
        always overrides the legacy hardcoded dict — preventing the two from
        silently drifting when a signature changes:
        1. ``func.__tool_description__`` — explicit attribute on the function
        2. ``func.__doc__`` (first-sentence, stripped) — auto-extracted docstring
        3. ``_TOOL_DESCRIPTIONS`` legacy dict
        4. the tool name itself
        """
        if name in self._tools:
            func = self._tools[name].func
            attr = getattr(func, "__tool_description__", None)
            if attr:
                return attr
            doc = getattr(func, "__doc__", None)
            if doc:
                first_line = doc.strip().split("\n")[0].strip()
                if first_line:
                    return first_line
        return self._TOOL_DESCRIPTIONS.get(name) or name

    def _tool_description_for_llm(self, name: str) -> str:
        desc = self._raw_description(name)
        kind = self.kind(name)
        if kind == "read":
            return (
                f"{desc} Read-only. When to use: load facts before answering or "
                "before any related write. Do not use for writes."
            )
        if kind == "write":
            prior_reads = self._required_prior_reads_for_tool(name)
            constraints = self._tool_constraints_for_llm(name, kind)
            return (
                f"{desc} When to use: after the user requests this exact account "
                "or order change. When not to use: do not use for lookup-only "
                "questions or unrelated actions. Required prior reads: "
                f"{prior_reads}. Guard blocks: if blocked, explain the guard "
                f"reason from the tool observation. Constraints: {constraints}"
            )
        if name == "transfer_to_human_agents":
            return (
                f"{desc} When to use: after available tools cannot resolve the "
                "request or the user explicitly asks for a human."
            )
        if name == "calculate":
            return f"{desc} When to use: arithmetic only. Do not use for policy decisions."
        if name == THINK_TOOL_NAME:
            # desc already carries the full usage contract; no suffix needed.
            return desc
        return desc

    def _required_prior_reads_for_tool(self, name: str) -> str:
        if name == "modify_user_address":
            return "get_user_details for the authenticated user_id"
        if name in WRITE_TOOL_NAMES:
            return "get_order_details for the target order_id"
        constraints = self._tool_constraints_for_llm(name, self.kind(name))
        return constraints

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
            THINK_TOOL_NAME: ["reasoning"],
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

    def _arg_description(self, arg_name: str) -> str:
        return self._ARG_DESCRIPTIONS.get(arg_name, "")

    def _property_schema(self, tool_name: str, arg_name: str) -> dict[str, Any]:
        desc = self._arg_description(arg_name)
        if arg_name == "order_id":
            result = {"type": "string", "pattern": "^#W\\d+$"}
            if desc:
                result["description"] = desc
            return result
        if arg_name in {"item_ids", "new_item_ids"}:
            result = {
                "type": "array",
                "items": {"type": "string", "pattern": "^\\d+$"},
            }
            if desc:
                result["description"] = desc
            return result
        if arg_name == "payment_method_id":
            result = {
                "type": "string",
                "pattern": "^(credit_card|gift_card|paypal)_\\d+$",
            }
            if desc:
                result["description"] = desc
            return result
        if tool_name == "cancel_pending_order" and arg_name == "reason":
            return {
                "type": "string",
                "enum": ["no longer needed", "ordered by mistake"],
                "description": desc,
            }
        if tool_name == "modify_pending_order_shipping_method" and arg_name == "shipping_method":
            return {
                "type": "string",
                "enum": ["standard", "express", "overnight"],
                "description": desc,
            }
        if arg_name == "state":
            result: dict[str, Any] = {
                "type": "string",
                "enum": list(_US_STATES),
            }
            if desc:
                result["description"] = desc
            return result
        if arg_name == "zip":
            result = {"type": "string", "pattern": "^\\d{5}$"}
            if desc:
                result["description"] = desc
            return result
        if arg_name == "country":
            result = {"type": "string", "enum": ["USA"]}
            if desc:
                result["description"] = desc
            return result
        if arg_name == "email":
            result = {"type": "string", "pattern": "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"}
            if desc:
                result["description"] = desc
            return result
        if arg_name == "reasoning":
            return {
                "type": "string",
                "description": (
                    "Step-by-step reasoning: which tool/params to use, whether "
                    "enough facts are loaded, or whether clarification is needed."
                ),
            }
        result = {"type": "string"}
        if desc:
            result["description"] = desc
        return result
