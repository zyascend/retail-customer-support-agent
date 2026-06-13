# Phase 5: Eval 适配与 Live Benchmark — 设计文档

日期：2026-06-14
状态：待评审
父 spec：`docs/superpowers/specs/2026-06-13-llm-agent-tool-calling-architecture-design.md`

## 目标

将 eval 基础设施从旧 pipeline 语义迁移到 LLM tool-calling 语义，同时保持向后兼容。新增 `required_tools`/`forbidden_tools` 断言、`eval_backend` 分层、LLM 指标采集，以及 live eval 支持。

## 背景

Phase 4 完成后，生产 runtime 已完全切换到 LLM tool-calling agent loop。但 eval 基础设施仍然使用旧 pipeline 时代的断言语义：

- `expected_tool_names` 做精确集合匹配，对 LLM 的合理工具选择变体过于严格
- `classify_failure` 的 14 个标签按旧 intent/slot/confirmation 模型组织
- runner 不支持真实 LLM eval
- report 不区分 scripted/live backend
- `SessionState` 仍有 Phase 4 兼容字段

## 非目标

- 不删除 `expected_tool_names`（保持向后兼容）
- 不重写现有 41 个 case 的断言
- 不把 live eval 加入 CI gate
- 不在本阶段做 prompt A/B benchmark
- 不做 Dashboard UI 改造

## 设计决策

| # | 决策项 | 结论 |
|---|--------|------|
| 1 | tool 断言演进 | 增量添加 `required_tools`/`forbidden_tools`，保留 `expected_tool_names` |
| 2 | eval backend 分层 | `--live` flag 切换 scripted/live；默认 scripted |
| 3 | LLM 指标 | 从 `TurnContext` 提取 token/loop 指标写入 `EvalCaseResult` |
| 4 | Phase 4 compat 清理 | 移除 `current_intent`/`slots`/`policy_decision`/`risk_level` |
| 5 | report schema | 升级到 `phase5.eval_run_summary.v1`，新增 `eval_backend` |
| 6 | failure category | 保持现有 14-label 归类，新增 `required_tool_missing`/`forbidden_tool_called` |

## EvalCase 变更

```python
@dataclass(frozen=True)
class EvalCase:
    # ── 现有字段（不变）──
    case_id: str
    category: str
    messages: List[Dict[str, str]]
    expected_user_id: str
    expected_intent: str
    order_id: Optional[str] = None
    expected_write_lock: Optional[str] = None
    expected_order_status: Optional[str] = None
    expected_confirmation_status: Optional[str] = None
    expected_guard_block_reason: Optional[str] = None
    expected_no_write: bool = False
    expected_tool_names: List[str] = field(default_factory=list)
    expected_assistant_contains: Optional[str] = None
    max_turns: int = 8
    subset: str = "curated_mvp"
    capability: Optional[str] = None
    policy_area: Optional[str] = None
    scenario_family: Optional[str] = None
    variant_type: Optional[str] = None
    language_variation_level: Optional[str] = None
    expected_db_assertions: Dict[str, object] = field(default_factory=dict)
    expected_tool_sequence: List[str] = field(default_factory=list)
    seed: Optional[int] = None

    # ── Phase 5 新增 ──
    required_tools: set[str] = field(default_factory=set)
    forbidden_tools: set[str] = field(default_factory=set)
```

语义：

- `required_tools`：集合中每个 tool 必须在实际调用中出现至少一次
- `forbidden_tools`：集合中任何 tool 绝对不能出现
- 两者都为 `set`，与 `expected_tool_names`（`list`）明确区分类型
- 现有 case 不需要修改，`default_factory=set` 保证向后兼容

## EvalCaseResult 变更

```python
@dataclass
class EvalCaseResult:
    # ── 现有字段（不变）──
    ...

    # ── Phase 5 新增 ──
    eval_backend: str = "scripted"
    llm_token_usage: Optional[Dict[str, Any]] = None
    llm_loop_iterations: int = 0
```

数据来源：

- `eval_backend`：runner 根据是否 `--live` 设置
- `llm_token_usage`：从 `TurnContext.llm_token_usage` 提取
- `llm_loop_iterations`：从 `TurnContext.loop_iterations` 提取

## EvalRunSummary 变更

```python
@dataclass
class EvalRunSummary:
    # ── 现有字段（保留）──
    agent_strategy: str  # 保留但标记 deprecated

    # ── Phase 5 新增 ──
    eval_backend: str = "scripted"  # "scripted" | "live"
```

schema version: `"phase5.eval_run_summary.v1"`

Report 新增：
- `eval_backend` 字段
- `llm_metrics` 段（聚合的 token / loop / tool 统计）

## Runner 变更

### `--live` flag

```bash
# Scripted（默认）
uv run phase2-eval --subset curated_mvp

# Live
uv run phase2-eval --subset curated_mvp --live
```

`CuratedEvalRunner.__init__` 新增 `live: bool = False`：

- `live=False`：注入 `DisabledLLMProvider`，agent 在 offline mode 运行
- `live=True`：不注入 provider，让 `AgentRuntime` 用 `build_default_provider()` 连接真实 DeepSeek

### LLM 指标采集

`_run_case()` 在 `run_result` 返回后提取 `TurnContext` 指标：

```python
# 从 AgentRunResult.state 提取 turn context 指标
turn = run_result.turn  # 需要在 AgentRunResult 中暴露
result.llm_token_usage = turn.llm_token_usage
result.llm_loop_iterations = turn.loop_iterations
```

需要修改 `AgentRunResult` 或 `AgentRuntime.run_script()` 暴露 `TurnContext`。

## classify_failure 变更

在现有 `wrong_tool` 检查后新增：

```python
# Phase 5: required_tools / forbidden_tools
if case.required_tools:
    missing_required = [
        t for t in case.required_tools if t not in tool_names
    ]
    if missing_required:
        return "required_tool_missing"
if case.forbidden_tools:
    violated = [
        t for t in case.forbidden_tools if t in tool_names
    ]
    if violated:
        return "forbidden_tool_called"
```

failure_category 映射：

```python
"required_tool_missing": "wrong_tool",
"forbidden_tool_called": "wrong_tool",
```

## SessionState 清理

移除 Phase 4 兼容字段：

```python
class SessionState(BaseModel):
    # 移除以下字段：
    # current_intent: str = "unknown"
    # slots: Dict[str, Any] = Field(default_factory=dict)
    # policy_decision: Optional[PolicyDecision] = None
    # risk_level: str = "low"

    # 保留（eval 仍在使用）：
    confirmation_status: str = "not_required"
    step_durations: dict[str, float] = Field(default_factory=dict)
```

需要更新 `AgentRuntime.handle_user_message()` 中引用这些字段的代码。

## AgentRunResult 变更

`AgentRunResult` 当前只暴露 `state: SessionState`。需要新增 `turn_contexts` 以便 eval runner 提取 LLM 指标。

实现机制：

1. `AgentRuntime` 新增私有属性 `_turn_contexts: list[TurnContext]`
2. `handle_user_message()` 每次调用后将 `AgentTurnResult.turn` append 到 `_turn_contexts`
3. `run_script()` 在返回前将 `_turn_contexts` 传入 `AgentRunResult`

```python
@dataclass
class AgentRunResult:
    run_id: str
    state: SessionState
    trace_artifact_path: Path
    turn_contexts: list[TurnContext] = field(default_factory=list)  # Phase 5 新增
```

Eval runner 从最后一轮（或聚合所有轮）的 `TurnContext` 提取 LLM 指标。

## 文件变更

### 修改

```
app/agent/models.py          — SessionState 清理 + AgentRunResult 新增 turn_contexts
app/agent/runtime.py         — run_script 累积 TurnContext
app/eval/cases.py            — EvalCase 新增 required_tools/forbidden_tools
app/eval/runner.py           — --live flag, LLM 指标采集, eval_backend
app/eval/metrics.py          — schema version, LLM metrics 聚合
tests/test_eval_runner.py    — 新增 Phase 5 测试
```

### 不修改

```
app/agent/llm_agent.py       — 不变
app/agent/guard.py           — 不变
app/tools/                   — 不变
```

## 测试计划

在 `tests/test_eval_runner.py` 新增：

1. `test_required_tool_missing_fails` — required_tools 不满足 → `required_tool_missing`
2. `test_forbidden_tool_called_fails` — forbidden_tools 被调用 → `forbidden_tool_called`
3. `test_scripted_run_marks_backend_scripted` — scripted run 的 summary 标记 scripted
4. `test_eval_case_result_carries_llm_metrics` — result 携带 token/loop 指标
5. `test_report_schema_version_is_phase5` — schema version 升级
6. `test_session_state_no_phase4_compat_fields` — SessionState 不含 compat 字段
7. `test_existing_curated_mvp_still_passes` — 现有 11 case 不受影响

## 验收标准

- [ ] `EvalCase` 有 `required_tools` / `forbidden_tools` 字段
- [ ] `EvalCaseResult` 有 `eval_backend` / `llm_token_usage` / `llm_loop_iterations`
- [ ] `EvalRunSummary` 有 `eval_backend`，schema version 升级
- [ ] `--live` flag 可切换真实 LLM eval
- [ ] scripted run 标记 `eval_backend="scripted"`
- [ ] `SessionState` 不含 `current_intent` / `slots` / `policy_decision` / `risk_level`
- [ ] `classify_failure` 支持 `required_tools` / `forbidden_tools`
- [ ] `uv run python -m pytest tests/test_eval_runner.py -q` 通过
- [ ] `uv run python -m pytest tests/ -q` 通过
- [ ] `uv run ruff check .` 通过

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| SessionState compat 字段移除破坏现有代码 | 先 grep 所有引用点，逐一迁移 |
| AgentRunResult 改接口影响 test fixtures | 用可选字段 `turn_contexts`，默认空列表 |
| live eval 调用真实 API 消耗 token | live eval 仅手动触发，不进入 CI |
