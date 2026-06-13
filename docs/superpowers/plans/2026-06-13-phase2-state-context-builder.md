# Phase 2：State 拆分与 Context Builder 实现计划

> **给 agentic workers：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐步执行本计划。步骤使用 checkbox（`- [ ]`）语法跟踪进度。

**目标：** 新增 `SessionState`（跨轮持久）+ `TurnContext`（单轮临时）模型，新增 `ContextBuilder` 构建 LLM-visible state summary。`ConversationState` 完全不碰，Phase 4 一刀切。

**架构：** `SessionState` 和 `TurnContext` 是独立 Pydantic model，目前没有任何消费者。`ContextBuilder` 是第一个消费者。Phase 3 的 LLM agent loop 将使用它们。Phase 4 删除 `ConversationState` + pipeline + graph + plan_handlers，runtime 切到新模型。

**技术栈：** Python、项目现有 Pydantic 兼容层、pytest。

---

## 来源文档

- 主 spec：`docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md`
- 主计划：`docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md`

---

## 文件结构

```
app/agent/
  models.py              ← 新增 SessionState、TurnContext
  context_builder.py     ← 新增

tests/
  test_session_state.py      ← 新增：模型测试
  test_context_builder.py    ← 新增：ContextBuilder 测试
```

**不修改的文件：** `ConversationState`、`runtime.py`、`pipeline.py`、`guard.py`、`gateway.py`、`tracing.py`、`eval/` — 全部保持不动。Phase 4 一次性切换。

---

## 实现任务

### Task 1：新增 SessionState 和 TurnContext 模型

**文件：**
- 修改：`app/agent/models.py`
- 新增：`tests/test_session_state.py`

- [ ] **Step 1：编写测试**

创建 `tests/test_session_state.py`：

```python
from __future__ import annotations

from app.agent.models import (
    LoadedContext,
    Message,
    PendingAction,
    SessionState,
    ToolCallRecord,
    TurnContext,
)


def test_session_state_minimal_construction() -> None:
    session = SessionState(session_id="sess-1")
    assert session.session_id == "sess-1"
    assert session.task_id is None
    assert session.authenticated_user_id is None
    assert session.messages == []
    assert isinstance(session.loaded_context, LoadedContext)
    assert session.tool_results == []
    assert session.write_locks == []
    assert session.audit_logs == []
    assert session.pending_action is None


def test_session_state_holds_accumulated_data() -> None:
    session = SessionState(
        session_id="sess-2",
        authenticated_user_id="U1",
        auth_method="email",
        active_user_identity={"name": "Test User", "email": "test@example.com"},
    )
    session.messages.append(Message(role="user", content="hello"))
    session.tool_results.append(
        ToolCallRecord(
            tool_name="get_order_details",
            arguments={"order_id": "O1"},
            tool_kind="read",
            status="success",
        )
    )
    session.write_locks.append("order_O1_write_lock")
    session.pending_action = PendingAction(
        action_name="cancel_pending_order",
        arguments={"order_id": "O1", "reason": "no longer needed"},
        user_facing_summary="Cancel order O1",
    )
    assert len(session.messages) == 1
    assert len(session.tool_results) == 1
    assert session.pending_action.action_name == "cancel_pending_order"


def test_turn_context_defaults() -> None:
    turn = TurnContext()
    assert turn.steps == []
    assert turn.step_durations == {}
    assert turn.llm_call_durations == []
    assert turn.llm_token_usage is None
    assert turn.loop_iterations == 0
    assert turn.consecutive_tool_failures == 0
    assert turn.termination is None


def test_turn_context_records_loop_metadata() -> None:
    turn = TurnContext(
        step_durations={"identity_resolver": 45.2},
        llm_call_durations=[
            {"node": "policy_reasoner", "call_type": "json", "duration_ms": 185.2, "status": "ok"},
        ],
        llm_token_usage={"prompt_tokens": 500, "completion_tokens": 80, "total_tokens": 580},
        loop_iterations=3,
        termination="final_response",
    )
    assert turn.step_durations["identity_resolver"] == 45.2
    assert turn.llm_token_usage["total_tokens"] == 580
    assert turn.loop_iterations == 3


def test_session_state_roundtrip() -> None:
    session = SessionState(
        session_id="sess-3",
        authenticated_user_id="U2",
        auth_method="name_zip",
    )
    session.messages.append(Message(role="user", content="track my order"))
    session.loaded_context.orders["O1"] = {"order_id": "O1", "status": "pending"}

    data = session.model_dump()
    restored = SessionState.model_validate(data)

    assert restored.session_id == "sess-3"
    assert restored.authenticated_user_id == "U2"
    assert restored.loaded_context.orders["O1"]["status"] == "pending"


def test_turn_context_roundtrip() -> None:
    turn = TurnContext(
        step_durations={"response_generator": 0.5},
        loop_iterations=2,
        termination="final_response",
    )
    data = turn.model_dump()
    restored = TurnContext.model_validate(data)
    assert restored.step_durations == {"response_generator": 0.5}
    assert restored.loop_iterations == 2


def test_session_and_turn_are_independent() -> None:
    """两个模型互不包含对方字段。"""
    session = SessionState(session_id="sess-4")
    turn = TurnContext()
    assert not hasattr(session, "steps")
    assert not hasattr(session, "loop_iterations")
    assert not hasattr(turn, "session_id")
    assert not hasattr(turn, "authenticated_user_id")
```

- [ ] **Step 2：运行测试，确认失败**

```bash
uv run python -m pytest tests/test_session_state.py -q
```

预期：`ImportError: cannot import name 'SessionState'`

- [ ] **Step 3：新增模型**

在 `app/agent/models.py` 的 `ConversationState` 之前插入：

```python
class SessionState(BaseModel):
    """Cross-turn persistent state.

    Replaces ConversationState's session-level fields. Phase 4 will make
    this the primary state object when the old pipeline is removed.
    """
    session_id: str
    task_id: Optional[str] = None
    authenticated_user_id: Optional[str] = None
    auth_method: Optional[str] = None
    active_user_identity: Dict[str, Any] = Field(default_factory=dict)
    messages: List[Message] = Field(default_factory=list)
    loaded_context: LoadedContext = Field(default_factory=LoadedContext)
    tool_results: List[ToolCallRecord] = Field(default_factory=list)
    write_locks: List[str] = Field(default_factory=list)
    audit_logs: List[Dict[str, Any]] = Field(default_factory=list)
    pending_action: Optional[PendingAction] = None
    termination_reason: Optional[str] = None


class TurnContext(BaseModel):
    """Single-turn ephemeral bookkeeping.

    Recorded in trace artifacts but not persisted across turns.
    Phase 3's LLM agent loop will populate this.
    """
    steps: List[AgentStep] = Field(default_factory=list)
    step_durations: dict[str, float] = Field(default_factory=dict)
    llm_call_durations: list[dict] = Field(default_factory=list)
    llm_token_usage: Optional[Dict[str, Any]] = None
    loop_iterations: int = 0
    consecutive_tool_failures: int = 0
    termination: Optional[str] = None
```

- [ ] **Step 4：运行测试**

```bash
uv run python -m pytest tests/test_session_state.py -q
```

预期：7 passed.

- [ ] **Step 5：运行全量回归确认零影响**

```bash
uv run python -m pytest tests/ -q
```

预期：243 existing + 7 new = 250 passed.

- [ ] **Step 6：Lint + 提交**

```bash
uv run ruff check app/agent/models.py tests/test_session_state.py
git add app/agent/models.py tests/test_session_state.py
git commit -m "feat: add SessionState and TurnContext models"
```

---

### Task 2：新增 ContextBuilder

**文件：**
- 新增：`app/agent/context_builder.py`
- 新增：`tests/test_context_builder.py`

- [ ] **Step 1：编写测试**

创建 `tests/test_context_builder.py`：

```python
from __future__ import annotations

from app.agent.context_builder import ContextBuilder
from app.agent.models import Message, PendingAction, SessionState, ToolCallRecord


def _session() -> SessionState:
    session = SessionState(
        session_id="ctx-1",
        authenticated_user_id="U1",
        auth_method="email",
        active_user_identity={
            "user_id": "U1",
            "name": "Alice Smith",
            "email": "alice@example.com",
        },
    )
    session.messages = [
        Message(role="user", content="I need help with my order"),
        Message(role="assistant", content="Let me look up your order."),
    ]
    session.loaded_context.orders["O1"] = {
        "order_id": "O1", "user_id": "U1", "status": "pending",
        "items": [{"item_id": "I1", "name": "Widget"}, {"item_id": "I2", "name": "Gadget"}],
    }
    session.loaded_context.orders["O2"] = {
        "order_id": "O2", "user_id": "U1", "status": "delivered",
        "items": [{"item_id": "I3", "name": "Thing"}],
    }
    session.tool_results = [
        ToolCallRecord(
            tool_name="get_order_details", arguments={"order_id": "O1"},
            tool_kind="read", status="success",
            observation={"order_id": "O1", "status": "pending", "item_count": 2},
        ),
    ]
    return session


def test_build_includes_auth_summary() -> None:
    summary = ContextBuilder(policy_text="dummy").build(_session())
    assert "Alice Smith" in summary
    assert "U1" in summary
    assert "example.com" in summary


def test_build_includes_order_summaries() -> None:
    summary = ContextBuilder(policy_text="dummy").build(_session())
    assert "O1" in summary
    assert "pending" in summary
    assert "O2" in summary
    assert "delivered" in summary


def test_build_marks_writable_orders() -> None:
    summary = ContextBuilder(policy_text="dummy").build(_session())
    assert "[writable]" in summary


def test_build_includes_pending_action() -> None:
    session = _session()
    session.pending_action = PendingAction(
        action_name="cancel_pending_order",
        arguments={"order_id": "O1", "reason": "no longer needed"},
        user_facing_summary="Cancel order O1",
    )
    summary = ContextBuilder(policy_text="dummy").build(session)
    assert "cancel_pending_order" in summary


def test_build_includes_write_locks() -> None:
    session = _session()
    session.write_locks = ["order_O1_write_lock"]
    summary = ContextBuilder(policy_text="dummy").build(session)
    assert "order_O1_write_lock" in summary


def test_build_handles_unauthenticated_user() -> None:
    session = SessionState(session_id="ctx-2")
    summary = ContextBuilder(policy_text="dummy").build(session)
    assert "not authenticated" in summary.lower()


def test_build_handles_empty_state() -> None:
    session = SessionState(session_id="ctx-3")
    summary = ContextBuilder(policy_text="dummy").build(session)
    assert len(summary) > 0


def test_estimate_tokens_is_reasonable() -> None:
    builder = ContextBuilder(policy_text="dummy")
    summary = builder.build(_session())
    tokens = builder.estimate_tokens(summary)
    assert isinstance(tokens, int)
    assert 0 < tokens < 2000


def test_recent_messages_limited_to_last_six() -> None:
    session = _session()
    for i in range(10):
        session.messages.append(Message(role="user", content=f"msg {i}"))
    summary = ContextBuilder(policy_text="dummy").build(session)
    assert "msg 0" not in summary
    assert "msg 3" not in summary
    assert "msg 8" in summary
```

- [ ] **Step 2：运行测试，确认失败**

```bash
uv run python -m pytest tests/test_context_builder.py -q
```

预期：`ModuleNotFoundError: No module named 'app.agent.context_builder'`

- [ ] **Step 3：实现 ContextBuilder**

创建 `app/agent/context_builder.py`：

```python
from __future__ import annotations

from typing import Any

from app.agent.models import SessionState


class ContextBuilder:
    """Builds a compressed LLM-visible state summary from SessionState.

    Target budget: ~1200 tokens. Provides the LLM with context needed for
    tool-calling decisions without overwhelming the prompt with raw DB objects.
    """

    def __init__(self, *, policy_text: str, max_recent_messages: int = 6) -> None:
        self._policy_text = policy_text
        self._max_recent_messages = max_recent_messages

    def build(self, session: SessionState) -> str:
        parts: list[str] = [self._auth_summary(session)]
        if session.loaded_context.orders:
            parts.append(self._orders_summary(session))
        if session.pending_action:
            parts.append(self._pending_summary(session))
        if session.write_locks:
            parts.append(self._locks_summary(session))
        if session.tool_results:
            parts.append(self._tool_results_summary(session))
        if session.messages:
            parts.append(self._messages_summary(session))
        parts.append(self._policy_summary())
        return "\n\n".join(parts)

    def estimate_tokens(self, text: str) -> int:
        return max(1, int(len(text.split()) / 0.75))

    def _auth_summary(self, session: SessionState) -> str:
        if not session.authenticated_user_id:
            return "## Session\nUser: not authenticated"
        identity = session.active_user_identity
        name = identity.get("name", "Unknown")
        email = str(identity.get("email", ""))
        lines = [
            "## Session",
            f"User: {name} (ID: {session.authenticated_user_id})",
            f"Auth: {session.auth_method or 'unknown'}",
        ]
        if email and "@" in email:
            lines.append(f"Email domain: {email.split('@')[1]}")
        return "\n".join(lines)

    def _orders_summary(self, session: SessionState) -> str:
        lines = ["## Loaded Orders"]
        for oid, order in session.loaded_context.orders.items():
            status = order.get("status", "unknown")
            items = order.get("items", [])
            count = len(items) if isinstance(items, list) else 0
            owner = order.get("user_id", "")
            flags = ""
            if status == "pending" and owner == session.authenticated_user_id:
                flags = " [writable]"
            lines.append(f"- {oid}: {status}, {count} items{flags}")
        return "\n".join(lines)

    def _pending_summary(self, session: SessionState) -> str:
        pa = session.pending_action
        return (
            "## Pending Action\n"
            f"Action: {pa.action_name}\n"
            f"Arguments: {self._brief_args(pa.arguments)}\n"
            f"Summary: {pa.user_facing_summary}"
        )

    def _locks_summary(self, session: SessionState) -> str:
        return "## Write Locks\n" + "\n".join(f"- {l}" for l in session.write_locks)

    def _tool_results_summary(self, session: SessionState) -> str:
        recent = session.tool_results[-3:]
        lines = ["## Recent Tool Calls"]
        for r in recent:
            obs = self._summarize_observation(r.observation)
            lines.append(f"- {r.tool_name}: {r.status} — {obs}")
        return "\n".join(lines)

    def _messages_summary(self, session: SessionState) -> str:
        recent = session.messages[-self._max_recent_messages :]
        lines = ["## Recent Messages"]
        for msg in recent:
            lines.append(f"- [{msg.role}] {msg.content[:200]}")
        return "\n".join(lines)

    def _policy_summary(self) -> str:
        return f"## Policy\n{self._policy_text[:500].strip()}"

    @staticmethod
    def _brief_args(args: dict[str, Any]) -> str:
        parts = []
        for k, v in args.items():
            s = str(v)
            parts.append(f"{k}={s[:37] + '...' if len(s) > 40 else s}")
        return ", ".join(parts)

    @staticmethod
    def _summarize_observation(obs: Any) -> str:
        if obs is None:
            return "(none)"
        if isinstance(obs, dict):
            fields = []
            for f in ("order_id", "status", "user_id", "item_count", "name", "email"):
                if f in obs:
                    fields.append(f"{f}={obs[f]}")
            return ", ".join(fields[:4]) if fields else f"dict({len(obs)} keys)"
        if isinstance(obs, list):
            return f"list({len(obs)} items)"
        s = str(obs)
        return s[:77] + "..." if len(s) > 80 else s
```

- [ ] **Step 4：运行测试**

```bash
uv run python -m pytest tests/test_context_builder.py -q
```

预期：9 passed.

- [ ] **Step 5：Lint + 提交**

```bash
uv run ruff check app/agent/context_builder.py tests/test_context_builder.py
git add app/agent/context_builder.py tests/test_context_builder.py
git commit -m "feat: add ContextBuilder for LLM-visible state summary"
```

---

### Task 3：Phase 2 回归检查

- [ ] **Step 1：运行 focused tests**

```bash
uv run python -m pytest tests/test_session_state.py tests/test_context_builder.py -q
```

预期：16 passed.

- [ ] **Step 2：运行全量测试**

```bash
uv run python -m pytest tests/ -q
```

预期：243 existing + 16 new = 259 passed.

- [ ] **Step 3：Lint**

```bash
uv run ruff check .
```

- [ ] **Step 4：验证 eval**

```bash
uv run phase2-eval --subset curated_mvp --trials 1
```

- [ ] **Step 5：更新主计划文档**

在 `docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md` 追加：

```markdown
- Phase 2：✅ 完成 — SessionState/TurnContext 模型、ContextBuilder（2026-06-13）。
```

- [ ] **Step 6：提交**

```bash
git add docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md
git commit -m "docs: mark LLM tool-calling phase 2 complete"
```

---

## 设计决策记录

**为什么不给 ConversationState 加转换方法？**
ConversationState 在 Phase 4 会被整个删除（连同 pipeline/graph/plan_handlers）。给它加 `to_session_state()` / `from_session_state()` 是多余的 — 就像给要拆的房子装修。Phase 4 一刀切，runtime 直接用 SessionState。

**为什么 trace 也不改？**
TraceWriter 当前序列化 ConversationState。Phase 4 切到 SessionState 后自然会序列化新模型。现在改 trace 加独立字段也是多此一举。

**Phase 2 的真正价值：** 把 Phase 3 （LLM agent loop）需要的数据结构提前定义好。ContextBuilder 是第一块真正使用新模型的积木。

---

## 退出条件

```bash
uv run python -m pytest tests/ -q   # 259 tests passed
uv run ruff check .                  # 零警告
uv run phase2-eval --subset curated_mvp --trials 1  # 结果一致
```

---

## Phase 3 预览

基于 SessionState + TurnContext + ContextBuilder + Phase 1 的 provider/harness，实现：
- `app/agent/llm_agent.py` — LLM agent loop
- `step_llm_reason`, `step_tool_execute`, `step_pending`, `step_finalize`
- max iteration guard, consecutive failure guard
- structured tool observations

动代码前基于 Phase 2 完成后状态重新生成专用计划。
