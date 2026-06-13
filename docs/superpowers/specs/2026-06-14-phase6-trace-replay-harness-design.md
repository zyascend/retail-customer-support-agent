# Phase 6: Trace Replay Harness — 设计文档

日期：2026-06-14
状态：待评审
父 spec：`docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md`

## 目标

构建 `TraceReplayHarness`，能够从 trace artifact 回放一次已记录的 turn，用于调试、回归验证和 CI 稳定性。

## 背景

Phase 5 完成后，eval 基础设施已支持 scripted 和 live 两种 backend。trace artifact 记录了完整的 messages、tool_calls、steps、timing 和 metadata，但缺少 LLM 的原始 `ToolCallResponse` 序列，无法精确回放。

Phase 6 补全这个能力：在 AgentLoop 执行时记录每轮 LLM 响应到 `TurnContext`，序列化到 trace，然后通过 `TraceReplayHarness` 读取并回放。

## 非目标

- 不回放多轮对话（只回放单轮 single turn）
- 不修改 eval runner 或 `eval_backend` 枚举
- 不回放 pre-flight（identity shortcut、pending confirmation）
- 不实现 trace diff / comparison 工具
- 不改变 `ConversationState` 或 workbench 代码

## 设计决策

| # | 决策项 | 结论 |
|---|--------|------|
| 1 | LLM 响应记录位置 | `TurnContext.llm_responses: list[dict]`，每轮 ToolCallResponse.model_dump() |
| 2 | Trace 序列化方式 | `run_script()` 从 turn_contexts 提取 llm_responses，写入 trace metadata |
| 3 | 回放 gateway | 新建 `ScriptedToolGateway`，按顺序返回 trace 中记录的工具结果 |
| 4 | 回放范围 | 单 turn，不含 pre-flight |
| 5 | 测试策略 | 集成测试：构造 ScriptedToolCallingProvider + ScriptedToolGateway → 跑 AgentLoop → 验证输出一致 |

## TurnContext 变更

```python
class TurnContext(BaseModel):
    # ── 现有字段（不变）──
    steps: List[AgentStep] = Field(default_factory=list)
    step_durations: dict[str, float] = Field(default_factory=dict)
    llm_call_durations: list[dict] = Field(default_factory=list)
    llm_token_usage: Optional[Dict[str, Any]] = None
    loop_iterations: int = 0
    consecutive_tool_failures: int = 0
    termination: Optional[str] = None

    # ── Phase 6 新增 ──
    llm_responses: list[dict] = Field(default_factory=list)
```

## AgentLoop 记录

`AgentLoop.run_turn()` 在 `_step_llm_reason()` 返回后记录：

```python
response = self._step_llm_reason(messages, tool_schemas)
turn.llm_responses.append(response.model_dump())
```

记录内容（`ToolCallResponse.model_dump()`）包含：
- `assistant_content` — LLM 文本回复
- `tool_calls` — 工具调用列表（含 id、tool_name、arguments、raw_arguments）
- `finish_reason` — `"stop"` | `"tool_calls"` | ...
- `token_usage` — token 统计

## Trace 序列化

`AgentRuntime.run_script()` 在返回前提取 llm_responses：

```python
llm_responses = []
for turn_ctx in self._turn_contexts:
    llm_responses.extend(turn_ctx.llm_responses)

trace_path = TraceWriter(self.config.run_artifact_dir).write(
    run_id=run_id,
    state=session,
    metadata={
        ...
        "llm_responses": llm_responses,
    },
)
```

## ScriptedToolGateway

新文件 `app/agent/replay.py` 中定义：

```python
from app.agent.models import ToolCallRecord

class ScriptedToolGateway:
    """按脚本返回预先记录的工具结果，不执行真实工具。"""

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
        # 验证工具名一致
        if expected.tool_name != tool_name:
            raise RuntimeError(
                f"Tool mismatch: expected {expected.tool_name}, got {tool_name}"
            )
        return expected
```

注意：`ScriptedToolGateway` 不需要完整的 `ToolGateway` 接口（不需要 registry、runtime），只需要 `execute()` 方法签名兼容 `AgentLoop._step_tool_execute()` 的调用方式。

## TraceReplayHarness

```python
from pathlib import Path
from app.agent.models import SessionState, AgentTurnResult, ToolCallRecord
from app.agent.providers import ScriptedToolCallingProvider

class TraceReplayHarness:
    """从 trace artifact 回放单轮对话。"""

    def __init__(self, trace_path: Path, registry: "ToolRegistry") -> None:
        import json
        with open(trace_path) as f:
            self._trace = json.load(f)

        # 提取 LLM 响应序列
        raw_responses = self._trace.get("llm_responses", [])
        from app.agent.models import ToolCallResponse, ToolCallRequest
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
        context_builder: "ContextBuilder",
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

## 文件变更

### 新增

```
app/agent/replay.py              — TraceReplayHarness + ScriptedToolGateway
tests/test_trace_replay_harness.py
```

### 修改

```
app/agent/models.py              — TurnContext + llm_responses
app/agent/llm_agent.py           — 记录 ToolCallResponse 到 turn.llm_responses
app/agent/runtime.py             — 提取 llm_responses 到 trace metadata
```

### 不修改

```
app/ops/tracing.py               — 不变（llm_responses 走 metadata 通道）
app/eval/                         — 不变
app/tools/                        — 不变
```

## 测试计划

`tests/test_trace_replay_harness.py`：

1. **test_scripted_gateway_returns_recorded_results** — ScriptedToolGateway 按序返回 ToolCallRecord
2. **test_scripted_gateway_raises_when_exhausted** — 结果耗尽时抛 RuntimeError
3. **test_scripted_gateway_raises_on_tool_name_mismatch** — 工具名不匹配时抛异常
4. **test_replay_read_turn_smoke** — 端到端：scripted provider + gateway → AgentLoop → 验证输出
5. **test_turn_context_records_llm_responses** — TurnContext.llm_responses 在 run_turn 后被填充
6. **test_replay_output_matches_original** — 用记录的 llm_responses + tool_results 回放，结果一致

## 验收标准

- [ ] `TurnContext` 有 `llm_responses` 字段
- [ ] `AgentLoop.run_turn()` 每轮记录 ToolCallResponse
- [ ] `run_script()` 把 llm_responses 写入 trace metadata
- [ ] `ScriptedToolGateway` 按序返回工具结果，耗尽/不匹配时抛异常
- [ ] `TraceReplayHarness.replay()` 可回放单轮
- [ ] `uv run python -m pytest tests/test_trace_replay_harness.py -q` 通过
- [ ] `uv run python -m pytest tests/ -q` 通过
- [ ] `uv run ruff check .` 通过

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| trace 中没有 llm_responses（旧 trace） | TraceReplayHarness 加载时检查，缺失时抛明确错误 |
| pre-flight 干扰回放 | replay 只跑 AgentLoop，不经过 AgentRuntime.handle_user_message() |
| ScriptedToolGateway 与 ToolGateway 接口不一致 | 只实现 execute() 方法，与 AgentLoop 调用点对齐即可 |
