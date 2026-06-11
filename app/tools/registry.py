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

