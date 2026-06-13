from __future__ import annotations

from typing import Any, List

from app.agent.models import ToolCallRecord


class ScriptedToolGateway:
    """按脚本返回预先记录的工具结果，不执行真实工具。

    用于 trace replay：从 trace artifact 的 tool_calls 段重建
    ToolCallRecord 列表，注入到 AgentLoop 替代真实 ToolGateway。
    """

    def __init__(self, results: List[ToolCallRecord]) -> None:
        self._results = list(results)
        self.calls: List[dict] = []

    def execute(
        self,
        state: Any,
        tool_name: str,
        arguments: dict,
        confirmed: bool = False,
    ) -> ToolCallRecord:
        self.calls.append({
            "tool_name": tool_name,
            "arguments": arguments,
            "confirmed": confirmed,
        })
        if not self._results:
            raise RuntimeError(
                f"No scripted tool results remain for {tool_name}"
            )
        expected = self._results.pop(0)
        if expected.tool_name != tool_name:
            raise RuntimeError(
                f"Tool mismatch: expected {expected.tool_name}, got {tool_name}"
            )
        return expected
