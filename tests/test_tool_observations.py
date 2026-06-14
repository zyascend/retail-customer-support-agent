from __future__ import annotations

from app.agent.tool_observations import format_tool_observation


def test_order_status_is_visible() -> None:
    content = format_tool_observation(
        {
            "items": [{"sku": "A1"}],
            "order_id": "#W123",
            "status": "pending",
        }
    )

    assert '"status":"pending"' in content
    assert '"order_id":"#W123"' in content


def test_priority_keys_precede_bulky_payload() -> None:
    content = format_tool_observation(
        {
            "payload": {"text": "x" * 50},
            "status": "pending",
            "user_id": "user_1",
        }
    )

    assert content.index('"status"') < content.index('"payload"')
    assert content.index('"user_id"') < content.index('"payload"')


def test_oversized_payload_preserves_priority_before_truncation() -> None:
    content = format_tool_observation(
        {
            "payload": "x" * 5000,
            "status": "pending",
            "order_id": "#W123",
        },
        limit=80,
    )

    assert content.startswith('{"status":"pending","order_id":"#W123"')
    assert content.endswith("...[truncated]")
    assert len(content) > 80


def test_non_dict_observation_has_deterministic_string() -> None:
    assert format_tool_observation(["alpha", "beta"]) == '["alpha","beta"]'
