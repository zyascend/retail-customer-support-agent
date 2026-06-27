# Phase 1a 交互真实化核心 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 agent 在真实多轮对话里表现得像真人客服——screen pop 进线预查订单、鲁棒指代消解、确认中可打断穿插。

**Architecture:** additive 改造，不重写编排器。新增 `list_user_orders` read tool + `ScreenPop` helper（会话建立时身份即设、主动查一次订单）；`confirmation.py` 加 `has_competing_signal` 让混合/打断信号 fallback 到 LLM（`changed` 分支逐字节不动护基线）；`context_builder` 订单含商品名 + pending 含参数；prompt 加指代消解启发式 + 打断处理段；新 eval 子集 `realistic_conversation` + 行为 rubric。

**Tech Stack:** Python 3.12 / pydantic / FastAPI / pytest / DeepSeek LLM / tau2-bench retail adapter

**基线保护纪律：** 每个动共享路径的 task 落地后跑 `generalized_mvp` 确认不回归。路由类改动可由构造证明不回归（25 条确认消息逐分支 identical）；`context_builder`/prompt 改动不能先验证明，掉点即 bisect。

---

## 文件结构

| 文件 | 责任 | 动作 |
|------|------|------|
| `app/tools/retail_adapter.py` | `LocalRetailTools.list_user_orders` + tau2 wrapper | 新增方法 |
| `app/tools/registry.py` | `list_user_orders` 进 READ_TOOLS + schema 描述 | 修改 |
| `app/agent/screen_pop.py` | `ScreenPop.apply`：身份即设 + 主动查一次订单 | 新建 |
| `app/agent/confirmation.py` | `has_competing_signal` + `_has_question` | 新增函数 |
| `app/agent/runtime.py` | `_preflight_confirmation` 路由修正（changed 独立分支）+ screen pop 接入 `run_script` | 修改 |
| `app/agent/context_builder.py` | 订单含商品名 + pending 含参数 | 修改 |
| `prompts/llm_agent_system_v001.md` | 指代消解启发式 + 打断处理段 | 修改 |
| `app/eval/cases.py` | `screen_pop_user_id` + `expected_behaviors` 字段 + `REALISTIC_CONVERSATION_CASES` | 修改 |
| `app/eval/runner.py` | screen pop 预载 + `evaluate_behaviors` 纯函数 | 修改 |
| `app/cli/chat.py` | `--customer` 参数触发 screen pop | 修改 |
| `app/workbench/session.py` | demo 模式 screen pop（无 case 时） | 修改 |
| `tests/test_list_user_orders.py` | list_user_orders 单元 | 新建 |
| `tests/test_screen_pop.py` | ScreenPop 单元 | 新建 |
| `tests/test_confirmation_competing.py` | has_competing_signal 单元 | 新建 |
| `tests/test_context_builder_rich.py` | 商品名/pending 详情 | 新建 |
| `tests/test_preflight_routing.py` | 路由分支 + changed 不回归 | 新建 |

---

## Task 1: `list_user_orders` read tool — LocalRetailTools 实现

**Files:**
- Modify: `app/tools/retail_adapter.py:13-21`（READ_TOOLS）+ `app/tools/retail_adapter.py:208` 后新增方法
- Test: `tests/test_list_user_orders.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_list_user_orders.py
from __future__ import annotations
from app.tools.retail_adapter import LocalRetailTools


def _tools_with_one_order():
    db = {
        "users": {"sofia_rossi_8776": {"name": {}, "email": "s@example.com", "address": {}, "payment_methods": {}}},
        "orders": {
            "#W5918442": {"user_id": "sofia_rossi_8776", "status": "pending",
                          "items": [{"item_id": "111", "name": "Water Bottle", "price": 10.0}]},
            "#W4817420": {"user_id": "sofia_rossi_8776", "status": "delivered",
                          "items": [{"item_id": "222", "name": "Mug", "price": 5.0}]},
            "#W0000001": {"user_id": "other_user", "status": "pending", "items": []},
        },
        "products": {},
    }
    return LocalRetailTools(db)


def test_list_user_orders_filters_by_user():
    tools = _tools_with_one_order()
    result = tools.list_user_orders("sofia_rossi_8776")
    order_ids = [o["order_id"] for o in result]
    assert order_ids == ["#W5918442", "#W4817420"]


def test_list_user_orders_summary_shape():
    tools = _tools_with_one_order()
    result = tools.list_user_orders("sofia_rossi_8776")
    first = result[0]
    assert first["order_id"] == "#W5918442"
    assert first["status"] == "pending"
    assert first["items"] == [{"item_id": "111", "name": "Water Bottle", "price": 10.0}]


def test_list_user_orders_empty():
    tools = _tools_with_one_order()
    assert tools.list_user_orders("nobody") == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_list_user_orders.py -v`
Expected: FAIL `AttributeError: 'LocalRetailTools' object has no attribute 'list_user_orders'`

- [ ] **Step 3: 注册到 READ_TOOLS**

```python
# app/tools/retail_adapter.py:13-21 — 在 READ_TOOLS 集合加 list_user_orders
READ_TOOLS = {
    "find_user_id_by_email",
    "find_user_id_by_name_zip",
    "get_user_details",
    "get_order_details",
    "get_product_details",
    "get_item_details",
    "list_all_product_types",
    "list_user_orders",
}
```

- [ ] **Step 4: 实现 list_user_orders 方法**

在 `app/tools/retail_adapter.py` 的 `list_all_product_types` 方法后（约 213 行后）新增：

```python
    def list_user_orders(self, user_id: str) -> list[dict[str, Any]]:
        """Return summary list of a user's orders (no heavy payment_history)."""
        orders = []
        for order_id, order in self.db.get("orders", {}).items():
            if order.get("user_id") != user_id:
                continue
            items = [
                {"item_id": str(it.get("item_id", "")),
                 "name": it.get("name", ""),
                 "price": it.get("price")}
                for it in order.get("items", []) or []
                if isinstance(it, dict)
            ]
            orders.append({
                "order_id": order_id,
                "status": order.get("status", ""),
                "order_date": order.get("order_date", ""),
                "items": items,
            })
        return orders
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_list_user_orders.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add app/tools/retail_adapter.py tests/test_list_user_orders.py
git commit -m "feat: 新增 list_user_orders read tool（LocalRetailTools）"
```

---

## Task 2: `list_user_orders` — registry schema + 越权校验

**Files:**
- Modify: `app/tools/registry.py:13`（READ_TOOLS 引用已含）+ `registry.py:54-72`（_TOOL_DESCRIPTIONS）+ `registry.py:74+`（_ARG_DESCRIPTIONS）
- Modify: `app/tools/gateway.py`（read tool 越权校验）
- Test: `tests/test_list_user_orders.py`（追加）

- [ ] **Step 1: 追加越权校验失败测试**

```python
# tests/test_list_user_orders.py 追加
from app.agent.models import SessionState
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry


def test_list_user_orders_blocked_for_other_user():
    tools = _tools_with_one_order()
    registry = ToolRegistry(tools.tools)
    gateway = ToolGateway(registry=registry, runtime=tools)
    state = SessionState(session_id="t")
    state.authenticated_user_id = "sofia_rossi_8776"
    # 查别人的订单 → blocked
    record = gateway.execute(
        state=state, tool_name="list_user_orders",
        arguments={"user_id": "other_user"},
    )
    assert record.status == "blocked"
    assert record.error == "ownership_violation"


def test_list_user_orders_allowed_for_authenticated_user():
    tools = _tools_with_one_order()
    registry = ToolRegistry(tools.tools)
    gateway = ToolGateway(registry=registry, runtime=tools)
    state = SessionState(session_id="t")
    state.authenticated_user_id = "sofia_rossi_8776"
    record = gateway.execute(
        state=state, tool_name="list_user_orders",
        arguments={"user_id": "sofia_rossi_8776"},
    )
    assert record.status == "success"
    assert len(record.observation) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_list_user_orders.py::test_list_user_orders_blocked_for_other_user -v`
Expected: FAIL（当前 read tool 不校验越权，返回 success）

- [ ] **Step 3: gateway 加 list_user_orders 越权校验**

在 `app/tools/gateway.py` 的 `execute` 方法内、`if spec.kind == "write":` 分支之前，新增 read 工具越权校验：

```python
        # list_user_orders 越权校验：user_id 必须是认证用户
        if tool_name == "list_user_orders":
            req_user = str(arguments.get("user_id", ""))
            if not state.authenticated_user_id or req_user != state.authenticated_user_id:
                observation = {
                    "status": "blocked",
                    "message_for_llm": "I can only list orders for the authenticated user.",
                }
                record = ToolCallRecord(
                    tool_name=tool_name,
                    arguments=arguments,
                    tool_kind=spec.kind,
                    status="blocked",
                    observation=observation,
                    error="ownership_violation",
                    before_db_hash=before_hash,
                    after_db_hash=before_hash,
                )
                state.tool_results.append(record)
                state.add_step(
                    "list_user_orders_guard",
                    status="blocked",
                    tool_name=tool_name,
                    block_reason="ownership_violation",
                )
                return record
```

- [ ] **Step 4: 加 LLM schema 描述**

在 `app/tools/registry.py` 的 `_TOOL_DESCRIPTIONS` dict 内追加：

```python
        "list_user_orders": "List all orders for the authenticated user. Returns order summaries with order_id, status, and item names. Use this to resolve vague references like 'my pending order' or 'the one that hasn't arrived'. Read-only.",
```

在 `_ARG_DESCRIPTIONS` dict 内追加（若该 dict 存在 user_id 条目则复用，否则加）：

```python
        "user_id": "The authenticated user's internal ID.",
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_list_user_orders.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: 跑 schema 测试确认不破坏**

Run: `uv run python -m pytest tests/test_tool_schema.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/tools/gateway.py app/tools/registry.py tests/test_list_user_orders.py
git commit -m "feat: list_user_orders 越权校验 + LLM schema 描述"
```

---

## Task 3: `has_competing_signal` + `_has_question`

**Files:**
- Modify: `app/agent/confirmation.py`（新增函数，不改现有 `ConfirmationResolver`）
- Test: `tests/test_confirmation_competing.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_confirmation_competing.py
from __future__ import annotations
from app.agent.confirmation import has_competing_signal, _has_question


def test_clean_confirm_no_competing():
    assert has_competing_signal("yes") is False
    assert has_competing_signal("确认") is False
    assert has_competing_signal("confirm") is False


def test_clean_deny_no_competing():
    assert has_competing_signal("no") is False
    assert has_competing_signal("取消") is False


def test_mixed_confirm_change_competing():
    assert has_competing_signal("嗯行吧不过换成 express") is True
    assert has_competing_signal("yes but change to express") is True


def test_question_with_signal_competing():
    assert has_competing_signal("确认，退款多少？") is True
    assert has_competing_signal("yes, how much is the refund?") is True


def test_question_alone_no_signal_no_competing():
    # 提问但无 confirm/deny/change 信号 → 不算 competing
    assert has_competing_signal("退款多少？") is False


def test_has_question_chinese():
    assert _has_question("退款多少") is True
    assert _has_question("怎么取消") is True


def test_has_question_english():
    assert _has_question("how much?") is True
    assert _has_question("what is the status") is True


def test_has_question_none():
    assert _has_question("yes") is False
    assert _has_question("帮我取消订单") is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_confirmation_competing.py -v`
Expected: FAIL `ImportError: cannot import name 'has_competing_signal'`

- [ ] **Step 3: 实现 has_competing_signal + _has_question**

在 `app/agent/confirmation.py` 末尾追加（不改现有 `_CONFIRM_KEYWORDS` / `ConfirmationResolver`）：

```python
_QUESTION_RE = re.compile(
    r"[?？]|多少|怎么|为什么|何时|what|how|why|when|where|"
    r"can you|能不能|是不是|有没有|退多少|多少钱"
)


def _has_question(text_lower: str) -> bool:
    return bool(_QUESTION_RE.search(text_lower))


def has_competing_signal(text: str) -> bool:
    """检测混合/竞争信号——需要 LLM 介入消歧的场景。

    仅在 confirm/deny/change 信号同时出现、或信号伴随提问时返回 True。
    干净的 yes/no 不触发，保护 fast-path 不回归。
    """
    text_lower = text.lower().strip()
    confirm = _score(text_lower, _CONFIRM_KEYWORDS)
    deny = _score(text_lower, _DENY_KEYWORDS)
    change = _score(text_lower, _CHANGE_KEYWORDS)
    if confirm >= 2 and change >= 2:
        return True
    if confirm >= 2 and deny >= 2:
        return True
    if _has_question(text_lower) and (confirm >= 2 or deny >= 2 or change >= 2):
        return True
    return False
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_confirmation_competing.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add app/agent/confirmation.py tests/test_confirmation_competing.py
git commit -m "feat: confirmation.has_competing_signal + _has_question"
```

---

## Task 4: `_preflight_confirmation` 路由修正（changed 独立分支不回归）

**Files:**
- Modify: `app/agent/runtime.py:287-354`（`_preflight_confirmation`）
- Test: `tests/test_preflight_routing.py`

- [ ] **Step 1: 写失败测试——干净确认仍短路执行**

```python
# tests/test_preflight_routing.py
from __future__ import annotations
from unittest.mock import MagicMock
from app.agent.models import SessionState, PendingAction
from app.agent.runtime import AgentRuntime


def _runtime_with_pending(monkeypatch):
    """构造一个有 pending_action 的 runtime，gateway 用 mock。"""
    from app.config import AppConfig
    from pathlib import Path
    config = AppConfig(
        tau3_retail_root=Path("/tmp"), tau2_bench_root=Path("/tmp"),
        artifact_dir=Path("/tmp"), deepseek_api_key="",
        default_agent_model="m",
    )
    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime.config = config
    runtime.gateway = MagicMock()
    runtime._resolver = __import__("app.agent.confirmation", fromlist=["ConfirmationResolver"]).ConfirmationResolver()
    runtime.provider = None
    runtime._context_builder = MagicMock()
    runtime._turn_contexts = []
    state = SessionState(session_id="t")
    state.authenticated_user_id = "u1"
    state.pending_action = PendingAction(
        action_name="cancel_pending_order",
        arguments={"order_id": "#W1", "reason": "no longer needed"},
        user_facing_summary="cancel",
    )
    return runtime, state


def test_clean_confirm_short_circuits(monkeypatch):
    runtime, state = _runtime_with_pending(monkeypatch)
    runtime.gateway.execute.return_value = MagicMock(status="success", observation={})
    msg = runtime._preflight_confirmation(state, "yes")
    # 干净确认 → gateway 用 confirmed=True 执行
    assert runtime.gateway.execute.call_args.kwargs.get("confirmed") is True
    assert state.pending_action is None


def test_clean_deny_discards(monkeypatch):
    runtime, state = _runtime_with_pending(monkeypatch)
    msg = runtime._preflight_confirmation(state, "no")
    assert state.pending_action is None
    assert "No changes" in msg


def test_changed_discards_pending(monkeypatch):
    runtime, state = _runtime_with_pending(monkeypatch)
    msg = runtime._preflight_confirmation(state, "No, use item 1234567890 instead.")
    assert state.pending_action is None
    assert "discarded" in msg.lower()


def test_mixed_confirm_falls_through_to_llm(monkeypatch):
    runtime, state = _runtime_with_pending(monkeypatch)
    msg = runtime._preflight_confirmation(state, "嗯行吧不过换成 express")
    # mixed → 放行 LLM，return None，pending 保持
    assert msg is None
    assert state.pending_action is not None


def test_denied_with_question_falls_through(monkeypatch):
    runtime, state = _runtime_with_pending(monkeypatch)
    msg = runtime._preflight_confirmation(state, "算了别取消了，退款多少？")
    # denied + 提问 → 丢弃 pending 后放行 LLM
    assert msg is None
    assert state.pending_action is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_preflight_routing.py -v`
Expected: FAIL（当前路由把 changed 折进 LLM fallback，`test_changed_discards_pending` 失败：pending 不为 None）

- [ ] **Step 3: 重写 `_preflight_confirmation` 路由**

替换 `app/agent/runtime.py` 的 `_preflight_confirmation` 方法（约 287-354 行）。保留现有的 `confirmed` 执行分支逻辑（含 prompt_injection 处理），仅调整路由结构。新方法：

```python
    def _preflight_confirmation(
        self, session: SessionState, content: str
    ) -> Optional[str]:
        from app.agent.confirmation import has_competing_signal

        resolution = self._resolver.resolve(content)

        # 干净确认 → 秒级短路执行（现有路径不变）
        if resolution == "confirmed" and not has_competing_signal(content):
            session.confirmation_status = "confirmed"
            session.add_step("preflight_confirmation", resolution="confirmed")
            action = session.pending_action
            injection_pattern_ids = _pending_action_prompt_injection_pattern_ids(
                action.arguments
            )
            if injection_pattern_ids:
                safe_arguments = {
                    key: value
                    for key, value in action.arguments.items()
                    if key != "_prompt_injection_pattern_ids"
                }
                AgentLoop._record_prompt_injection_write_block(
                    session=session,
                    tool_name=action.action_name,
                    arguments=safe_arguments,
                    pattern_ids=injection_pattern_ids,
                )
                session.pending_action = None
                msg = (
                    "I can't continue with that account or order change because "
                    "the request included instruction-bypassing language. Please "
                    "restate the request without those instructions, or I can help "
                    "check the order or transfer you to a human agent."
                )
                session.messages.append(Message(role="assistant", content=msg))
                return msg
            record = self.gateway.execute(
                state=session,
                tool_name=action.action_name,
                arguments={
                    key: value
                    for key, value in action.arguments.items()
                    if key != "_prompt_injection_pattern_ids"
                },
                confirmed=True,
            )
            session.pending_action = None
            if record.status == "success":
                continued = self._continue_after_confirmed_action(session)
                if continued is not None:
                    return continued
                msg = "Done. I have completed the requested update."
            else:
                msg = _map_guard_error_to_user_message(str(record.error))
            session.messages.append(Message(role="assistant", content=msg))
            return msg

        # confirmed + competing → 放行 LLM，pending 保持（NEW）
        if resolution == "confirmed":
            session.add_step(
                "preflight_confirmation_fallback",
                resolution="confirmed_competing",
            )
            return None

        # denied → 丢弃 pending（现有路径不变）
        if resolution == "denied":
            session.confirmation_status = "denied"
            session.pending_action = None
            session.add_step("preflight_confirmation", resolution="denied")
            if has_competing_signal(content):
                # denied + 提问/穿插 → 丢弃后放行 LLM 答问题（NEW）
                return None
            msg = "No changes were made."
            session.messages.append(Message(role="assistant", content=msg))
            return msg

        # changed → 独立分支，逐字节不动（保护 generalized_mvp changed case）
        if resolution == "changed":
            session.confirmation_status = "changed"
            session.pending_action = None
            session.add_step("preflight_confirmation", resolution="changed")
            msg = "I discarded the previous request. Please provide updated details."
            session.messages.append(Message(role="assistant", content=msg))
            return msg

        # unknown → 放行 LLM（现有路径不变）
        return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_preflight_routing.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 跑现有确认相关测试确认不破坏**

Run: `uv run python -m pytest tests/test_agent_core.py -v -k "confirm or change or deny"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/agent/runtime.py tests/test_preflight_routing.py
git commit -m "feat: _preflight_confirmation 路由修正——changed 独立分支 + competing fallback"
```

---

## Task 5: `context_builder` 订单含商品名 + pending 含参数

**Files:**
- Modify: `app/agent/context_builder.py:86-93`（订单行）+ `context_builder.py:115-119`（pending 行）
- Test: `tests/test_context_builder_rich.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_context_builder_rich.py
from __future__ import annotations
from app.agent.context_builder import ContextBuilder
from app.agent.models import SessionState, PendingAction


def test_orders_show_item_names():
    cb = ContextBuilder(policy_text="")
    state = SessionState(session_id="t")
    state.authenticated_user_id = "u1"
    state.loaded_context.orders["#W1"] = {
        "status": "pending",
        "items": [
            {"item_id": "1", "name": "Water Bottle", "price": 10},
            {"item_id": "2", "name": "T-Shirt", "price": 20},
            {"item_id": "3", "name": "Mug", "price": 5},
        ],
    }
    out = cb.build(state)
    assert "[Water Bottle, T-Shirt, Mug]" in out


def test_orders_truncate_to_three_names():
    cb = ContextBuilder(policy_text="")
    state = SessionState(session_id="t")
    state.authenticated_user_id = "u1"
    state.loaded_context.orders["#W1"] = {
        "status": "pending",
        "items": [
            {"item_id": str(i), "name": f"Item{i}", "price": 1} for i in range(5)
        ],
    }
    out = cb.build(state)
    assert "..." in out  # 超过 3 个截断


def test_pending_shows_arguments():
    cb = ContextBuilder(policy_text="")
    state = SessionState(session_id="t")
    state.authenticated_user_id = "u1"
    state.pending_action = PendingAction(
        action_name="cancel_pending_order",
        arguments={"order_id": "#W5918442", "reason": "no longer needed"},
        user_facing_summary="cancel",
    )
    out = cb.build(state)
    assert "order_id=#W5918442" in out
    assert "reason=no longer needed" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_context_builder_rich.py -v`
Expected: FAIL（当前订单行是 `(3 items)`，不含商品名）

- [ ] **Step 3: 改订单行含商品名**

`app/agent/context_builder.py` 的 `build` 方法内，订单行部分（约 86-93 行）替换为：

```python
        if session.loaded_context.orders:
            order_parts = []
            for oid, order in session.loaded_context.orders.items():
                status = order.get("status", "?")
                items = order.get("items", [])
                item_list = [it for it in items if isinstance(it, dict)]
                names = [str(it.get("name", "")) for it in item_list if it.get("name")]
                if len(names) > 3:
                    names = names[:3] + ["..."]
                names_str = "[" + ", ".join(names) + "]" if names else f"({len(item_list)} items)"
                order_parts.append(f"{oid}={status} {names_str}")
            parts.append("Orders: " + ", ".join(order_parts))
```

- [ ] **Step 4: 改 pending 行含参数**

`app/agent/context_builder.py` 的 `build` 方法内，pending 行部分（约 115-119 行）替换为：

```python
        if session.pending_action:
            pa = session.pending_action
            arg_str = ", ".join(f"{k}={v}" for k, v in pa.arguments.items()
                                if not k.startswith("_"))
            arg_part = f"({arg_str})" if arg_str else ""
            parts.append(
                f"Pending: {pa.action_name}{arg_part} — waiting for user confirmation"
            )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_context_builder_rich.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: 跑现有 context_builder 测试确认不破坏**

Run: `uv run python -m pytest tests/test_context_builder.py -v`
Expected: PASS（若已有断言检查旧格式 `(N items)`，需同步更新断言）

- [ ] **Step 7: Commit**

```bash
git add app/agent/context_builder.py tests/test_context_builder_rich.py
git commit -m "feat: context_builder 订单含商品名 + pending 含参数详情"
```

---

## Task 6: `ScreenPop` helper

**Files:**
- Create: `app/agent/screen_pop.py`
- Test: `tests/test_screen_pop.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_screen_pop.py
from __future__ import annotations
from unittest.mock import MagicMock
from app.agent.models import SessionState, ToolCallRecord
from app.agent.screen_pop import ScreenPop


def _mock_gateway(user_obs, orders_obs):
    gw = MagicMock()
    def execute(*, state, tool_name, arguments, confirmed=False):
        if tool_name == "get_user_details":
            return ToolCallRecord(tool_name=tool_name, arguments=arguments,
                                  tool_kind="read", status="success",
                                  observation=user_obs)
        if tool_name == "list_user_orders":
            return ToolCallRecord(tool_name=tool_name, arguments=arguments,
                                  tool_kind="read", status="success",
                                  observation=orders_obs)
        return ToolCallRecord(tool_name=tool_name, arguments=arguments,
                              tool_kind="read", status="error", error="x")
    gw.execute.side_effect = execute
    return gw


def test_screen_pop_sets_identity_and_loads_orders():
    user_obs = {"name": {"first_name": "Sofia"}, "email": "s@example.com"}
    orders_obs = [{"order_id": "#W1", "status": "pending", "items": []}]
    gw = _mock_gateway(user_obs, orders_obs)
    state = SessionState(session_id="t")
    ScreenPop(gw).apply(state, "sofia_rossi_8776")
    assert state.authenticated_user_id == "sofia_rossi_8776"
    assert state.auth_method == "screen_pop"
    assert "sofia_rossi_8776" in state.loaded_context.users
    assert "#W1" in state.loaded_context.orders
    assert any(s.node == "screen_pop" for s in state.steps)


def test_screen_pop_orders_loaded_into_context():
    user_obs = {"name": {}}
    orders_obs = [
        {"order_id": "#W1", "status": "pending",
         "items": [{"item_id": "1", "name": "Bottle", "price": 10}]},
    ]
    gw = _mock_gateway(user_obs, orders_obs)
    state = SessionState(session_id="t")
    ScreenPop(gw).apply(state, "u1")
    assert state.loaded_context.orders["#W1"]["status"] == "pending"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_screen_pop.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'app.agent.screen_pop'`

- [ ] **Step 3: 实现 ScreenPop**

```python
# app/agent/screen_pop.py
from __future__ import annotations

from app.agent.models import SessionState
from app.tools.gateway import ToolGateway


class ScreenPop:
    """会话建立时模拟真实坐席进线：身份即设 + 主动查一次订单。

    身份是渠道带入的（直接设置 authenticated_user_id，无需 tool）；
    订单是进线后主动调 list_user_orders 查一次的显式动作（非自动 pop）。
    """

    def __init__(self, gateway: ToolGateway) -> None:
        self._gateway = gateway

    def apply(self, session: SessionState, customer_id: str) -> None:
        # 步骤1：身份进线即有（渠道带入）
        session.authenticated_user_id = customer_id
        session.auth_method = "screen_pop"

        # 步骤2：客户卡
        user_record = self._gateway.execute(
            state=session, tool_name="get_user_details",
            arguments={"user_id": customer_id},
        )
        if user_record.status == "success" and isinstance(user_record.observation, dict):
            session.loaded_context.users[customer_id] = user_record.observation

        # 步骤3：进线预查一次订单（显式 tool 调用，非自动 pop）
        orders_record = self._gateway.execute(
            state=session, tool_name="list_user_orders",
            arguments={"user_id": customer_id},
        )
        order_count = 0
        if orders_record.status == "success" and isinstance(orders_record.observation, list):
            for order_summary in orders_record.observation:
                if isinstance(order_summary, dict):
                    oid = order_summary.get("order_id")
                    if oid:
                        session.loaded_context.orders[oid] = order_summary
                        order_count += 1

        # 步骤4：记录 trace
        session.add_step(
            "screen_pop",
            user_id=customer_id,
            order_count=order_count,
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_screen_pop.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/agent/screen_pop.py tests/test_screen_pop.py
git commit -m "feat: ScreenPop helper——身份进线即设 + 主动查一次订单"
```

---

## Task 7: screen pop 接入 `run_script` + chat CLI + workbench session

**Files:**
- Modify: `app/agent/runtime.py:129-195`（`run_script`）
- Modify: `app/cli/chat.py:87-128`（`_interactive`）
- Modify: `app/workbench/session.py:162-193`（`_create_runtime_and_state_for`）
- Test: `tests/test_screen_pop.py`（追加集成测试）

- [ ] **Step 1: 写失败测试——run_script 支持 screen pop**

```python
# tests/test_screen_pop.py 追加
def test_run_script_applies_screen_pop(monkeypatch):
    """run_script 收到 screen_pop_user_id 时在首条消息前预载。"""
    from app.agent.runtime import AgentRuntime
    from app.config import AppConfig
    from pathlib import Path
    # 用 mock provider 避免真实 LLM
    runtime = AgentRuntime.__new__(AgentRuntime)
    # 最小桩：跳过完整构造，只测 screen_pop 接入路径
    # 真实验证靠 realistic_conversation eval（Task 9）
    # 此单元测试验证 run_script 签名接受 screen_pop_user_id
    import inspect
    sig = inspect.signature(AgentRuntime.run_script)
    assert "screen_pop_user_id" in sig.parameters
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run python -m pytest tests/test_screen_pop.py::test_run_script_applies_screen_pop -v`
Expected: FAIL（`run_script` 无 `screen_pop_user_id` 参数）

- [ ] **Step 3: `run_script` 加 screen_pop_user_id 参数**

`app/agent/runtime.py` 的 `run_script` 方法签名加参数，方法体首行加 screen pop：

```python
    def run_script(
        self,
        *,
        messages: Iterable[Dict[str, str]],
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        max_turns: int = 20,
        user_simulator_callback: Optional[Callable[[str], Optional[str]]] = None,
        screen_pop_user_id: Optional[str] = None,
    ) -> AgentRunResult:
        self._turn_contexts = []
        run_id = session_id or f"agent-{uuid.uuid4().hex[:12]}"
        session = SessionState(session_id=run_id, task_id=task_id)
        initial_db_hash = self.retail_runtime.db_hash()

        # Screen pop：身份进线即设 + 主动查一次订单（realistic 子集）
        if screen_pop_user_id:
            from app.agent.screen_pop import ScreenPop
            ScreenPop(self.gateway).apply(session, screen_pop_user_id)

        turn = 0
        # ... 现有 while 循环不动
```

- [ ] **Step 4: chat CLI 加 --customer 参数**

`app/cli/chat.py` 的 `chat_main` parser 加参数，`_interactive` 接收并 screen pop：

```python
# chat_main 内 parser 加：
    parser.add_argument("--customer", help="Authenticated user_id for screen pop (demo mode).")
# _interactive 签名加 customer_id，会话建立后：
def _interactive(runtime: AgentRuntime, max_turns: int, json_output: bool, customer_id: Optional[str]) -> int:
    session_id = "interactive"
    state = SessionState(session_id=session_id)
    if customer_id:
        from app.agent.screen_pop import ScreenPop
        ScreenPop(runtime.gateway).apply(state, customer_id)
    initial_db_hash = runtime.retail_runtime.db_hash()
    # ... 现有逻辑不动
```

同步修改 `chat_main` 内对 `_interactive` 的调用，传入 `args.customer`。

- [ ] **Step 5: workbench session demo 模式 screen pop**

`app/workbench/session.py` 的 `_create_runtime_and_state_for` 内，state 创建后加：

```python
        state = SessionState(
            session_id=self.session_id,
            task_id=(selected_case.case_id if selected_case is not None else None),
        )
        # Demo 模式（无 scripted case）：screen pop 预载客户卡
        if selected_case is None and hasattr(self, '_demo_customer_id') and self._demo_customer_id:
            from app.agent.screen_pop import ScreenPop
            ScreenPop(runtime.gateway).apply(state, self._demo_customer_id)
        return runtime, state, runtime.retail_runtime.db_hash()
```

（`_demo_customer_id` 暂由 session 构造时可选传入；本轮 workbench demo 模式默认不设，留作 Phase 2 UI 接入点。）

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run python -m pytest tests/test_screen_pop.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: 跑 workbench session 测试确认不破坏**

Run: `uv run python -m pytest tests/test_workbench_session.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/agent/runtime.py app/cli/chat.py app/workbench/session.py tests/test_screen_pop.py
git commit -m "feat: screen pop 接入 run_script/chat --customer/workbench demo"
```

---

## Task 8: prompt 指代消解启发式 + 打断处理段

**Files:**
- Modify: `prompts/llm_agent_system_v001.md`（Heuristics 段 + Core Contract）
- Test: 人工验证 + realistic eval（Task 9）

- [ ] **Step 1: Core Contract 加打断处理条**

`prompts/llm_agent_system_v001.md` 的 Core Contract 列表末尾（第 11 条后）追加：

```markdown
12. **Handle interruptions during pending confirmation** — if a write action is pending confirmation and the user's response is mixed (e.g., confirms but also asks a question, or wants to change a detail), address both parts: handle the question or modification, then re-ask for clean confirmation. Do not discard the pending action unless the user clearly denies it.
```

- [ ] **Step 2: Heuristics 段扩展指代消解**

`prompts/llm_agent_system_v001.md` 的 Heuristics 段，在现有 "Recent order inference" 后追加：

```markdown
- **Order list lookup** — if the user refers to an order without an ID ("my pending order", "the one that hasn't arrived"), call `list_user_orders` to see their orders and match by status, recency, or item name. If exactly one order matches, use it; if multiple match, list them briefly and ask which one.
- **Status reference** — "没到的"/"the one that hasn't arrived" → match pending orders. "退了的"/"returned" → match by return history.
- **Attribute reference** — "蓝衬衫"/"the blue shirt" → match by item name in loaded orders.
- **Discourse anaphora** — "刚说的那个"/"that one" → use the most recently referenced order.
```

- [ ] **Step 3: 跑 generalized_mvp 确认 prompt 改动不回归（关键验证点）**

Run: `uv run phase2-eval --subset generalized_mvp --live --max-workers 50`
Expected: pass_rate = 1.0（若 <1.0，bisect：先回退 prompt 再跑，确认是否 prompt 导致）

- [ ] **Step 4: Commit**

```bash
git add prompts/llm_agent_system_v001.md
git commit -m "feat: prompt 指代消解启发式 + 打断处理段"
```

---

## Task 9: realistic_conversation eval 子集 + 行为 rubric

**Files:**
- Modify: `app/eval/cases.py`（EvalCase 字段 + REALISTIC_CONVERSATION_CASES + get_cases 分支）
- Modify: `app/eval/runner.py`（screen pop 预载 + evaluate_behaviors）
- Test: `tests/test_eval_runner.py`（追加）

- [ ] **Step 1: EvalCase 加字段**

`app/eval/cases.py` 的 `EvalCase` dataclass 加两个字段（在现有字段末尾、`skill_id` 后）：

```python
    # ── Phase 1a: screen pop + 行为 rubric ──
    screen_pop_user_id: Optional[str] = None
    expected_behaviors: set = field(default_factory=set)
```

- [ ] **Step 2: 写 realistic_conversation case 子集**

`app/eval/cases.py` 新增 case 列表（先放 3 个代表 case，后续可扩到 12-15）：

```python
REALISTIC_CONVERSATION_CASES: List[EvalCase] = [
    EvalCase(
        case_id="rc_screen_pop_cancel",
        category="realistic_cancel",
        subset="realistic_conversation",
        screen_pop_user_id="sofia_rossi_8776",
        messages=[
            {"role": "user", "content": "帮我取消那个没发货的订单"},
            {"role": "user", "content": "对，不想要了"},
            {"role": "user", "content": "确认"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="cancel_order",
        order_id="#W5918442",
        expected_order_status="cancelled",
        expected_confirmation_status="confirmed",
        required_tools={"cancel_pending_order"},
        expected_behaviors={"screen_pop_preloaded", "reference_resolved"},
    ),
    EvalCase(
        case_id="rc_screen_pop_lookup",
        category="realistic_lookup",
        subset="realistic_conversation",
        screen_pop_user_id="sofia_rossi_8776",
        messages=[
            {"role": "user", "content": "我那个已经到的单子状态怎么样了"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="lookup",
        order_id="#W4817420",
        expected_order_status="delivered",
        expected_assistant_contains="delivered",
        expected_behaviors={"screen_pop_preloaded", "reference_resolved"},
    ),
    EvalCase(
        case_id="rc_interruption_confirm_with_question",
        category="realistic_interruption",
        subset="realistic_conversation",
        screen_pop_user_id="sofia_rossi_8776",
        messages=[
            {"role": "user", "content": "取消 #W5918442 吧，不想要了"},
            {"role": "user", "content": "确认，退款能退多少？"},
            {"role": "user", "content": "确认"},
        ],
        expected_user_id="sofia_rossi_8776",
        expected_intent="cancel_order",
        order_id="#W5918442",
        expected_order_status="cancelled",
        expected_confirmation_status="confirmed",
        required_tools={"cancel_pending_order"},
        expected_behaviors={"interruption_handled", "no_stale_pending"},
    ),
]
```

- [ ] **Step 3: get_cases 加分支**

`app/eval/cases.py` 的 `get_cases` 函数加分支：

```python
    if subset == "realistic_conversation":
        return list(REALISTIC_CONVERSATION_CASES)
```

- [ ] **Step 4: runner screen pop 预载**

`app/eval/runner.py` 的 `_run_case` 内，`runtime.run_script` 调用处加 `screen_pop_user_id`：

```python
        run_result = runtime.run_script(
            messages=run_messages,
            session_id=session_id,
            task_id=case.case_id,
            max_turns=case.max_turns,
            user_simulator_callback=user_simulator_callback,
            screen_pop_user_id=getattr(case, "screen_pop_user_id", None),
        )
```

- [ ] **Step 5: 实现 evaluate_behaviors 纯函数**

`app/eval/runner.py` 新增函数：

```python
def evaluate_behaviors(
    case: EvalCase,
    state: SessionState,
) -> List[str]:
    """返回未满足的 behavior key 列表（空 = 全满足）。"""
    failed: List[str] = []
    expected = case.expected_behaviors
    steps = state.steps

    if "screen_pop_preloaded" in expected:
        has_screen_pop = any(s.node == "screen_pop" for s in steps)
        if not has_screen_pop:
            failed.append("screen_pop_preloaded")

    if "reference_resolved" in expected:
        # 用户原话没显式给 #W 订单号，但 write 成功了 → 指代被消解
        user_gave_explicit_order = any(
            ORDER_RE.search(m.get("content", "")) for m in case.messages
        )
        write_succeeded = any(
            getattr(r, "tool_kind", "") == "write" and r.status == "success"
            for r in state.tool_results
        )
        # lookup 类 case 无 write，用 assistant 回复含状态判定
        lookup_ok = case.expected_assistant_contains and any(
            case.expected_assistant_contains.lower() in msg.content.lower()
            for msg in state.messages if msg.role == "assistant"
        )
        if (user_gave_explicit_order or not (write_succeeded or lookup_ok)):
            failed.append("reference_resolved")

    if "interruption_handled" in expected:
        has_fallback = any(
            s.node == "preflight_confirmation_fallback" for s in steps
        )
        if not has_fallback or state.confirmation_status != "confirmed":
            failed.append("interruption_handled")

    if "no_stale_pending" in expected and state.pending_action is not None:
        failed.append("no_stale_pending")

    return failed
```

- [ ] **Step 6: _run_case 末尾并入 behavior 失败**

`app/eval/runner.py` 的 `_run_case` 内，`failure_label = classify_failure(...)` 之后追加：

```python
        behavior_failures = evaluate_behaviors(case, state)
        if behavior_failures and failure_label is None:
            failure_label = f"behavior_unmet:{','.join(behavior_failures)}"
```

- [ ] **Step 7: 写单元测试——evaluate_behaviors**

```python
# tests/test_eval_runner.py 追加
from app.eval.runner import evaluate_behaviors
from app.eval.cases import EvalCase
from app.agent.models import SessionState, AgentStep


def test_evaluate_behaviors_screen_pop_missing():
    case = EvalCase(case_id="x", category="c", messages=[],
                    expected_user_id="u", expected_intent="i",
                    expected_behaviors={"screen_pop_preloaded"})
    state = SessionState(session_id="t")
    # 无 screen_pop step
    assert "screen_pop_preloaded" in evaluate_behaviors(case, state)


def test_evaluate_behaviors_screen_pop_present():
    case = EvalCase(case_id="x", category="c", messages=[],
                    expected_user_id="u", expected_intent="i",
                    expected_behaviors={"screen_pop_preloaded"})
    state = SessionState(session_id="t")
    state.add_step("screen_pop", user_id="u", order_count=1)
    assert evaluate_behaviors(case, state) == []


def test_evaluate_behaviors_no_stale_pending():
    from app.agent.models import PendingAction
    case = EvalCase(case_id="x", category="c", messages=[],
                    expected_user_id="u", expected_intent="i",
                    expected_behaviors={"no_stale_pending"})
    state = SessionState(session_id="t")
    state.pending_action = PendingAction(action_name="x", arguments={},
                                         user_facing_summary="x")
    assert "no_stale_pending" in evaluate_behaviors(case, state)
```

- [ ] **Step 8: 跑单元测试确认通过**

Run: `uv run python -m pytest tests/test_eval_runner.py -v -k "evaluate_behaviors"`
Expected: PASS (3 passed)

- [ ] **Step 9: 跑 realistic_conversation live eval**

Run: `uv run phase2-eval --subset realistic_conversation --live --max-workers 10`
Expected: 初始基线记录（允许 <100%，逐 case 攻坚）

- [ ] **Step 10: Commit**

```bash
git add app/eval/cases.py app/eval/runner.py tests/test_eval_runner.py
git commit -m "feat: realistic_conversation eval 子集 + 行为 rubric"
```

---

## Task 10: 全量回归 + 基线确认

- [ ] **Step 1: 跑全量单元测试**

Run: `uv run python -m pytest tests/ -v`
Expected: 全 PASS（含新增 5 个测试文件）

- [ ] **Step 2: 跑 generalized_mvp 基线（关键验证点）**

Run: `uv run phase2-eval --subset generalized_mvp --live --max-workers 50`
Expected: pass_rate = 1.0。若 <1.0：bisect——`git stash` 逐个回退 Task 8(prompt)/Task 5(context_builder)/Task 4(routing) 定位扰动源。

- [ ] **Step 3: 跑 curated_mvp 基线**

Run: `uv run phase2-eval --subset curated_mvp --live --max-workers 50`
Expected: pass_rate = 1.0

- [ ] **Step 4: 跑 golden 回归**

Run: `uv run flywheel check --no-progress --json`
Expected: 无回归

- [ ] **Step 5: 手动 demo 验证三件套**

Run: `uv run phase1-chat --interactive --customer sofia_rossi_8776`
- 输入"帮我取消那个没发货的订单" → 验证 screen pop 已认识客户 + 指代消解
- 输入"对，不想要了" → 验证确认流程
- 输入"确认" → 验证执行
Expected: 三件套交互流跑通

- [ ] **Step 6: 最终 Commit**

```bash
git add -A
git commit -m "test: Phase 1a 全量回归 + 基线确认通过"
```

---

## Self-Review

**1. Spec 覆盖：**
- §1 screen pop（身份进线即设 + 订单预查）→ Task 6 (ScreenPop) + Task 7 (接入) ✓
- §2 指代消解（list_user_orders + context 商品名 + prompt 启发式）→ Task 1-2 (tool) + Task 5 (context) + Task 8 (prompt) ✓
- §3 打断穿插（has_competing_signal + 路由修正 + prompt）→ Task 3 (函数) + Task 4 (路由) + Task 8 (prompt) ✓
- §4 测试策略（单元 + realistic 子集 + 行为 rubric + 基线保护）→ Task 1-7 (单元) + Task 9 (eval) + Task 10 (基线) ✓

**2. 占位符扫描：** 无 TBD/TODO。Task 9 case 数量标注"先 3 个，后续可扩到 12-15"是合理的渐进，非占位符。

**3. 类型一致性：** `has_competing_signal(text: str) -> bool`（Task 3 定义，Task 4 引用）✓；`ScreenPop(gateway).apply(session, customer_id)`（Task 6 定义，Task 7 引用）✓；`evaluate_behaviors(case, state) -> List[str]`（Task 9 定义并引用）✓；`screen_pop_user_id`（EvalCase Task 9 定义，runner Task 9 引用）✓。
