# Phase 6: Trace Replay Harness — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 TraceReplayHarness，记录 LLM 响应到 TurnContext → trace，并从 trace 回放单轮对话。

**Architecture:** 三层：记录层（TurnContext.llm_responses + AgentLoop 记录）→ 序列化层（run_script 提取到 trace metadata）→ 回放层（ScriptedToolGateway + TraceReplayHarness）。ScriptedToolGateway 只实现 `execute()` 方法，与 AgentLoop 调用点对齐。

**Tech Stack:** Python, Pydantic v2, pytest, 现有 ScriptedToolCallingProvider

**Spec:** `docs/superpowers/specs/2026-06-14-phase6-trace-replay-harness-design.md`

---

## 文件结构

```
app/agent/
  models.py              ← 修改：TurnContext + llm_responses
  llm_agent.py           ← 修改：记录 ToolCallResponse 到 turn
  runtime.py             ← 修改：提取 llm_responses 到 trace metadata
  replay.py              ← 新增：TraceReplayHarness + ScriptedToolGateway

tests/
  test_trace_replay_harness.py  ← 新增
```

---

### Task 1: TurnContext.llm_responses — 记录 LLM 响应

**Files:**
- Modify: `app/agent/models.py:131-146`
- Modify: `app/agent/llm_agent.py:48-66`
- Modify: `app/agent/runtime.py:141-156`

- [ ] **Step 1: 编写失败测试**

创建 `tests/test_trace_replay_harness.py`：

```python
from __future__ import annotations

import unittest

from app.agent.models import TurnContext, ToolCallResponse, ToolCallRequest


class TurnContextRecordingTests(unittest.TestCase):
    def test_turn_context_has_llm_responses_field(self):
        turn = TurnContext()
        self.assertEqual(turn.llm_responses, [])

    def test_turn_context_can_store_llm_response(self):
        turn = TurnContext()
        response = ToolCallResponse(
            assistant_content="I found your order.",
            finish_reason="stop",
            token_usage={"total_tokens": 100},
        )
        turn.llm_responses.append(response.model_dump())
        self.assertEqual(len(turn.llm_responses), 1)
        self.assertEqual(turn.llm_responses[0]["finish_reason"], "stop")
        self.assertEqual(turn.llm_responses[0]["assistant_content"], "I found your order.")

    def test_turn_context_stores_multiple_llm_responses_per_turn(self):
        turn = TurnContext()
        r1 = ToolCallResponse(
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    tool_name="get_order_details",
                    arguments={"order_id": "W123"},
                )
            ],
            finish_reason="tool_calls",
        )
        r2 = ToolCallResponse(
            assistant_content="Done.",
            finish_reason="stop",
        )
        turn.llm_responses.append(r1.model_dump())
        turn.llm_responses.append(r2.model_dump())
        self.assertEqual(len(turn.llm_responses), 2)
        self.assertEqual(turn.llm_responses[0]["finish_reason"], "tool_calls")
        self.assertEqual(turn.llm_responses[1]["finish_reason"], "stop")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run python -m pytest tests/test_trace_replay_harness.py -v
```

预期：FAIL — `TurnContext` 没有 `llm_responses` 属性。

- [ ] **Step 3: TurnContext 新增 llm_responses**

修改 `app/agent/models.py` 的 `TurnContext` 类，在 `termination` 字段后新增：

```python
    # ── Phase 6: replay harness ──
    llm_responses: list[dict] = Field(default_factory=list)
```

- [ ] **Step 4: AgentLoop 记录 ToolCallResponse**

修改 `app/agent/llm_agent.py` 的 `run_turn` 方法。在 `self._step_llm_reason(messages, tool_schemas)` 返回后（约第 53 行），新增记录：

```python
            try:
                response = self._step_llm_reason(messages, tool_schemas)
                # Phase 6: record LLM response for trace replay
                turn.llm_responses.append(response.model_dump())
            except TimeoutError:
```

- [ ] **Step 5: run_script 提取 llm_responses 到 trace metadata**

修改 `app/agent/runtime.py` 的 `run_script` 方法。在 metadata dict 中新增（`"prompts": prompt_metadata(),` 之后）：

```python
                "llm_responses": [
                    resp
                    for turn_ctx in self._turn_contexts
                    for resp in turn_ctx.llm_responses
                ],
```

- [ ] **Step 6: 运行测试确认通过**

```bash
uv run python -m pytest tests/test_trace_replay_harness.py -v
```

预期：3 passed。

- [ ] **Step 7: 提交**

```bash
git add app/agent/models.py app/agent/llm_agent.py app/agent/runtime.py tests/test_trace_replay_harness.py
git commit -m "feat: record LLM responses in TurnContext and trace metadata"
```

---

### Task 2: ScriptedToolGateway

**Files:**
- Create: `app/agent/replay.py`
- Modify: `tests/test_trace_replay_harness.py`

- [ ] **Step 1: 编写失败测试**

追加到 `tests/test_trace_replay_harness.py`：

```python
from app.agent.models import ToolCallRecord


class ScriptedToolGatewayTests(unittest.TestCase):
    def test_scripted_gateway_returns_recorded_results_in_order(self):
        from app.agent.replay import ScriptedToolGateway

        results = [
            ToolCallRecord(
                tool_name="get_order_details",
                arguments={"order_id": "W123"},
                tool_kind="read",
                status="success",
                observation={"status": "pending"},
            ),
            ToolCallRecord(
                tool_name="cancel_pending_order",
                arguments={"order_id": "W123", "reason": "no longer needed"},
                tool_kind="write",
                status="blocked",
                error="explicit_confirmation_required",
            ),
        ]
        gateway = ScriptedToolGateway(results=results)

        r1 = gateway.execute(state=None, tool_name="get_order_details", arguments={"order_id": "W123"})
        self.assertEqual(r1.status, "success")
        self.assertEqual(r1.tool_name, "get_order_details")

        r2 = gateway.execute(state=None, tool_name="cancel_pending_order", arguments={"order_id": "W123", "reason": "no longer needed"})
        self.assertEqual(r2.status, "blocked")
        self.assertEqual(r2.error, "explicit_confirmation_required")

    def test_scripted_gateway_raises_when_exhausted(self):
        from app.agent.replay import ScriptedToolGateway

        gateway = ScriptedToolGateway(results=[])
        with self.assertRaises(RuntimeError) as ctx:
            gateway.execute(state=None, tool_name="any_tool", arguments={})
        self.assertIn("No scripted tool results remain", str(ctx.exception))

    def test_scripted_gateway_raises_on_tool_name_mismatch(self):
        from app.agent.replay import ScriptedToolGateway

        results = [
            ToolCallRecord(
                tool_name="get_order_details",
                arguments={},
                tool_kind="read",
                status="success",
            ),
        ]
        gateway = ScriptedToolGateway(results=results)
        with self.assertRaises(RuntimeError) as ctx:
            gateway.execute(state=None, tool_name="wrong_tool", arguments={})
        self.assertIn("Tool mismatch", str(ctx.exception))

    def test_scripted_gateway_tracks_all_calls(self):
        from app.agent.replay import ScriptedToolGateway

        results = [
            ToolCallRecord(
                tool_name="find_user_id_by_email",
                arguments={"email": "test@test.com"},
                tool_kind="read",
                status="success",
                observation="user_1",
            ),
        ]
        gateway = ScriptedToolGateway(results=results)
        gateway.execute(state=None, tool_name="find_user_id_by_email", arguments={"email": "test@test.com"})

        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(gateway.calls[0]["tool_name"], "find_user_id_by_email")
        self.assertEqual(gateway.calls[0]["arguments"], {"email": "test@test.com"})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run python -m pytest tests/test_trace_replay_harness.py::ScriptedToolGatewayTests -v
```

预期：FAIL — `ScriptedToolGateway` 不存在。

- [ ] **Step 3: 实现 ScriptedToolGateway**

创建 `app/agent/replay.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run python -m pytest tests/test_trace_replay_harness.py::ScriptedToolGatewayTests -v
```

预期：4 passed。

- [ ] **Step 5: 提交**

```bash
git add app/agent/replay.py tests/test_trace_replay_harness.py
git commit -m "feat: add ScriptedToolGateway for trace replay"
```

---

### Task 3: TraceReplayHarness

**Files:**
- Modify: `app/agent/replay.py`
- Modify: `tests/test_trace_replay_harness.py`

- [ ] **Step 1: 编写失败测试**

追加到 `tests/test_trace_replay_harness.py`：

```python
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from app.agent.models import (
    AgentTurnResult,
    SessionState,
    ToolCallRecord,
    ToolCallRequest,
    ToolCallResponse,
    TurnContext,
)


class TraceReplayHarnessTests(unittest.TestCase):
    def _make_trace(self, tmp: str, llm_responses: list[dict], tool_calls: list[dict]) -> Path:
        trace = {
            "run_id": "test-replay",
            "llm_responses": llm_responses,
            "tool_calls": tool_calls,
            "messages": [],
            "steps": [],
        }
        path = Path(tmp) / "trace.json"
        path.write_text(json.dumps(trace))
        return path

    def _make_registry(self):
        from app.tools.registry import ToolRegistry
        registry = MagicMock(spec=ToolRegistry)
        registry.tools = {"get_order_details", "find_user_id_by_email"}
        registry.tool_schemas_for_llm.return_value = []
        return registry

    def _make_context_builder(self):
        from app.agent.context_builder import ContextBuilder
        builder = MagicMock(spec=ContextBuilder)
        builder.build.return_value = "state_summary_placeholder"
        builder.policy_text = ""
        return builder

    def test_replay_harness_loads_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = self._make_trace(tmp, [], [])
            registry = self._make_registry()
            from app.agent.replay import TraceReplayHarness
            harness = TraceReplayHarness(trace_path, registry)
            self.assertIsNotNone(harness)

    def test_replay_read_turn_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            responses = [
                ToolCallResponse(
                    assistant_content="I'll look up that order for you.",
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="get_order_details",
                            arguments={"order_id": "W123"},
                        )
                    ],
                    finish_reason="tool_calls",
                ).model_dump(),
                ToolCallResponse(
                    assistant_content="Your order #W123 is pending.",
                    finish_reason="stop",
                ).model_dump(),
            ]
            tool_calls = [
                ToolCallRecord(
                    tool_name="get_order_details",
                    arguments={"order_id": "W123"},
                    tool_kind="read",
                    status="success",
                    observation={"order_id": "W123", "status": "pending"},
                ).model_dump(),
            ]
            trace_path = self._make_trace(tmp, responses, tool_calls)
            registry = self._make_registry()
            context_builder = self._make_context_builder()

            from app.agent.replay import TraceReplayHarness
            harness = TraceReplayHarness(trace_path, registry)
            session = SessionState(session_id="replay-test")
            result = harness.replay(
                session,
                "What is the status of order #W123?",
                context_builder=context_builder,
            )
            self.assertIsInstance(result, AgentTurnResult)
            self.assertIn("pending", result.assistant_message)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run python -m pytest tests/test_trace_replay_harness.py::TraceReplayHarnessTests -v
```

预期：FAIL — `TraceReplayHarness` 不存在。

- [ ] **Step 3: 实现 TraceReplayHarness**

追加到 `app/agent/replay.py`：

```python
import json
from pathlib import Path

from app.agent.models import (
    AgentTurnResult,
    SessionState,
    ToolCallRecord,
    ToolCallResponse,
    ToolCallRequest,
)
from app.agent.providers import ScriptedToolCallingProvider


class TraceReplayHarness:
    """从 trace artifact 回放单轮对话。

    加载 trace JSON，提取 LLM 响应序列和工具结果序列，
    用 ScriptedToolCallingProvider + ScriptedToolGateway 驱动 AgentLoop。
    """

    def __init__(self, trace_path: Path, registry) -> None:
        with open(trace_path) as f:
            self._trace = json.load(f)

        # 提取 LLM 响应序列
        raw_responses = self._trace.get("llm_responses", [])
        self._responses = [
            ToolCallResponse(**r) for r in raw_responses
        ]

        # 提取工具结果序列
        raw_tool_calls = self._trace.get("tool_calls", [])
        self._tool_results = [
            ToolCallRecord(**tc) for tc in raw_tool_calls
        ]

        self._registry = registry

    def replay(
        self,
        session: SessionState,
        user_message: str,
        *,
        context_builder,
    ) -> AgentTurnResult:
        """回放单轮：用记录的 LLM 响应和工具结果驱动 AgentLoop。"""
        from app.agent.llm_agent import AgentLoop

        provider = ScriptedToolCallingProvider(
            responses=list(self._responses)
        )
        gateway = ScriptedToolGateway(
            results=list(self._tool_results)
        )

        loop = AgentLoop(
            provider=provider,
            gateway=gateway,
            registry=self._registry,
            context_builder=context_builder,
        )
        return loop.run_turn(session, user_message)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run python -m pytest tests/test_trace_replay_harness.py::TraceReplayHarnessTests -v
```

预期：2 passed。

- [ ] **Step 5: 提交**

```bash
git add app/agent/replay.py tests/test_trace_replay_harness.py
git commit -m "feat: add TraceReplayHarness for single-turn trace replay"
```

---

### Task 4: 端到端回放验证测试

**Files:**
- Modify: `tests/test_trace_replay_harness.py`

- [ ] **Step 1: 编写端到端测试**

追加到 `tests/test_trace_replay_harness.py` 的 `TraceReplayHarnessTests` 类：

```python
    def test_replay_exhausted_llm_responses_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            # trace with only 1 LLM response but the AgentLoop needs 2
            # (one tool_calls + one final) — actually 1 is enough if it's stop
            responses = [
                ToolCallResponse(
                    assistant_content="Done.",
                    finish_reason="stop",
                ).model_dump(),
            ]
            trace_path = self._make_trace(tmp, responses, [])
            registry = self._make_registry()
            context_builder = self._make_context_builder()

            from app.agent.replay import TraceReplayHarness
            harness = TraceReplayHarness(trace_path, registry)
            session = SessionState(session_id="replay-test")
            result = harness.replay(
                session, "hello", context_builder=context_builder
            )
            self.assertIsInstance(result, AgentTurnResult)
            self.assertEqual(result.assistant_message, "Done.")

    def test_replay_with_write_pending_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            responses = [
                ToolCallResponse(
                    assistant_content="I'll cancel that order.",
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            tool_name="cancel_pending_order",
                            arguments={"order_id": "W123", "reason": "no longer needed"},
                        )
                    ],
                    finish_reason="tool_calls",
                ).model_dump(),
            ]
            tool_calls = [
                ToolCallRecord(
                    tool_name="cancel_pending_order",
                    arguments={"order_id": "W123", "reason": "no longer needed"},
                    tool_kind="write",
                    status="blocked",
                    error="explicit_confirmation_required",
                ).model_dump(),
            ]
            trace_path = self._make_trace(tmp, responses, tool_calls)
            registry = self._make_registry()
            context_builder = self._make_context_builder()

            from app.agent.replay import TraceReplayHarness
            harness = TraceReplayHarness(trace_path, registry)
            session = SessionState(session_id="replay-test")
            result = harness.replay(
                session, "Cancel order #W123", context_builder=context_builder
            )
            # Should set pending_action on session
            self.assertTrue(result.pending_action_set)
            self.assertIsNotNone(session.pending_action)
```

- [ ] **Step 2: 运行端到端测试**

```bash
uv run python -m pytest tests/test_trace_replay_harness.py::TraceReplayHarnessTests -v
```

预期：4 passed（2 原有 + 2 新增）。

- [ ] **Step 3: 提交**

```bash
git add tests/test_trace_replay_harness.py
git commit -m "test: add end-to-end replay verification tests"
```

---

### Task 5: Phase 6 回归检查

**Files:**
- 预期不修改源码文件。

- [ ] **Step 1: 运行 replay harness 测试**

```bash
uv run python -m pytest tests/test_trace_replay_harness.py -v
```

预期：9 passed（Task 1: 3 + Task 2: 4 + Task 3: 2 + Task 4: 新增 2，但 Task 4 的 2 个在 Task 3 的类里 = 3 + 4 + 4 = 11 passed）。

- [ ] **Step 2: 运行完整测试套件**

```bash
uv run python -m pytest tests/ -q
```

预期：全部通过，无新增 regression。

- [ ] **Step 3: 运行 lint**

```bash
uv run ruff check .
```

预期：通过。

- [ ] **Step 4: 更新计划状态**

修改 `docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md` 的 Phase Status 段，新增：

```markdown
- Phase 6：✅ 完成 — TurnContext.llm_responses 记录、ScriptedToolGateway、TraceReplayHarness、11 回放测试通过（2026-06-14）。
```

- [ ] **Step 5: 提交状态更新**

```bash
git add docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md
git commit -m "docs: mark LLM agent tool-calling phase 6 complete"
```

---

## 自审记录

Spec 覆盖：

- TurnContext + llm_responses → Task 1
- AgentLoop 记录 → Task 1
- Trace 序列化 → Task 1
- ScriptedToolGateway → Task 2
- TraceReplayHarness → Task 3
- 端到端回放验证 → Task 4
- 回归检查 → Task 5

歧义处理：

- `ScriptedToolGateway` 只实现 `execute()` 方法，不实现完整 `ToolGateway` 接口。AgentLoop 只调用 `execute()`，兼容即可。
- `TraceReplayHarness` 不处理 pre-flight（identity shortcut、pending confirmation）。回放范围限定为 AgentLoop.run_turn()。
- `llm_responses` 序列化走 trace metadata 通道（已有 dict 结构），不修改 `build_trace_payload()` 签名。
