"""Layer 0 — 纯格式提取正则。

格式不随语言变化（邮箱就是邮箱、订单号就是订单号），因此本模块
语言无关：加一门语言无需改动此处。语义相关的检测走 Layer 1
（action_candidates，意图 HINT）与 Layer 2（security，安全 GATE），
意图泛化由主 LLM 的 tool-call 兜底。

迁移来源：``parsers.py`` 的 ``EMAIL_RE`` / ``NAME_ZIP_RE``。
"""

from __future__ import annotations

import re
from typing import Optional

from app.agent.guard import _canonical_order_id

# ── 模块级正则常量（保留 public 名，供 runtime 等沿用 .search 调用） ──

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")

# 英文 "my name is X Y ... zip code is Z" 句式快路径 + 中文等价。
# 预检短路需设置 authenticated_user_id（主 LLM 调 find_user_id_by_name_zip
# 只是读操作，不会设认证态），故中文句式也需在此捕获。非中英文 miss
# → 由主 LLM 调 find_user_id_by_name_zip 兜底（见 spec §1.3）。
NAME_ZIP_RE = re.compile(
    r"(?:my name is|i am|i'm)\s+([A-Za-z]+)\s+([A-Za-z]+).*?"
    r"\bzip(?:[ -]?code)? is\s+(\d{5}(?:-\d{4})?)"
    r"|(?:我叫|我是|我的名字是)\s+([A-Za-z]+)\s+([A-Za-z]+).*?"
    r"邮编(?:是|为)?\s*(\d{5}(?:-\d{4})?)",
    re.IGNORECASE,
)

# ── 订单 ID 提取（两段式：显式 #W 优先于 "order W123" 上下文） ──
# 迁移自 action_candidates._extract_order_id，语义零变化。
_EXPLICIT_ORDER_ID_RE = re.compile(r"#W\d{7,}", re.IGNORECASE)
_ORDER_CONTEXT_ID_RE = re.compile(
    r"\border\s+(?P<order_id>#?(?:W)?\d{7,})", re.IGNORECASE
)


def extract_email(text: str) -> Optional[str]:
    """返回首个匹配的邮箱地址，无则 ``None``。"""
    match = EMAIL_RE.search(text)
    return match.group(0) if match else None


def extract_name_zip(text: str) -> Optional[tuple[str, str, str]]:
    """返回 ``(first_name, last_name, zip)``，无中英文句式匹配则 ``None``。

    支持英文 "my name is X Y ... zip code is Z" 与中文
    "我叫 X Y ... 邮编是 Z" 两种句式（见 spec §5）。
    """
    match = NAME_ZIP_RE.search(text)
    if match is None:
        return None
    groups = match.groups()
    # 英文分支（1-3 组）或中文分支（4-6 组），择非 None 者
    if groups[0] is not None:
        return groups[0], groups[1], groups[2]
    return groups[3], groups[4], groups[5]


def extract_order_id(text: str) -> Optional[str]:
    """提取订单 ID 并规范化为 ``#W\\d+``。

    两段式（与原 action_candidates._extract_order_id 一致）：
    1. 显式 ``#W\\d{7,}`` 优先；
    2. 否则 "order <id>" 上下文匹配；
    3. 均无则 ``None``。
    """
    explicit = _EXPLICIT_ORDER_ID_RE.search(text)
    if explicit:
        return _canonical_order_id(explicit.group(0))
    contextual = _ORDER_CONTEXT_ID_RE.search(text)
    if contextual:
        return _canonical_order_id(contextual.group("order_id"))
    return None
