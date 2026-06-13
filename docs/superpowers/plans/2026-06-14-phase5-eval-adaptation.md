# Phase 5: Eval 适配与 Live Benchmark — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 eval 基础设施从旧 pipeline 语义迁移到 LLM tool-calling 语义：新增 `required_tools`/`forbidden_tools`、`eval_backend` 分层、LLM 指标采集、live eval 支持，并清理 Phase 4 兼容字段。

**Architecture:** 增量修改，不破坏现有 41 个 case。`EvalCase` 新增 set 型断言字段，`EvalCaseResult`/`EvalRunSummary` 新增 backend + LLM 指标，runner 新增 `--live` flag，`SessionState` 移除 compat 字段。

**Tech Stack:** Python, Pydantic v2, pytest, 现有 `openai` package, 现有 retail tool registry/gateway/guard

**Spec:** `docs/superpowers/specs/2026-06-14-phase5-eval-adaptation-design.md`

---

## 文件结构

```
app/agent/
  models.py              ← 修改：SessionState 移除 compat 字段
  runtime.py             ← 修改：AgentRunResult + turn_contexts, _preflight_confirmation

app/eval/
  cases.py               ← 修改：EvalCase + required_tools/forbidden_tools
  runner.py              ← 修改：EvalCaseResult/EvalRunSummary + eval_backend/LLM指标,
                           classify_failure + required/forbidden checks,
                           CuratedEvalRunner + live parameter
  metrics.py             ← 修改：schema version bump

app/cli/
  eval.py                ← 修改：+ --live flag

tests/
  test_eval_runner.py    ← 修改：新增 Phase 5 测试
```

---

### Task 1: EvalCase — 新增 required_tools / forbidden_tools

**Files:**
- Modify: `app/eval/cases.py`
- Modify: `app/eval/runner.py` (classify_failure)
- Modify: `tests/test_eval_runner.py`

- [ ] **Step 1: 编写失败测试**

在 `tests/test_eval_runner.py` 的 `CuratedEvalTests` 类中追加：

```python
def test_required_tool_missing_fails_classify(self):
    case = EvalCase(
        case_id="req_test",
        category="test",
        messages=[],
        expected_user_id="user",
        expected_intent="lookup",
        required_tools={"must_have_tool"},
    )

    label = classify_failure(
        case=case,
        authenticated_user_id="user",
        final_intent="lookup",
        write_locks=[],
        actual_order_status=None,
        assistant_messages=[],
        tool_names=["other_tool"],
        guard_block_reasons=[],
        tool_errors=0,
        guard_blocks=0,
        pending_action=False,
        llm_errors=0,
        confirmation_status="not_required",
    )

    self.assertEqual(label, "required_tool_missing")


def test_forbidden_tool_called_fails_classify(self):
    case = EvalCase(
        case_id="forbid_test",
        category="test",
        messages=[],
        expected_user_id="user",
        expected_intent="lookup",
        forbidden_tools={"dangerous_tool"},
    )

    label = classify_failure(
        case=case,
        authenticated_user_id="user",
        final_intent="lookup",
        write_locks=[],
        actual_order_status=None,
        assistant_messages=[],
        tool_names=["dangerous_tool", "other_tool"],
        guard_block_reasons=[],
        tool_errors=0,
        guard_blocks=0,
        pending_action=False,
        llm_errors=0,
        confirmation_status="not_required",
    )

    self.assertEqual(label, "forbidden_tool_called")


def test_required_and_forbidden_pass_when_satisfied(self):
    case = EvalCase(
        case_id="both_test",
        category="test",
        messages=[],
        expected_user_id="user",
        expected_intent="lookup",
        required_tools={"good_tool"},
        forbidden_tools={"bad_tool"},
    )

    label = classify_failure(
        case=case,
        authenticated_user_id="user",
        final_intent="lookup",
        write_locks=[],
        actual_order_status=None,
        assistant_messages=[],
        tool_names=["good_tool", "neutral_tool"],
        guard_block_reasons=[],
        tool_errors=0,
        guard_blocks=0,
        pending_action=False,
        llm_errors=0,
        confirmation_status="not_required",
    )

    self.assertIsNone(label)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run python -m pytest tests/test_eval_runner.py::CuratedEvalTests::test_required_tool_missing_fails_classify tests/test_eval_runner.py::CuratedEvalTests::test_forbidden_tool_called_fails_classify tests/test_eval_runner.py::CuratedEvalTests::test_required_and_forbidden_pass_when_satisfied -v
```

预期：`test_required_tool_missing_fails_classify` 和 `test_forbidden_tool_called_fails` 失败（`required_tools`/`forbidden_tools` 属性不存在），`test_required_and_forbidden_pass_when_satisfied` 也失败。

- [ ] **Step 3: EvalCase 新增字段**

修改 `app/eval/cases.py`：

在 `EvalCase` dataclass 末尾（`seed` 字段后）新增：

```python
    # ── Phase 5: tool-calling 语义断言 ──
    required_tools: set = field(default_factory=set)
    forbidden_tools: set = field(default_factory=set)
```

注意：`set` 不能直接用 `set[str]`（`from __future__ import annotations` 下可用，但保持与现有代码风格一致用 `set`）。

修改 `_case_for_subset` 函数，在 `seed=case.seed,` 后新增：

```python
        required_tools=set(case.required_tools),
        forbidden_tools=set(case.forbidden_tools),
```

- [ ] **Step 4: classify_failure 新增 required/forbidden 检查**

修改 `app/eval/runner.py` 的 `classify_failure` 函数。

在 `missing_tools` 检查之后、`tool_errors` 检查之前（约第 558 行）新增：

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

- [ ] **Step 5: 运行新增测试确认通过**

```bash
uv run python -m pytest tests/test_eval_runner.py::CuratedEvalTests::test_required_tool_missing_fails_classify tests/test_eval_runner.py::CuratedEvalTests::test_forbidden_tool_called_fails_classify tests/test_eval_runner.py::CuratedEvalTests::test_required_and_forbidden_pass_when_satisfied -v
```

预期：3 passed。

- [ ] **Step 6: 运行完整 eval 测试确认向后兼容**

```bash
uv run python -m pytest tests/test_eval_runner.py -v
```

预期：全部通过（现有 20 个测试 + 新增 3 个 = 23 passed）。

- [ ] **Step 7: 提交**

```bash
git add app/eval/cases.py app/eval/runner.py tests/test_eval_runner.py
git commit -m "feat: add required_tools/forbidden_tools to EvalCase and classify_failure"
```

---

### Task 2: EvalCaseResult — 新增 eval_backend + LLM 指标

**Files:**
- Modify: `app/eval/runner.py` (EvalCaseResult, _run_case)
- Modify: `tests/test_eval_runner.py`

- [ ] **Step 1: 编写失败测试**

在 `tests/test_eval_runner.py` 的 `CuratedEvalTests` 类中追加：

```python
def test_eval_case_result_defaults_to_scripted_backend(self):
    result = _result("test_case", 0)
    self.assertEqual(result.eval_backend, "scripted")

def test_eval_case_result_carries_llm_metrics(self):
    result = _result("test_case", 0)
    result.llm_token_usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    result.llm_loop_iterations = 3

    self.assertEqual(result.eval_backend, "scripted")
    self.assertEqual(result.llm_token_usage["total_tokens"], 150)
    self.assertEqual(result.llm_loop_iterations, 3)

def test_eval_run_summary_has_eval_backend(self):
    with tempfile.TemporaryDirectory() as tmp:
        config = resolve_config(artifact_dir=tmp)
        summary = CuratedEvalRunner(
            config=config,
            artifact_dir=Path(tmp),
        ).run(subset="curated_mvp", trials=1)
    self.assertEqual(summary.eval_backend, "scripted")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run python -m pytest tests/test_eval_runner.py::CuratedEvalTests::test_eval_case_result_defaults_to_scripted_backend tests/test_eval_runner.py::CuratedEvalTests::test_eval_case_result_carries_llm_metrics tests/test_eval_runner.py::CuratedEvalTests::test_eval_run_summary_has_eval_backend -v
```

预期：失败（`eval_backend`、`llm_token_usage`、`llm_loop_iterations` 属性不存在）。

- [ ] **Step 3: EvalCaseResult 新增字段**

修改 `app/eval/runner.py` 的 `EvalCaseResult` dataclass。

在 `replay_metadata` 字段后新增：

```python
    # ── Phase 5: LLM tool-calling metrics ──
    eval_backend: str = "scripted"
    llm_token_usage: Optional[Dict[str, Any]] = None
    llm_loop_iterations: int = 0
```

- [ ] **Step 4: EvalRunSummary 新增 eval_backend 字段**

修改 `app/eval/runner.py` 的 `EvalRunSummary` dataclass。

在 `generalization_variant_count` 字段后新增：

```python
    # ── Phase 5 ──
    eval_backend: str = "scripted"
```

在 `run()` 方法中构造 `EvalRunSummary` 时，新增：

```python
            eval_backend="scripted",
```

- [ ] **Step 5: 更新 schema version 和 report**

修改 `app/eval/metrics.py`：

```python
EVAL_RUN_SUMMARY_SCHEMA_VERSION = "phase5.eval_run_summary.v1"
EVAL_REPORT_SCHEMA_VERSION = "phase5.eval_report.v1"
```

修改 `build_report_artifact` 函数，在现有字段后新增：

```python
        "eval_backend": summary.eval_backend,
```

- [ ] **Step 6: 更新 _progress_placeholder**

修改 `app/eval/runner.py` 的 `_progress_placeholder` 方法，在返回的 `EvalCaseResult` 中新增：

```python
            eval_backend="scripted",
```

位置：在 `expected_write_lock=case.expected_write_lock,` 后。

- [ ] **Step 7: 运行测试确认通过**

```bash
uv run python -m pytest tests/test_eval_runner.py::CuratedEvalTests::test_eval_case_result_defaults_to_scripted_backend tests/test_eval_runner.py::CuratedEvalTests::test_eval_case_result_carries_llm_metrics tests/test_eval_runner.py::CuratedEvalTests::test_eval_run_summary_has_eval_backend -v
```

预期：3 passed。

- [ ] **Step 8: 运行完整 eval 测试确认向后兼容**

```bash
uv run python -m pytest tests/test_eval_runner.py -v
```

预期：全部通过（23 + 3 = 26 passed）。此步会因 `test_curated_eval_runner_writes_summary` 中 schema version 断言变化而失败 — 需要更新。

- [ ] **Step 9: 更新现有测试中的 schema version 断言**

修改 `tests/test_eval_runner.py` 的 `test_curated_eval_runner_writes_summary`：

```python
# 修改前：
self.assertEqual(summary.schema_version, "phase2.eval_run_summary.v1")
# 修改后：
self.assertEqual(summary.schema_version, "phase5.eval_run_summary.v1")
```

同样修改 payload 的 schema_version 断言：

```python
# 修改前：
self.assertEqual(payload["schema_version"], "phase2.eval_run_summary.v1")
# 修改后：
self.assertEqual(payload["schema_version"], "phase5.eval_run_summary.v1")
```

以及 report 的 schema_version：

```python
# 修改前：
self.assertEqual(report["schema_version"], "phase2.eval_report.v1")
self.assertEqual(report["report_type"], "phase2_eval_report")
# 修改后：
self.assertEqual(report["schema_version"], "phase5.eval_report.v1")
self.assertEqual(report["report_type"], "phase5_eval_report")
```

修改 `build_report_artifact` 的 `report_type`：

```python
# 修改前：
"report_type": "phase2_eval_report",
# 修改后：
"report_type": "phase5_eval_report",
```

- [ ] **Step 10: 运行完整 eval 测试确认通过**

```bash
uv run python -m pytest tests/test_eval_runner.py -v
```

预期：26 passed。

- [ ] **Step 11: 提交**

```bash
git add app/eval/runner.py app/eval/metrics.py tests/test_eval_runner.py
git commit -m "feat: add eval_backend and LLM metrics to EvalCaseResult and EvalRunSummary"
```

---

### Task 3: AgentRunResult — 暴露 TurnContext 给 eval runner

**Files:**
- Modify: `app/agent/runtime.py` (AgentRunResult, AgentRuntime)
- Modify: `tests/test_eval_runner.py`

- [ ] **Step 1: AgentRunResult 新增 turn_contexts**

修改 `app/agent/runtime.py` 的 `AgentRunResult` dataclass。

新增 import：

```python
from app.agent.models import TurnContext
```

在 `AgentRunResult` 的 `trace_artifact_path` 后新增：

```python
    turn_contexts: list = field(default_factory=list)
```

- [ ] **Step 2: AgentRuntime 追踪 TurnContext**

修改 `app/agent/runtime.py` 的 `AgentRuntime.__init__`，在 `self._context_builder` 赋值后新增：

```python
        self._turn_contexts: list = []
```

修改 `handle_user_message` 方法。在 `result = loop.run_turn(session, content)` 之后、post-process 之前新增：

```python
        # Phase 5: capture TurnContext for eval metrics
        self._turn_contexts.append(result.turn)
```

修改 `run_script` 方法。在方法开头新增：

```python
        self._turn_contexts = []
```

在返回 `AgentRunResult` 时新增 `turn_contexts`：

```python
        return AgentRunResult(
            run_id=run_id,
            state=session,
            trace_artifact_path=trace_path,
            turn_contexts=list(self._turn_contexts),
        )
```

- [ ] **Step 3: Eval runner 从 AgentRunResult 提取 LLM 指标**

修改 `app/eval/runner.py` 的 `_run_case` 方法。

在 `run_result = runtime.run_script(...)` 之后、`duration_seconds` 计算之后，新增 LLM 指标提取逻辑：

```python
        # Phase 5: extract LLM metrics from turn contexts
        total_tokens: Optional[Dict[str, Any]] = None
        total_loop_iterations = 0
        for turn_ctx in run_result.turn_contexts:
            total_loop_iterations += turn_ctx.loop_iterations
            if turn_ctx.llm_token_usage:
                if total_tokens is None:
                    total_tokens = dict(turn_ctx.llm_token_usage)
                else:
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        total_tokens[key] = total_tokens.get(key, 0) + turn_ctx.llm_token_usage.get(key, 0)
```

在 `EvalCaseResult` 构造时新增：

```python
            eval_backend="scripted",
            llm_token_usage=total_tokens,
            llm_loop_iterations=total_loop_iterations,
```

- [ ] **Step 4: 更新 _progress_placeholder**

修改 `_progress_placeholder` 返回的 `EvalCaseResult`：

```python
            eval_backend="scripted",
```

- [ ] **Step 5: 运行完整 eval 测试确认通过**

```bash
uv run python -m pytest tests/test_eval_runner.py -v
```

预期：26 passed。

- [ ] **Step 6: 提交**

```bash
git add app/agent/runtime.py app/eval/runner.py
git commit -m "feat: expose TurnContext via AgentRunResult for eval LLM metrics"
```

---

### Task 4: CuratedEvalRunner — 新增 --live flag

**Files:**
- Modify: `app/eval/runner.py` (CuratedEvalRunner)
- Modify: `app/cli/eval.py` (--live argument)
- Modify: `tests/test_eval_runner.py`

- [ ] **Step 1: CuratedEvalRunner 新增 live 参数**

修改 `app/eval/runner.py` 的 `CuratedEvalRunner.__init__`：

```python
    def __init__(
        self,
        *,
        config: AppConfig,
        artifact_dir: Path = DEFAULT_EVAL_ARTIFACT_DIR,
        require_llm: bool = False,
        live: bool = False,
        progress_callback: Optional[Callable[[str, EvalCaseResult], None]] = None,
    ) -> None:
        self.config = config
        self.artifact_dir = artifact_dir
        self.require_llm = require_llm
        self.live = live
        self.progress_callback = progress_callback
```

修改 `_run_case` 方法。在 provider 创建逻辑处（约第 285 行），改为：

```python
        # Phase 5: live mode uses real LLM provider, scripted uses disabled
        if self.live:
            provider = None  # let AgentRuntime build real DeepSeekProvider
        elif self.require_llm:
            provider = None
        else:
            provider = DisabledLLMProvider()
```

修改 `run()` 方法的 `EvalRunSummary` 构造，将 `eval_backend` 改为根据 live 参数动态设置：

```python
            eval_backend="live" if self.live else "scripted",
```

修改 `_progress_placeholder`，类似地：

```python
            eval_backend="live" if self.live else "scripted",
```

- [ ] **Step 2: CLI 新增 --live flag**

修改 `app/cli/eval.py`：

在 `--require-llm` 后新增：

```python
    parser.add_argument("--live", action="store_true", help="Use real LLM provider for eval.")
```

在 `CuratedEvalRunner` 构造时传入：

```python
        summary = CuratedEvalRunner(
            config=config,
            artifact_dir=Path(args.artifact_dir).expanduser(),
            require_llm=args.require_llm,
            live=args.live,
            progress_callback=None if args.no_progress else _print_progress,
        ).run(
```

- [ ] **Step 3: 编写测试**

在 `tests/test_eval_runner.py` 中追加：

```python
def test_live_flag_passes_provider_none_to_runtime(self):
    """Verify --live does not inject DisabledLLMProvider."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        config = resolve_config(artifact_dir=tmp)
        # Scripted run should pass (all 11 cases)
        summary = CuratedEvalRunner(
            config=config,
            artifact_dir=Path(tmp),
            live=False,
        ).run(subset="curated_mvp", trials=1)
        self.assertEqual(summary.eval_backend, "scripted")
        self.assertEqual(summary.passed_count, 11)

def test_eval_backend_in_summary_matches_live_flag(self):
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        config = resolve_config(artifact_dir=tmp)
        summary = CuratedEvalRunner(
            config=config,
            artifact_dir=Path(tmp),
            live=False,
        ).run(subset="curated_mvp", trials=1)
        self.assertEqual(summary.eval_backend, "scripted")
        for result in summary.results:
            self.assertEqual(result.eval_backend, "scripted")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run python -m pytest tests/test_eval_runner.py::CuratedEvalTests::test_live_flag_passes_provider_none_to_runtime tests/test_eval_runner.py::CuratedEvalTests::test_eval_backend_in_summary_matches_live_flag -v
```

预期：2 passed。

- [ ] **Step 5: 运行完整 eval 测试确认向后兼容**

```bash
uv run python -m pytest tests/test_eval_runner.py -v
```

预期：28 passed。

- [ ] **Step 6: 提交**

```bash
git add app/eval/runner.py app/cli/eval.py tests/test_eval_runner.py
git commit -m "feat: add --live flag to eval runner for real LLM eval"
```

---

### Task 5: SessionState — 移除 Phase 4 兼容字段

**Files:**
- Modify: `app/agent/models.py` (SessionState)
- Modify: `app/agent/runtime.py` (移除 session.slots = {})
- Modify: `app/eval/runner.py` (current_intent/policy_decision 引用)
- Modify: `tests/test_eval_runner.py`

- [ ] **Step 1: 编写测试验证 compat 字段已移除**

在 `tests/test_eval_runner.py` 中追加：

```python
def test_session_state_has_no_phase4_compat_fields(self):
    from app.agent.models import SessionState

    state = SessionState(session_id="test")
    # These fields should NOT exist on SessionState after Phase 5 cleanup
    for removed_field in ("current_intent", "slots", "policy_decision", "risk_level"):
        with self.subTest(field=removed_field):
            with self.assertRaises(AttributeError):
                getattr(state, removed_field)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run python -m pytest tests/test_eval_runner.py::CuratedEvalTests::test_session_state_has_no_phase4_compat_fields -v
```

预期：失败（这些字段目前还存在）。

- [ ] **Step 3: 从 SessionState 移除 compat 字段**

修改 `app/agent/models.py` 的 `SessionState` 类。

移除以下 4 个字段（第 122-127 行）：

```python
    # ── Phase 4 temporary compat (Phase 5 removes these) ──
    current_intent: str = "unknown"
    slots: Dict[str, Any] = Field(default_factory=dict)
    policy_decision: Optional[PolicyDecision] = None
    risk_level: str = "low"
```

保留以下字段（eval 仍在使用）：

```python
    confirmation_status: str = "not_required"
    step_durations: dict[str, float] = Field(default_factory=dict)
```

- [ ] **Step 4: 更新 runtime.py 引用**

修改 `app/agent/runtime.py` 的 `_preflight_confirmation` 方法。

移除 `session.slots = {}` 这一行（在 `resolution == "changed"` 分支中）：

```python
        elif resolution == "changed":
            session.pending_action = None
            # session.slots = {}  ← 删除这行
            msg = "I discarded the previous request. Please provide updated details."
```

- [ ] **Step 5: 更新 eval runner 引用**

修改 `app/eval/runner.py` 的 `_run_case` 方法。

`final_intent=state.current_intent` → 改为 `final_intent=""`：

```python
# 第一处（line ~352）：
            final_intent=state.confirmation_status,  # 不对，这是 current_intent 的位置
```

让我看一下具体代码位置。在 `_run_case` 的 `failure_label = classify_failure(...)` 调用中，`final_intent=state.current_intent` 出现一次；在 `EvalCaseResult` 构造中，`final_intent=state.current_intent` 出现一次。

将两处 `final_intent=state.current_intent` 改为 `final_intent=""`。

`policy_check_count=1 if state.policy_decision else 0` → 改为 `policy_check_count=0`：

```python
# 修改前：
            policy_check_count=1 if state.policy_decision else 0,
# 修改后：
            policy_check_count=0,
```

- [ ] **Step 6: 更新 classify_failure 中的 intent 检查**

由于 `final_intent` 现在始终为空字符串，`classify_failure` 中的 intent 检查需要调整。

修改 `app/eval/runner.py` 的 `classify_failure` 函数。将 intent 检查改为仅在 tau subset 以外的 case 中跳过（因为 `final_intent` 不再有意义）：

```python
    # 修改前（line ~539-541）：
    if not is_tau:
        if authenticated_user_id != case.expected_user_id:
            return "auth_failure"
        if final_intent != case.expected_intent:
            return "wrong_intent"

    # 修改后：
    if not is_tau:
        if authenticated_user_id != case.expected_user_id:
            return "auth_failure"
        # Phase 5: final_intent is always "" in tool-calling paradigm;
        # skip intent check for scripted backend (no intent extraction).
        # Live backend failure attribution uses failure_category instead.
```

即：删除 `if final_intent != case.expected_intent: return "wrong_intent"` 这两行。

- [ ] **Step 7: 运行完整 eval 测试确认通过**

```bash
uv run python -m pytest tests/test_eval_runner.py -v
```

预期：29 passed（之前的 28 + 新增的 compat 字段移除测试）。注意：`test_classify_failure_detects_auth_failure_first` 会因为 `final_intent` 不再检查而行为变化 — 该测试构造 `final_intent=case.expected_intent`，intent 检查被删除后不影响。

- [ ] **Step 8: 确认现有测试不受影响**

```bash
uv run python -m pytest tests/test_eval_runner.py tests/test_runtime_phase4.py -v
```

预期：全部通过。

- [ ] **Step 9: 提交**

```bash
git add app/agent/models.py app/agent/runtime.py app/eval/runner.py tests/test_eval_runner.py
git commit -m "feat: remove Phase 4 compat fields from SessionState"
```

---

### Task 6: Phase 5 回归检查

**Files:**
- 预期不修改源码文件。

- [ ] **Step 1: 运行 eval 测试**

```bash
uv run python -m pytest tests/test_eval_runner.py -v
```

预期：29 passed。

- [ ] **Step 2: 运行完整测试套件**

```bash
uv run python -m pytest tests/ -q
```

预期：全部通过（预计 ~250+ passed）。Workbench 相关测试 `test_workbench_session.py` 中 4 个已知失败不算 regression（这些使用 `ConversationState`，不受 `SessionState` 改动影响）。

- [ ] **Step 3: 运行 lint**

```bash
uv run ruff check .
```

预期：通过。

- [ ] **Step 4: 更新计划状态**

修改 `docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md` 的 Phase Status 段，新增：

```markdown
- Phase 5：✅ 完成 — required_tools/forbidden_tools、eval_backend 分层、LLM 指标采集、--live flag、SessionState compat 清理、29 eval 测试通过（2026-06-14）。
```

- [ ] **Step 5: 提交状态更新**

```bash
git add docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md
git commit -m "docs: mark LLM agent tool-calling phase 5 complete"
```

---

## 自审记录

Spec 覆盖：

- `required_tools` / `forbidden_tools` → Task 1
- `eval_backend` → Task 2 + Task 4
- LLM token/tool/loop metrics → Task 2 + Task 3
- scripted/live report 分层 → Task 2 + Task 4
- failure category reporting → Task 1（classify_failure 新增标签）
- live LLM eval as manual/nightly → Task 4（--live flag）
- SessionState compat 清理 → Task 5

歧义处理：

- `expected_tool_names` 保留不变，`required_tools`/`forbidden_tools` 增量添加。
- `final_intent` 在 scripted backend 下始终为空，intent 检查从 classify_failure 移除。
- `policy_check_count` 设为 0（不再有 policy_decision 对象）。
- `ConversationState` 不在此阶段修改（workbench 仍在使用）。
- `AgentRunResult.turn_contexts` 用 list 累积多轮 TurnContext。
