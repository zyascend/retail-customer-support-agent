# app/synthetic/oracle.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class DeterministicOracle:
    """从 variant 类型自动派生的标准答案（用于 eval 断言）"""
    expected_user_id: str
    expected_intent: str
    order_id: str | None = None
    expected_write_lock: str | None = None
    expected_order_status: str | None = None
    expected_confirmation_status: str = "confirmed"
    expected_guard_block_reason: str | None = None
    expected_no_write: bool = False
    expected_tool_names: List[str] = field(default_factory=list)
    expected_db_assertions: Dict[str, Any] = field(default_factory=dict)
    expected_tool_sequence: List[str] = field(default_factory=list)
