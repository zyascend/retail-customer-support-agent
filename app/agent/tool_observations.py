from __future__ import annotations

import json
from typing import Any

TOOL_OBSERVATION_LIMIT = 4000
PRIORITY_OBSERVATION_KEYS = (
    "status",
    "order_status",
    "order_id",
    "user_id",
    "email",
    "name",
    "pending_confirmation",
    "guard_decision",
    "block_reason",
    "block_context",
    "orders",
)


def format_tool_observation(
    observation: Any,
    limit: int = TOOL_OBSERVATION_LIMIT,
) -> str:
    """Compact tool observations while keeping top-level facts visible."""
    if observation is None:
        return "(none)"

    payload = _prioritize_observation_keys(observation)
    try:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = str(payload)

    if len(text) <= limit:
        return text
    return f"{text[:limit]}...[truncated]"


def _prioritize_observation_keys(observation: Any) -> Any:
    if not isinstance(observation, dict):
        return observation

    prioritized: dict[str, Any] = {}
    for key in PRIORITY_OBSERVATION_KEYS:
        if key in observation:
            prioritized[key] = observation[key]

    for key, value in observation.items():
        if key not in prioritized:
            prioritized[key] = value

    return prioritized
