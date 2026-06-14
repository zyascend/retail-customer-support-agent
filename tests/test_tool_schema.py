from __future__ import annotations

from app.config import resolve_config
from app.tools.registry import ToolRegistry
from app.tools.retail_adapter import RetailAdapter


def _registry() -> ToolRegistry:
    runtime = RetailAdapter(resolve_config()).create_runtime()
    return ToolRegistry(runtime.tools)


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
        "description": "List of item IDs to modify/return/exchange (numeric strings)",
    }
    assert params["properties"]["new_item_ids"] == {
        "type": "array",
        "items": {"type": "string", "pattern": "^\\d+$"},
        "description": "List of replacement item IDs, must be same count as item_ids",
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
