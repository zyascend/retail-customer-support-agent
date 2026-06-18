from __future__ import annotations

from typing import Any, Callable, Dict

from app.config import resolve_config
from app.tools.registry import ToolRegistry
from app.tools.retail_adapter import RetailAdapter


def _registry() -> ToolRegistry:
    runtime = RetailAdapter(resolve_config()).create_runtime()
    return ToolRegistry(runtime.tools)


class _StubToolkit:
    """Minimal toolkit for registry unit tests (no db required)."""

    def __init__(self, tools: Dict[str, Callable[..., Any]]) -> None:
        self.tools = tools

    def tool_type(self, name: str) -> str:
        if name.startswith(("get_", "find_", "list_")):
            return "read"
        if name == "calculate" or name == "transfer_to_human_agents":
            return "generic"
        return "write"


def test_tool_schemas_cover_all_registry_tools() -> None:
    registry = _registry()

    schemas = registry.tool_schemas_for_llm()
    schema_names = {
        schema["function"]["name"]
        for schema in schemas
        if schema.get("type") == "function"
    }

    assert schema_names == set(registry.tools)


def test_cancel_order_schema_has_reason_enum() -> None:
    registry = _registry()

    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "cancel_pending_order"
    )
    params = schema["function"]["parameters"]

    assert params["required"] == ["order_id", "reason"]
    assert params["properties"]["reason"]["enum"] == [
        "no longer needed",
        "ordered by mistake",
    ]
    assert params["additionalProperties"] is False


def test_item_array_schema_declares_string_items() -> None:
    registry = _registry()

    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "modify_pending_order_items"
    )
    params = schema["function"]["parameters"]

    assert params["properties"]["item_ids"] == {
        "type": "array",
        "items": {"type": "string", "pattern": "^\\d+$"},
        "description": (
            "List of existing order item IDs to modify/return/exchange (numeric "
            "strings from get_order_details for the exact order). Include all "
            "target items for the same order in one call when possible."
        ),
    }
    assert params["properties"]["new_item_ids"] == {
        "type": "array",
        "items": {"type": "string", "pattern": "^\\d+$"},
        "description": (
            "List of replacement catalog/variant item IDs, same count and order as "
            "item_ids; use parallel arrays old_item_ids[i] -> new_item_ids[i]."
        ),
    }


def test_modify_order_payment_schema_has_required_fields() -> None:
    registry = _registry()

    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "modify_pending_order_payment"
    )
    params = schema["function"]["parameters"]

    assert params["required"] == ["order_id", "payment_method_id"]
    assert params["properties"]["payment_method_id"] == {
        "type": "string",
        "pattern": "^(credit_card|gift_card|paypal)_\\d+$",
        "description": "Payment method ID from user profile (e.g. credit_card_XXXX or gift_card_XXXX)",
    }
    assert params["additionalProperties"] is False


def test_modify_user_address_schema_requires_address2() -> None:
    registry = _registry()

    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "modify_user_address"
    )
    params = schema["function"]["parameters"]

    assert params["required"] == [
        "user_id",
        "address1",
        "address2",
        "city",
        "state",
        "country",
        "zip",
    ]
    assert params["properties"]["address2"] == {
        "type": "string",
        "description": "Apartment/unit number (optional)",
    }


def test_write_tool_descriptions_include_selection_contract() -> None:
    registry = _registry()
    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "cancel_pending_order"
    )
    description = schema["function"]["description"]

    assert "When to use:" in description
    assert "When not to use:" in description
    assert "Required prior reads:" in description
    assert "Guard blocks:" in description


def test_read_tool_description_tells_model_not_to_mutate() -> None:
    registry = _registry()
    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "get_order_details"
    )

    assert "Read-only" in schema["function"]["description"]
    assert "Do not use for writes" in schema["function"]["description"]


def test_payment_method_schema_uses_pattern() -> None:
    registry = _registry()
    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "return_delivered_order_items"
    )
    payment = schema["function"]["parameters"]["properties"]["payment_method_id"]

    assert payment["pattern"] == "^(credit_card|gift_card|paypal)_\\d+$"


def test_address_schema_has_state_zip_country_constraints() -> None:
    registry = _registry()
    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "modify_pending_order_address"
    )
    props = schema["function"]["parameters"]["properties"]

    # state: enum of US 2-letter abbreviations
    state_schema = props["state"]
    assert state_schema["type"] == "string"
    assert {"TX", "CA", "NY"} <= set(state_schema["enum"])
    assert len(state_schema["enum"]) == 50
    assert all(len(code) == 2 and code.isupper() for code in state_schema["enum"])

    # zip: exactly 5 digits
    assert props["zip"] == {
        "type": "string",
        "pattern": "^\\d{5}$",
        "description": "5-digit ZIP code",
    }

    # country: restricted to USA
    assert props["country"] == {
        "type": "string",
        "enum": ["USA"],
        "description": "Country name (e.g. USA)",
    }


def test_email_schema_has_pattern() -> None:
    registry = _registry()
    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "find_user_id_by_email"
    )
    email_schema = schema["function"]["parameters"]["properties"]["email"]
    assert email_schema["type"] == "string"
    assert "pattern" in email_schema
    # Anchored, requires local@domain.tld, no spaces or extra @
    pattern = email_schema["pattern"]
    assert pattern.startswith("^") and pattern.endswith("$")
    import re

    assert re.match(pattern, "user@example.com")
    assert re.match(pattern, "a.b+co@sub.example.org")
    assert not re.match(pattern, "not-an-email")
    assert not re.match(pattern, "a@b")
    assert not re.match(pattern, "a b@example.com")


def test_order_and_item_ids_use_patterns() -> None:
    registry = _registry()
    cancel = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "cancel_pending_order"
    )
    exchange = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "exchange_delivered_order_items"
    )

    assert (
        cancel["function"]["parameters"]["properties"]["order_id"]["pattern"]
        == "^#W\\d+$"
    )
    assert (
        exchange["function"]["parameters"]["properties"]["item_ids"]["items"][
            "pattern"
        ]
        == "^\\d+$"
    )
    assert (
        exchange["function"]["parameters"]["properties"]["new_item_ids"]["items"][
            "pattern"
        ]
        == "^\\d+$"
    )


def _stub_toolkit_with_override() -> _StubToolkit:
    def get_thing(thing_id: str) -> dict[str, Any]:
        return {"thing_id": thing_id}

    # Attribute takes precedence over the legacy dict below.
    get_thing.__tool_description__ = (
        "OVERRIDE: lookup a thing by id from the attribute source."
    )
    # A second tool without any attribute — will fall through to the legacy
    # dict, which is empty for these stub names, then to the name itself.
    def get_widget(widget_id: str) -> dict[str, Any]:
        return {"widget_id": widget_id}

    return _StubToolkit({"get_thing": get_thing, "get_widget": get_widget})


def test_tool_description_prefers_function_attribute() -> None:
    toolkit = _stub_toolkit_with_override()
    registry = ToolRegistry(toolkit)

    override_schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "get_thing"
    )
    # The attribute string must appear in the assembled description.
    assert "OVERRIDE" in override_schema["function"]["description"]


def test_tool_description_falls_back_to_name_when_no_dict_no_attr() -> None:
    toolkit = _stub_toolkit_with_override()
    registry = ToolRegistry(toolkit)

    widget_schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "get_widget"
    )
    # No attribute, no legacy-dict entry → falls back to the tool name itself.
    assert "get_widget" in widget_schema["function"]["description"]


def test_think_tool_absent_by_default() -> None:
    toolkit = _StubToolkit(
        {"get_order_details": lambda order_id: {"order_id": order_id}}
    )
    registry = ToolRegistry(toolkit)  # enable_think_tool defaults to False
    names = {item["function"]["name"] for item in registry.tool_schemas_for_llm()}
    assert "think" not in names
    # And it must not appear in the catalog text either.
    assert "think" not in registry.tool_catalog_for_llm()


def test_think_tool_present_when_enabled() -> None:
    toolkit = _StubToolkit(
        {"get_order_details": lambda order_id: {"order_id": order_id}}
    )
    registry = ToolRegistry(toolkit, enable_think_tool=True)

    # kind is "think" (not misclassified as write by the fallback).
    assert registry.kind("think") == "think"

    schema = next(
        item
        for item in registry.tool_schemas_for_llm()
        if item["function"]["name"] == "think"
    )
    fn = schema["function"]
    assert fn["parameters"]["required"] == ["reasoning"]
    props = fn["parameters"]["properties"]
    assert props["reasoning"]["type"] == "string"
    assert "Step-by-step" in props["reasoning"]["description"]
    # Description carries the usage contract and the no-side-effect note.
    assert "no side effect" in fn["description"].lower()
    assert "reason" in fn["description"].lower()

    # Executing the tool is a no-op that never touches the guard.
    assert registry.get("think").func(reasoning="plan a write") == {"status": "ok"}

    # Catalog advertises it too.
    assert "think" in registry.tool_catalog_for_llm()
