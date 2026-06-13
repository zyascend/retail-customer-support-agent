# Phase 2：State 拆分与 Context Builder 实现计划

> **给 agentic workers：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐步执行本计划。步骤使用 checkbox（`- [ ]`）语法跟踪进度。

**目标：** 新增 `SessionState`（跨轮持久）+ `TurnContext`（单轮临时）模型，在 `ConversationState` 上添加转换方法，新增 `ContextBuilder` 构建 LLM-visible state summary，更新 trace 记录独立视图。现有 runtime 完全不受影响。

**架构：** Phase 2 不修改 `ConversationState` 现有字段，只在其上添加 `to_session_state()` / `from_session_state()` 转换方法。新代码（ContextBuilder、Phase 3 的 LLM agent loop）使用新模型；旧代码（pipeline、runtime、guard、gateway、eval）继续使用 `ConversationState` 不变。新增 `ContextBuilder` 为 Phase 3 做准备。

**技术栈：** Python、项目现有 Pydantic 兼容层（`app/pydantic_compat.py`）、pytest。

---

## 来源文档

- 主 spec：`docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md`
- 主计划：`docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md`

---

## 设计决策

### 策略：新增而非替换

Phase 2 不修改 `ConversationState` 现有字段和行为。而是：

1. 新增 `SessionState` 和 `TurnContext` 作为独立 Pydantic model
2. 在 `ConversationState` 上添加 `to_session_state()` 方法（浅拷贝到新模型）
3. 在 `ConversationState` 上添加 `from_session_state()` classmethod（从新模型构造）
4. `ContextBuilder` 接收 `SessionState`（为 Phase 3 做准备）
5. `TraceWriter` 追加 `session_state` / `turn_context` 独立字段

现有代码零改动，零风险。

### ContextBuilder 设计

接收 `SessionState` + policy 文本，构建压缩的 LLM-visible state summary。

摘要顺序：
1. Auth summary — user name, ID, auth method, email domain
2. Loaded orders — order_id, status, item count, writable flag
3. Pending action — action name, args, user-facing summary
4. Write locks — acquired resource locks
5. Recent tool results — last 3 tool calls with observation summaries
6. Recent messages — last 6 user/assistant messages (truncated)
7. Policy excerpt — first 500 chars

---

## 文件结构

```
app/agent/
  models.py              ← 新增 SessionState、TurnContext；ConversationState 添加转换方法
  context_builder.py     ← 新增：构建 LLM-visible state summary

app/ops/
  tracing.py             ← 修改：追加 session_state/turn_context 到 trace

tests/
  test_session_state.py           ← 新增：模型测试（6 tests）
  test_state_conversion.py        ← 新增：ConversationState ↔ SessionState 转换测试（7 tests）
  test_context_builder.py         ← 新增：ContextBuilder 行为测试（11 tests）
```

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
    assert session.auth_method is None
    assert session.active_user_identity == {}
    assert session.messages == []
    assert isinstance(session.loaded_context, LoadedContext)
    assert session.tool_results == []
    assert session.write_locks == []
    assert session.audit_logs == []
    assert session.pending_action is None
    assert session.termination_reason is None


def test_session_state_holds_accumulated_data() -> None:
    session = SessionState(
        session_id="sess-2",
        task_id="task-1",
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
    session.audit_logs.append({"event": "order_looked_up"})
    session.pending_action = PendingAction(
        action_name="cancel_pending_order",
        arguments={"order_id": "O1", "reason": "no longer needed"},
        user_facing_summary="Cancel order O1",
    )

    assert len(session.messages) == 1
    assert len(session.tool_results) == 1
    assert len(session.write_locks) == 1
    assert len(session.audit_logs) == 1
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


def test_turn_context_records_timing() -> None:
    turn = TurnContext(
        step_durations={"identity_resolver": 45.2, "context_loader": 12.1},
        llm_call_durations=[
            {"node": "policy_reasoner", "call_type": "json", "duration_ms": 185.2, "status": "ok"},
        ],
        llm_token_usage={"prompt_tokens": 500, "completion_tokens": 80, "total_tokens": 580},
    )

    assert turn.step_durations["identity_resolver"] == 45.2
    assert len(turn.llm_call_durations) == 1
    assert turn.llm_token_usage["total_tokens"] == 580


def test_session_state_serialization_roundtrip() -> None:
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
    assert len(restored.messages) == 1
    assert restored.loaded_context.orders["O1"]["status"] == "pending"


def test_turn_context_serialization_roundtrip() -> None:
    turn = TurnContext(
        step_durations={"response_generator": 0.5},
        loop_iterations=2,
        termination="final_response",
    )

    data = turn.model_dump()
    restored = TurnContext.model_validate(data)

    assert restored.step_durations == {"response_generator": 0.5}
    assert restored.loop_iterations == 2
    assert restored.termination == "final_response"
```

- [ ] **Step 2：运行测试，确认失败**

```bash
uv run python -m pytest tests/test_session_state.py -q
```

预期：`ImportError: cannot import name 'SessionState'`

- [ ] **Step 3：新增模型**

在 `app/agent/models.py` 中，在 `ConversationState` 之前插入：

```python
class SessionState(BaseModel):
    """Cross-turn persistent state. Serializable, survives across turns.

    This is the Phase 2-4 target model. In Phase 2-3 it coexists with
    ConversationState; in Phase 4 ConversationState will be removed.
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
    """Single-turn ephemeral state. Recorded in trace, not persisted across turns.

    This is the Phase 3-4 target model for per-turn bookkeeping.
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

预期：6 passed.

- [ ] **Step 5：Lint**

```bash
uv run ruff check app/agent/models.py tests/test_session_state.py
```

- [ ] **Step 6：提交**

```bash
git add app/agent/models.py tests/test_session_state.py
git commit -m "feat: add SessionState and TurnContext models"
```

---

### Task 2：ConversationState 转换方法

**文件：**
- 修改：`app/agent/models.py`
- 新增：`tests/test_state_conversion.py`

**设计：** 在 `ConversationState` 类上添加两个方法，不修改现有字段：

```python
def to_session_state(self) -> SessionState:
    """Extract a SessionState snapshot from this ConversationState."""
    ...

@classmethod
def from_session_state(
    cls, session: SessionState, turn: Optional[TurnContext] = None
) -> ConversationState:
    """Construct a ConversationState from SessionState + optional TurnContext."""
    ...
```

- [ ] **Step 1：编写转换测试**

创建 `tests/test_state_conversion.py`：

```python
from __future__ import annotations

from app.agent.models import (
    ConversationState,
    Message,
    PendingAction,
    SessionState,
    ToolCallRecord,
    TurnContext,
)


def test_to_session_state_copies_core_fields() -> None:
    """to_session_state() 提取核心跨轮字段。"""
    state = ConversationState(
        session_id="cs-1",
        task_id="task-1",
        current_intent="cancel_order",
        slots={"order_id": "O1"},
        confirmation_status="not_required",
        risk_level="medium",
    )
    state.authenticated_user_id = "U1"
    state.auth_method = "email"
    state.active_user_identity = {"name": "Alice", "email": "alice@example.com"}
    state.messages.append(Message(role="user", content="cancel my order"))
    state.tool_results.append(
        ToolCallRecord(
            tool_name="get_order_details",
            arguments={"order_id": "O1"},
            tool_kind="read",
            status="success",
        )
    )
    state.write_locks.append("lock_1")
    state.audit_logs.append({"event": "auth"})
    state.pending_action = PendingAction(
        action_name="cancel_pending_order",
        arguments={"order_id": "O1"},
        user_facing_summary="Cancel O1",
    )
    state.termination_reason = "user_confirmed"

    session = state.to_session_state()

    assert isinstance(session, SessionState)
    assert session.session_id == "cs-1"
    assert session.task_id == "task-1"
    assert session.authenticated_user_id == "U1"
    assert session.auth_method == "email"
    assert session.active_user_identity == {"name": "Alice", "email": "alice@example.com"}
    assert len(session.messages) == 1
    assert len(session.tool_results) == 1
    assert session.write_locks == ["lock_1"]
    assert session.audit_logs == [{"event": "auth"}]
    assert session.pending_action is not None
    assert session.pending_action.action_name == "cancel_pending_order"
    assert session.termination_reason == "user_confirmed"


def test_to_session_state_excludes_turn_level_fields() -> None:
    """to_session_state() 不包含 deprecated 和 turn-level 字段。"""
    state = ConversationState(
        session_id="cs-2",
        current_intent="lookup",
        risk_level="low",
    )
    state.add_step("test", status="ok")
    state.step_durations["test"] = 1.0

    session = state.to_session_state()

    # SessionState 不应该有这些字段
    assert not hasattr(session, "current_intent")
    assert not hasattr(session, "slots")
    assert not hasattr(session, "policy_decision")
    assert not hasattr(session, "confirmation_status")
    assert not hasattr(session, "risk_level")
    assert not hasattr(session, "run_metrics")
    assert not hasattr(session, "steps")
    assert not hasattr(session, "step_durations")


def test_to_session_state_preserves_loaded_context() -> None:
    """to_session_state() 正确拷贝 loaded_context。"""
    state = ConversationState(session_id="cs-3")
    state.loaded_context.orders["O1"] = {"order_id": "O1", "status": "pending"}
    state.loaded_context.users["U1"] = {"user_id": "U1", "name": "Alice"}

    session = state.to_session_state()

    assert session.loaded_context.orders["O1"]["status"] == "pending"
    assert session.loaded_context.users["U1"]["name"] == "Alice"


def test_from_session_state_reconstructs() -> None:
    """from_session_state() 从 SessionState + TurnContext 重建 ConversationState。"""
    session = SessionState(
        session_id="cs-4",
        authenticated_user_id="U2",
        auth_method="email",
        active_user_identity={"name": "Bob"},
    )
    session.messages.append(Message(role="user", content="hello"))
    session.loaded_context.orders["O1"] = {"order_id": "O1", "status": "pending"}
    session.pending_action = PendingAction(
        action_name="cancel_pending_order",
        arguments={"order_id": "O1"},
        user_facing_summary="Cancel O1",
    )
    turn = TurnContext(loop_iterations=2, termination="final_response")

    state = ConversationState.from_session_state(session, turn)

    assert state.session_id == "cs-4"
    assert state.authenticated_user_id == "U2"
    assert state.auth_method == "email"
    assert state.active_user_identity == {"name": "Bob"}
    assert len(state.messages) == 1
    assert state.loaded_context.orders["O1"]["status"] == "pending"
    assert state.pending_action is not None
    assert state.step_durations == {}
    assert state.llm_call_durations == []


def test_from_session_state_without_turn() -> None:
    """from_session_state() 在无 TurnContext 时也能工作。"""
    session = SessionState(session_id="cs-5")

    state = ConversationState.from_session_state(session)

    assert state.session_id == "cs-5"
    assert state.steps == []
    assert state.step_durations == {}
    assert state.llm_call_durations == []


def test_roundtrip_session_state() -> None:
    """ConversationState → to_session_state() → 修改 session → from_session_state() 闭环。"""
    original = ConversationState(
        session_id="cs-6",
        current_intent="cancel_order",
        risk_level="high",
    )
    original.authenticated_user_id = "U3"
    original.messages.append(Message(role="user", content="cancel O2"))
    original.pending_action = PendingAction(
        action_name="cancel_pending_order",
        arguments={"order_id": "O2"},
        user_facing_summary="Cancel O2",
    )

    session = original.to_session_state()
    # 修改 session（模拟新 runtime 操作）
    session.messages.append(Message(role="assistant", content="Order cancelled"))
    session.pending_action = None
    session.tool_results.append(
        ToolCallRecord(
            tool_name="cancel_pending_order",
            arguments={"order_id": "O2", "reason": "no longer needed"},
            tool_kind="write",
            status="success",
        )
    )
    turn = TurnContext(loop_iterations=3)

    restored = ConversationState.from_session_state(session, turn)

    assert restored.session_id == "cs-6"
    assert restored.authenticated_user_id == "U3"
    assert len(restored.messages) == 2
    assert restored.pending_action is None
    assert len(restored.tool_results) == 1
    assert restored.turn_context.loop_iterations == 3
    # deprecated 字段回到默认值（新 runtime 不维护它们）
    assert restored.current_intent == "unknown"


def test_turn_context_property_on_reconstructed_state() -> None:
    """从 from_session_state() 重建的 state 可以访问 turn_context property。"""
    session = SessionState(session_id="cs-7")
    turn = TurnContext(loop_iterations=5, llm_token_usage={"total_tokens": 100})

    state = ConversationState.from_session_state(session, turn)

    assert state.turn_context.loop_iterations == 5
    assert state.turn_context.llm_token_usage == {"total_tokens": 100}
```

- [ ] **Step 2：运行转换测试，确认失败**

```bash
uv run python -m pytest tests/test_state_conversion.py -q
```

预期：`AttributeError: 'ConversationState' object has no attribute 'to_session_state'`

- [ ] **Step 3：在 ConversationState 上添加转换方法**

在 `app/agent/models.py` 的 `ConversationState` 类中，在 `add_step` 方法之后追加：

```python
    # ── Phase 2: Conversion to/from new state models ──

    def to_session_state(self) -> SessionState:
        """Extract a SessionState snapshot from this ConversationState.

        Only copies session-level fields. Turn-level fields (steps,
        step_durations, llm_call_durations) and deprecated fields
        (current_intent, slots, policy_decision, confirmation_status,
        risk_level, run_metrics) are excluded.
        """
        return SessionState(
            session_id=self.session_id,
            task_id=self.task_id,
            authenticated_user_id=self.authenticated_user_id,
            auth_method=self.auth_method,
            active_user_identity=dict(self.active_user_identity),
            messages=list(self.messages),
            loaded_context=self.loaded_context,
            tool_results=list(self.tool_results),
            write_locks=list(self.write_locks),
            audit_logs=list(self.audit_logs),
            pending_action=self.pending_action,
            termination_reason=self.termination_reason,
        )

    @classmethod
    def from_session_state(
        cls, session: SessionState, turn: Optional[TurnContext] = None
    ) -> ConversationState:
        """Construct a ConversationState from SessionState + optional TurnContext.

        The resulting ConversationState has default values for all deprecated
        fields (current_intent, slots, etc.) since the new runtime does not
        maintain them.
        """
        state = cls(session_id=session.session_id)
        state.task_id = session.task_id
        state.authenticated_user_id = session.authenticated_user_id
        state.auth_method = session.auth_method
        state.active_user_identity = dict(session.active_user_identity)
        state.messages = list(session.messages) if session.messages else []
        state.loaded_context = session.loaded_context
        state.tool_results = list(session.tool_results) if session.tool_results else []
        state.write_locks = list(session.write_locks) if session.write_locks else []
        state.audit_logs = list(session.audit_logs) if session.audit_logs else []
        state.pending_action = session.pending_action
        state.termination_reason = session.termination_reason
        if turn is not None:
            state.steps = list(turn.steps) if turn.steps else []
            state.step_durations = dict(turn.step_durations) if turn.step_durations else {}
            state.llm_call_durations = list(turn.llm_call_durations) if turn.llm_call_durations else []
        return state

    @property
    def turn_context(self) -> TurnContext:
        """Build a TurnContext snapshot from this ConversationState's turn-level fields."""
        return TurnContext(
            steps=list(self.steps),
            step_durations=dict(self.step_durations),
            llm_call_durations=list(self.llm_call_durations),
            llm_token_usage=None,
            loop_iterations=0,
            consecutive_tool_failures=0,
            termination=self.termination_reason,
        )
```

- [ ] **Step 4：运行转换测试**

```bash
uv run python -m pytest tests/test_state_conversion.py -q
```

预期：7 passed.

- [ ] **Step 5：运行全量回归测试**

```bash
uv run python -m pytest tests/ -q
```

预期：所有现有测试通过（243 existing + 13 new ≈ 256 tests）。

- [ ] **Step 6：Lint**

```bash
uv run ruff check app/agent/models.py tests/test_session_state.py tests/test_state_conversion.py
```

- [ ] **Step 7：提交**

```bash
git add app/agent/models.py tests/test_session_state.py tests/test_state_conversion.py
git commit -m "feat: add ConversationState to/from SessionState conversion methods"
```

---

### Task 3：更新 Trace Serialization

**文件：**
- 修改：`app/ops/tracing.py`

- [ ] **Step 1：确认现有 trace 测试通过（作为基线）**

```bash
uv run python -m pytest tests/test_agent_core.py -q -k "trace"
```

- [ ] **Step 2：读取 tracing.py 找到修改位置**

阅读 `app/ops/tracing.py`，找到 `TraceWriter.write()` 方法中构建 trace dict 的位置（`"final_state"` 字段附近）。

- [ ] **Step 3：追加 session_state 和 turn_context 独立字段**

在 `"final_state"` 行之后追加（保持向后兼容，不修改现有字段）：

```python
# Phase 2: Record SessionState and TurnContext as independent views.
# These are additive — existing final_state is preserved for backward compat.
if hasattr(state, "to_session_state"):
    trace["session_state"] = _to_plain(state.to_session_state().model_dump())
if hasattr(state, "turn_context"):
    trace["turn_context"] = _to_plain(state.turn_context.model_dump())
```

- [ ] **Step 4：运行测试确认兼容**

```bash
uv run python -m pytest tests/ -q
```

- [ ] **Step 5：Lint**

```bash
uv run ruff check app/ops/tracing.py
```

- [ ] **Step 6：提交**

```bash
git add app/ops/tracing.py
git commit -m "feat: record SessionState and TurnContext in trace artifact"
```

---

### Task 4：新增 ContextBuilder

**文件：**
- 新增：`app/agent/context_builder.py`
- 新增：`tests/test_context_builder.py`

- [ ] **Step 1：编写测试**

创建 `tests/test_context_builder.py`：

```python
from __future__ import annotations

from app.agent.context_builder import ContextBuilder
from app.agent.models import (
    Message,
    PendingAction,
    SessionState,
    ToolCallRecord,
)


def _session() -> SessionState:
    session = SessionState(
        session_id="ctx-1",
        authenticated_user_id="U1",
        auth_method="email",
        active_user_identity={
            "user_id": "U1",
            "name": "Alice Smith",
            "email": "alice@example.com",
            "addresses": [
                {"address1": "123 Main St", "city": "Springfield", "state": "IL", "zip": "62701", "country": "USA"},
            ],
        },
    )
    session.messages = [
        Message(role="user", content="I need help with my order"),
        Message(role="assistant", content="Let me look up your order. Which order would you like to check?"),
    ]
    session.loaded_context.orders["O1"] = {
        "order_id": "O1",
        "user_id": "U1",
        "status": "pending",
        "items": [{"item_id": "I1", "name": "Widget"}, {"item_id": "I2", "name": "Gadget"}],
    }
    session.loaded_context.orders["O2"] = {
        "order_id": "O2",
        "user_id": "U1",
        "status": "delivered",
        "items": [{"item_id": "I3", "name": "Thing"}],
    }
    session.tool_results = [
        ToolCallRecord(
            tool_name="get_order_details",
            arguments={"order_id": "O1"},
            tool_kind="read",
            status="success",
            observation={"order_id": "O1", "status": "pending", "item_count": 2},
        ),
        ToolCallRecord(
            tool_name="get_order_details",
            arguments={"order_id": "O2"},
            tool_kind="read",
            status="success",
            observation={"order_id": "O2", "status": "delivered", "item_count": 1},
        ),
    ]
    return session


def test_build_includes_auth_summary() -> None:
    builder = ContextBuilder(policy_text="dummy policy")
    summary = builder.build(_session())
    assert "Alice Smith" in summary
    assert "U1" in summary
    assert "example.com" in summary


def test_build_includes_order_summaries() -> None:
    builder = ContextBuilder(policy_text="dummy policy")
    summary = builder.build(_session())
    assert "O1" in summary
    assert "pending" in summary
    assert "O2" in summary
    assert "delivered" in summary


def test_build_marks_writable_orders() -> None:
    builder = ContextBuilder(policy_text="dummy policy")
    summary = builder.build(_session())
    assert "[writable]" in summary


def test_build_includes_pending_action() -> None:
    session = _session()
    session.pending_action = PendingAction(
        action_name="cancel_pending_order",
        arguments={"order_id": "O1", "reason": "no longer needed"},
        user_facing_summary="Cancel order O1 because no longer needed",
    )
    builder = ContextBuilder(policy_text="dummy policy")
    summary = builder.build(session)
    assert "cancel_pending_order" in summary
    assert "no longer needed" in summary


def test_build_includes_write_locks() -> None:
    session = _session()
    session.write_locks = ["order_O1_write_lock", "order_O3_write_lock"]
    builder = ContextBuilder(policy_text="dummy policy")
    summary = builder.build(session)
    assert "order_O1_write_lock" in summary
    assert "order_O3_write_lock" in summary


def test_build_includes_recent_tool_results() -> None:
    builder = ContextBuilder(policy_text="dummy policy")
    summary = builder.build(_session())
    assert "get_order_details" in summary


def test_build_handles_unauthenticated_user() -> None:
    session = SessionState(session_id="ctx-2")
    builder = ContextBuilder(policy_text="dummy policy")
    summary = builder.build(session)
    assert "not authenticated" in summary.lower()


def test_build_handles_empty_state() -> None:
    session = SessionState(session_id="ctx-3")
    builder = ContextBuilder(policy_text="dummy policy")
    summary = builder.build(session)
    assert len(summary) > 0


def test_estimate_tokens_returns_reasonable_value() -> None:
    builder = ContextBuilder(policy_text="dummy policy")
    summary = builder.build(_session())
    tokens = builder.estimate_tokens(summary)
    assert isinstance(tokens, int)
    assert tokens > 0
    assert tokens < 2000


def test_build_with_policy_text_includes_policy_excerpt() -> None:
    policy = "This is the retail policy. Orders can be cancelled if pending."
    builder = ContextBuilder(policy_text=policy)
    summary = builder.build(_session())
    assert "retail policy" in summary.lower()


def test_recent_messages_limited_to_last_six() -> None:
    session = _session()
    for i in range(10):
        session.messages.append(Message(role="user", content=f"msg {i}"))
    builder = ContextBuilder(policy_text="dummy policy")
    summary = builder.build(session)
    assert "msg 0" not in summary
    assert "msg 1" not in summary
    assert "msg 2" not in summary
    assert "msg 3" not in summary
    assert "msg 8" in summary
    assert "msg 9" in summary
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
    """Builds a compressed, LLM-visible state summary from SessionState.

    The summary is designed to fit within a ~1200 token budget and
    provides the LLM with all the context it needs to make tool-calling
    decisions without overwhelming the prompt with raw DB objects.
    """

    def __init__(self, *, policy_text: str, max_recent_messages: int = 6) -> None:
        self._policy_text = policy_text
        self._max_recent_messages = max_recent_messages

    def build(self, session: SessionState) -> str:
        parts: list[str] = []
        parts.append(self._auth_summary(session))
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
        """Rough token count using word-based heuristic (1 token ≈ 0.75 word)."""
        words = len(text.split())
        return max(1, int(words / 0.75))

    # ── Private helpers ──

    def _auth_summary(self, session: SessionState) -> str:
        if not session.authenticated_user_id:
            return "## Session\nUser: not authenticated"
        identity = session.active_user_identity
        name = identity.get("name", "Unknown")
        email = identity.get("email", "")
        lines = [
            "## Session",
            f"User: {name} (ID: {session.authenticated_user_id})",
            f"Auth: {session.auth_method or 'unknown'}",
        ]
        if email and "@" in str(email):
            domain = str(email).split("@")[1]
            lines.append(f"Email domain: {domain}")
        return "\n".join(lines)

    def _orders_summary(self, session: SessionState) -> str:
        lines = ["## Loaded Orders"]
        for order_id, order in session.loaded_context.orders.items():
            status = order.get("status", "unknown")
            items = order.get("items", [])
            item_count = len(items) if isinstance(items, list) else 0
            owner_id = order.get("user_id", "")
            flags = ""
            if status == "pending" and owner_id == session.authenticated_user_id:
                flags = " [writable]"
            elif status in ("pending", "processing") and owner_id != session.authenticated_user_id:
                flags = " [read-only: not your order]"
            lines.append(f"- {order_id}: {status}, {item_count} items{flags}")
        return "\n".join(lines)

    def _pending_summary(self, session: SessionState) -> str:
        pa = session.pending_action
        if pa is None:
            return ""
        return (
            "## Pending Action\n"
            f"Action: {pa.action_name}\n"
            f"Arguments: {self._brief_args(pa.arguments)}\n"
            f"Summary: {pa.user_facing_summary}"
        )

    def _locks_summary(self, session: SessionState) -> str:
        lines = ["## Write Locks"]
        for lock in session.write_locks:
            lines.append(f"- {lock}")
        return "\n".join(lines)

    def _tool_results_summary(self, session: SessionState) -> str:
        recent = session.tool_results[-3:]
        lines = ["## Recent Tool Calls"]
        for record in recent:
            obs_summary = self._summarize_observation(record.observation)
            lines.append(f"- {record.tool_name}: {record.status} — {obs_summary}")
        return "\n".join(lines)

    def _messages_summary(self, session: SessionState) -> str:
        recent = session.messages[-self._max_recent_messages :]
        lines = ["## Recent Messages"]
        for msg in recent:
            content = msg.content[:200]
            lines.append(f"- [{msg.role}] {content}")
        return "\n".join(lines)

    def _policy_summary(self) -> str:
        excerpt = self._policy_text[:500].strip()
        return f"## Policy\n{excerpt}"

    @staticmethod
    def _brief_args(args: dict[str, Any]) -> str:
        items = []
        for k, v in args.items():
            v_str = str(v)
            if len(v_str) > 40:
                v_str = v_str[:37] + "..."
            items.append(f"{k}={v_str}")
        return ", ".join(items)

    @staticmethod
    def _summarize_observation(obs: Any) -> str:
        if obs is None:
            return "(no observation)"
        if isinstance(obs, dict):
            key_fields = []
            for field in ("order_id", "status", "user_id", "item_count", "name", "email"):
                if field in obs:
                    key_fields.append(f"{field}={obs[field]}")
            if key_fields:
                return ", ".join(key_fields[:4])
            return f"dict({len(obs)} keys)"
        if isinstance(obs, list):
            return f"list({len(obs)} items)"
        text = str(obs)
        if len(text) > 80:
            text = text[:77] + "..."
        return text
```

- [ ] **Step 4：运行 ContextBuilder 测试**

```bash
uv run python -m pytest tests/test_context_builder.py -q
```

预期：11 passed.

- [ ] **Step 5：Lint**

```bash
uv run ruff check app/agent/context_builder.py tests/test_context_builder.py
```

- [ ] **Step 6：提交**

```bash
git add app/agent/context_builder.py tests/test_context_builder.py
git commit -m "feat: add ContextBuilder for LLM-visible state summary"
```

---

### Task 5：Phase 2 回归检查

**文件：** 仅更新计划文档。

- [ ] **Step 1：运行 focused tests**

```bash
uv run python -m pytest tests/test_session_state.py tests/test_state_conversion.py tests/test_context_builder.py -q
```

预期：24 passed.

- [ ] **Step 2：运行全量测试**

```bash
uv run python -m pytest tests/ -q
```

预期：所有现有测试 + 24 new ≈ 267 tests passed.

- [ ] **Step 3：运行 lint**

```bash
uv run ruff check .
```

预期：All checks passed.

- [ ] **Step 4：验证 eval 仍可运行**

```bash
uv run phase2-eval --subset curated_mvp --trials 1
```

预期：正常完成，结果与 Phase 1 一致。

- [ ] **Step 5：更新主计划文档**

在 `docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md` 的 Phase Status 追加：

```markdown
- Phase 2：✅ 完成 — SessionState/TurnContext 模型、ConversationState 转换方法、trace 独立视图、ContextBuilder（2026-06-13）。
```

- [ ] **Step 6：提交**

```bash
git add docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md
git commit -m "docs: mark LLM tool-calling phase 2 complete"
```

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| to_session_state 浅拷贝导致对象共享 | SessionState 构造时显式 `list()` / `dict()` 拷贝；loaded_context 是 Pydantic model 赋值（值语义） |
| TraceWriter 改动影响下游 consumer | 只追加字段，不修改 `final_state` |
| ContextBuilder token 估算不准确 | 保守估算（0.75 word/token），测试验证 <2000 token |

---

## 退出条件

```bash
uv run python -m pytest tests/ -q   # 全部通过 (267 tests)
uv run ruff check .                  # 零警告
uv run phase2-eval --subset curated_mvp --trials 1  # 结果一致
```

---

## Phase 3 预览

Phase 2 完成后，Phase 3 将基于 `SessionState` + `TurnContext` + `ContextBuilder` + Phase 1 的 provider/harness 实现 LLM agent loop。动代码前必须基于 Phase 2 完成后状态重新生成专用计划。
