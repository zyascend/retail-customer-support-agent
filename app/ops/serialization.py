from __future__ import annotations

import json
from hashlib import sha256
from typing import Any


def to_plain_data(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {str(key): to_plain_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain_data(item) for item in value]
    return value


def stable_json(value: Any) -> str:
    return json.dumps(to_plain_data(value), sort_keys=True, default=str)


def stable_hash(value: Any) -> str:
    return sha256(stable_json(value).encode("utf-8")).hexdigest()

