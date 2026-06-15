from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.agent.action_specs import WRITE_ACTION_REGISTRY
from app.agent.prompts import prompt_metadata
from app.config import AppConfig
from app.ops.serialization import stable_hash
from app.tools.registry import ToolRegistry
from app.tools.retail_adapter import RetailAdapter


def build_baseline_metadata(
    *,
    config: AppConfig,
    subset: str,
    eval_backend: str,
    live: bool,
    require_llm: bool,
) -> dict[str, Any]:
    registry = ToolRegistry(RetailAdapter(config).create_runtime().tools)
    provider = "deepseek" if live or require_llm else "no_provider"
    prompt_info = prompt_metadata()
    return {
        "subset": subset,
        "eval_backend": eval_backend,
        "model": config.default_agent_model,
        "provider": provider,
        "prompt_hash": stable_hash(prompt_info),
        "tool_schema_hash": stable_hash(registry.tool_schemas_for_llm()),
        "action_specs_hash": stable_hash(
            [asdict(spec) for spec in WRITE_ACTION_REGISTRY]
        ),
    }
