# Long-Term Optimization Path

日期：2026-06-14

## 目标

这份文档承接 `docs/superpowers/plans/2026-06-13-llm-agent-tool-calling-architecture.md` 中 Phase 1-6 的完成态，定义下一阶段的长期优化路线。

核心目标不再是“把旧 deterministic pipeline 迁移到 LLM tool-calling runtime”，而是把已经迁移完成的系统继续打磨成一个边界清晰、可评估、可回放、可演示、可扩展的 Agent 工程作品。

长期优化原则：

1. **Runtime 单一，Harness 多样**：生产 runtime 始终只保留 LLM tool-calling 主路径；离线演示、scripted eval、trace replay 都是显式 harness。
2. **安全边界优先于通过率**：任何写操作都必须经过 `ToolGateway`、`WriteActionGuard` 和用户确认。
3. **先观测，再优化**：prompt、tool schema、guard、runtime 的优化必须由 trace、eval report、failure category 支撑。
4. **每个 Phase 都可停止、可验证、可交接**：不要把长期优化写成一次性大重构。

## 当前阶段 Review

截至 2026-06-14，项目已完成 tool-calling 架构迁移的 Phase 1-6。

验证信号：

- `uv run python -m pytest -q`：323 passed，1 warning，4 subtests passed。
- `uv run ruff check .`：All checks passed。
- `uv run python -m app.cli.eval --subset curated_mvp --trials 1 --max-workers 1 --no-progress`：11/11 passed。

已完成的关键能力：

| 能力 | 当前状态 | 证据 |
|------|----------|------|
| Tool-calling provider contract | 已完成 | `ToolCallRequest`, `ToolCallResponse`, `LLMProvider.chat_with_tools()` |
| Tool schema 自动生成 | 已完成 | `ToolRegistry.tool_schemas_for_llm()` |
| LLM agent loop | 已完成 | `AgentLoop.run_turn()` |
| Runtime 切换 | 已完成 | `AgentRuntime.handle_user_message()` 主路径调用 `AgentLoop` |
| 旧 pipeline 删除 | 已完成 | `pipeline.py`, `plan_handlers.py`, `graph.py` 不再存在 |
| Eval scripted/live 分层 | 已完成 | `--live`, `eval_backend`, token/loop metrics |
| Trace replay harness | 已完成 | `TraceReplayHarness`, `ScriptedToolGateway` |
| Structured guard context | 已完成 | `WriteActionGuardResult.block_context`, `ToolCallRecord.block_context`, JSON guard observation |
| Offline demo harness | 已完成 | `OfflineDemoHarness`, `scripted_offline_demo`, Workbench `compat` |

当前主要漂移点：

| 漂移点 | 影响 | 处理方向 |
|--------|------|----------|
| `scripted_tool_loop` 目前只有命名契约 | 还不能用 scripted provider 直接驱动 AgentLoop 做 deterministic tool-loop eval | Phase 9/10 视 baseline 需要接入 |
| trace/workbench 仍展示 `compat.current_intent`, `compat.slots`, `compat.policy_decision` | 旧字段已隔离，但 portfolio 展示时仍需避免误读为 runtime 业务状态 | Phase 9 文档和 failure taxonomy 中继续标注 |
| `AgentLoop` 有 auto-load 和 premature-refusal correction | 提升安全和通过率，但比“全由 LLM 选择工具”更保守 | Phase 10 把它们文档化并用 eval 监控 |

## Phase Review 协议

每个后续 Phase 结束时，都必须写一段 phase review。review 不只是“测试通过”，还要回答架构是否更清晰、风险是否降低。

建议 review 模板：

```markdown
## Phase N Review

### 目标

- 本 phase 原本要解决什么问题。

### 完成内容

- 修改了哪些模块。
- 新增了哪些 contract、artifact 或 CLI 能力。

### 架构边界检查

- 是否保持 production runtime 单一路径。
- 是否把 harness/demo/eval/replay 明确隔离。
- 是否新增了 runtime 内的规则分支；如果新增，为什么安全且必要。

### 安全检查

- 写工具是否仍全部经过 gateway + guard + confirmation。
- guard block 是否保持 no-write invariant。
- confirmation 后是否重新校验 guard。

### Eval / Trace 证据

- 运行的测试命令和结果。
- scripted eval 结果。
- live eval 或 replay 结果。
- 新增 artifact 示例路径。

### 未解决问题

- 本 phase 有意留下什么债。
- 下一 phase 要优先处理什么。
```

## Phase 7：Runtime / Harness Boundary Hardening

### 目标

把生产 runtime、offline demo、scripted eval、trace replay 的边界彻底切清。Phase 7 不是为了新增能力，而是为了避免架构回潮。

### 现状 Review

当前 `AgentRuntime.handle_user_message()` 已经具备正确的生产安全行为：没有 provider 且非 `offline_demo` 时安全转人工，不执行规则写操作。问题在于 `offline_demo` 的 intent 解析和 `_det_call()` 仍在 `runtime.py` 中，文件职责变宽。

当前 scripted eval 默认构造 `DeterministicProvider()` 并开启 `offline_demo=True`。这对 CI smoke 很实用，但 backend 名称和 report 解释应更精确。

### 建议变更

1. 新增 `app/agent/offline_demo.py`：
   - 移动 `_offline_demo_intent()`、`_det_call()`、地址解析和 demo-only 正则。
   - 暴露 `OfflineDemoHarness.handle(session, content) -> str | None`。
2. `AgentRuntime` 只保留：
   - provider 构造。
   - pre-flight confirmation。
   - pre-flight identity。
   - 调用 `AgentLoop` 或显式调用 `OfflineDemoHarness`。
3. eval backend 命名细化：
   - `scripted_offline_demo`：当前 curated CI smoke。
   - `scripted_tool_loop`：未来用 `ScriptedToolCallingProvider` 直接驱动 AgentLoop。
   - `live`：真实 provider。
   - `replay`：trace replay。
4. Workbench mode 保留 `offline_demo` 和 `llm`；legacy `"deterministic"` 只作为输入兼容，不作为输出模式。
5. trace/workbench 中旧字段改为 compat 区域：
   - `compat.current_intent`
   - `compat.slots`
   - `compat.policy_decision`
   或从新 UI 中隐藏。

### 验收标准

- `app/agent/runtime.py` 不再包含 demo intent/parser 大段逻辑。
- `AgentRuntime` 生产路径仍为 pre-flight -> AgentLoop -> gateway/guard -> post-processing。
- 无 API key 且未开启 `offline_demo` 时，写操作不会执行。
- README、portfolio 文档和 eval report 明确说明 scripted/offline demo 不代表 live LLM 能力。
- 全量 pytest、ruff、curated scripted eval 通过。

### Phase Review 重点

- 是否真的降低了 runtime 文件的职责复杂度。
- 是否没有把 demo harness 伪装成 production fallback。
- 是否让 eval backend 的语义更精确。

## Phase 7 Review

### 目标

- 把 `offline_demo` 规则解析从 `AgentRuntime` 中拆出。
- 明确 `scripted_offline_demo` / `scripted_tool_loop` / `live` / `replay` 的 backend 语义。
- 让 trace 和 Workbench 中的旧架构字段只以 compat 形式存在。

### 完成内容

- 新增 `app/agent/offline_demo.py`，引入 `OfflineDemoHarness.handle(session, content)` 承载 demo-only parser、确认流和工具执行包装。
- `AgentRuntime` 只保留 provider 构造、pre-flight confirmation、pre-flight identity、`AgentLoop` 调用和显式 harness 分流。
- `CuratedEvalRunner`、`EvalCaseResult`、`EvalRunSummary` 的 `eval_backend` 命名更新为 `scripted_offline_demo`、`scripted_tool_loop`、`live`、`replay`。
- `app/workbench/snapshot.py` 和 `app/ops/tracing.py` 将 `current_intent`、`slots`、`policy_decision` 下沉到 `compat` 区域；Workbench 类型与 UI 同步读取 `compat`。
- README 与 portfolio 文档明确说明 offline demo/scripted 结果不是 live LLM 能力证明。

### 架构边界检查

- production runtime 仍保持单一路径：pre-flight -> `AgentLoop` -> `ToolGateway` / `WriteActionGuard` -> post-processing。
- demo harness 现在是显式模块，而不是 runtime 文件内的隐式 fallback。
- Workbench mode 继续只输出 `offline_demo` 和 `llm`；legacy `"deterministic"` 仅作为输入兼容。

### 安全检查

- 无 provider 且未开启 `offline_demo` 时，runtime 仍然安全转人工，不执行写操作。
- 所有写工具仍经由 `ToolGateway` 和 `WriteActionGuard`。
- confirmation pre-flight 和确认后的再次 guard 校验未变。

### Eval / Trace 证据

- `uv run python -m pytest tests/test_runtime_phase4.py -q`
- `uv run python -m pytest tests/test_eval_runner.py -q`
- `uv run python -m pytest tests/test_workbench_snapshot.py tests/test_workbench_session.py tests/test_workbench_api.py tests/test_workbench_cases.py -q`
- 后续验收命令：`uv run python -m pytest -q`、`uv run ruff check .`、`uv run python -m app.cli.eval --subset curated_mvp --trials 1 --max-workers 1 --no-progress`、`uv run python -m app.cli.eval --subset curated_mvp --trials 1 --max-workers 1 --no-progress --live`

### 未解决问题

- `scripted_tool_loop` 目前只有命名契约，尚未接入真正的 scripted tool-calling provider。
- Workbench 仍展示 compat 信息，但这些字段已被明确隔离，不再伪装为 runtime 业务真相。

## Phase 8：Structured Guard Context

### 目标

补齐设计文档中尚未实现的 `WriteActionGuardResult.block_context`，让 guard block 变成可解释、可回放、可评估的结构化 observation。

### 现状 Review

当前 guard 返回 `block_reason`、`missing_requirements` 等字段，但 `AgentLoop` 给 LLM 的 tool observation 主要是字符串：

```text
Tool cancel_pending_order was blocked: ownership_violation.
Explain this to the user and suggest alternatives.
```

这能工作，但不利于 live eval 失败归因，也不利于 LLM 生成稳定、具体、可行动的回复。

### 建议变更

1. 扩展 `WriteActionGuardResult`：

```python
block_context: dict[str, Any] = field(default_factory=dict)
```

2. 每类 block reason 提供最小结构化上下文：

| Block reason | block_context |
|--------------|---------------|
| `authentication_required` | `{"required": "authenticated_user"}` |
| `ownership_violation` | `{"resource_type": "order", "resource_id": "...", "authenticated_user_id": "...", "owner_user_id": "..."}` |
| `read_before_write_required` | `{"required_read_tool": "get_order_details", "resource_id": "..."}` |
| `explicit_confirmation_required` | `{"confirmation_required": true, "summary": "..."}` |
| policy block | `{"policy_area": "...", "current_state": {...}, "allowed_values": [...]}` |
| lock conflict | `{"existing_locks": [...], "new_lock": "..."}` |

3. `ToolGateway` 将 `block_context` 写入 `ToolCallRecord.observation` 或新增字段。
4. `AgentLoop` 的 `ToolExecutionError.message_for_llm` 引用结构化 context，而不是只拼接字符串。
5. trace artifact 和 Workbench timeline 显示 block context。

### 验收标准

- 每个 guard block 的 trace 能看到 `block_reason` 和 `block_context`。
- LLM 收到的 guard block observation 是 JSON，可被 replay。
- ownership、read-before-write、policy、lock 至少各有一个测试覆盖。
- no-write invariant 不变：blocked write 的 before/after DB hash 相同。

### Phase Review 重点

- block context 是否足够解释用户可见回复。
- 是否泄漏了不该给用户的信息，例如其他用户的敏感数据。
- 是否降低了 live eval 中“guard 正确但回复差”的失败率。

## Phase 8 Review

### 目标

让 guard block 从字符串 reason 升级为可解释、可回放、可评估的结构化 observation，同时保持写操作安全边界不变。

### 完成内容

- `WriteActionGuardResult` 新增 `block_context`，覆盖 authentication、ownership、read-before-write、explicit confirmation、policy block、lock conflict 等主要拒绝路径。
- `ToolGateway` 将 guard block 写成结构化 observation，并同步保存到 `ToolCallRecord.block_context`、trace artifact、replay harness 和 Workbench timeline。
- `AgentLoop` 给 LLM 的 guard-block tool message 现在是 JSON `ToolExecutionError`，包含 `error_type=guard_blocked`、`message_for_llm`、`retryable=false` 和 `block_context`。
- tool observation formatter 将 `block_reason` 和 `block_context` 提升到大 payload 前面，避免上下文在长 observation 中被淹没。

### 架构边界检查

- production runtime 仍保持单一路径：pre-flight -> `AgentLoop` -> `ToolGateway` / `WriteActionGuard` -> post-processing。
- `block_context` 的 source of truth 是 guard result；gateway、agent loop、trace、replay、Workbench 只做传播和展示，没有新增并行 guard/error 模型。
- replay harness 继续使用 recorded `ToolCallRecord`，因此可复现 blocked observation，不需要重新执行真实写工具。

### 安全检查

- blocked write 仍由 `ToolGateway` 在工具执行前短路，no-write invariant 不变。
- `block_context` 只保存最小解释字段：resource type/id、认证用户、owner id、required read、confirmation summary、policy area/current state/allowed values、lock ids；不放完整订单、用户、支付或地址 payload。
- LLM 收到的 context 用于解释安全下一步，不能绕过 `WriteActionGuard` 的最终裁决。

### 验证证据

- Targeted pytest 覆盖 guard、gateway、agent loop、trace/replay、Workbench、observation formatter。
- Full pytest、ruff、curated MVP scripted eval、curated MVP live eval 作为 Phase 8 出口验证。

### 后续风险

- live eval 中仍需继续观察“guard 正确但回复差”的失败率；Phase 9 应把这类 case 纳入 failure taxonomy。
- `AgentLoop` 的 auto-load 与 premature-refusal correction 仍是有意的保守策略，Phase 10 需要继续文档化并用 live eval 监控。

## Phase 9：Live Eval Baseline and Failure Taxonomy

### 目标

建立真实模型能力基线。Phase 9 的重点不是马上提高通过率，而是让每一次 live eval 失败都能被准确归因。

### 现状 Review

当前 scripted eval 稳定，live eval 能通过 `--live` 触发，但 live 结果和 scripted 结果之间还缺一层更强的分析契约。现有 failure label 偏 eval 断言层，缺少 prompt/schema/model/provider/data/policy 的工程归因。

### 建议变更

1. 固定 live subsets：
   - `live_smoke_core`：lookup、cancel、return、exchange、wrong-user、confirmation。
   - `live_guard_smoke`：核心 guard block。
   - `tau_retail_supported_live`：面向 tau supported task 的长期趋势集。
2. eval report 增加：
   - `model`
   - `provider`
   - `prompt_hash`
   - `tool_schema_hash`
   - `action_specs_hash`
   - `eval_backend`
   - `llm_loop_iterations`
   - `token_usage`
   - `tool_call_count`
   - `guard_block_count`
3. 新增 failure root cause：
   - `runtime_bug`
   - `tool_schema_gap`
   - `prompt_gap`
   - `model_reasoning_gap`
   - `guard_policy_gap`
   - `data_fixture_gap`
   - `provider_error`
   - `expected_behavior_unclear`
4. 增加 live eval comparison：
   - baseline vs candidate。
   - 按 case_id 比较 tool calls、guard blocks、final DB state、assistant response。
5. 生成 triage bundle：
   - failing trace path。
   - user messages。
   - LLM responses。
   - tool calls。
   - guard context。
   - DB assertion diff。

### 验收标准

- 跑完 live eval 后，每个失败 case 都有 root cause。
- report 能回答“这是代码回归，还是 prompt/model/provider 波动”。
- live eval 不进入普通 CI gate，但可以作为 manual、nightly、release smoke。
- 有一份稳定 baseline artifact 可用于后续比较。

### Phase Review 重点

- failure category 是否可操作，而不是只描述现象。
- live 波动是否被隔离，不影响常规 CI。
- 是否避免为了通过 live eval 在 runtime 中新增 case-specific parser。

## Phase 9 Review

### 目标

- 固定 live eval baseline subsets。
- 让 live eval report 说明 model/provider/prompt/tool/action-spec identity。
- 让失败 case 输出 actionable root cause 和 triage bundle。

### 完成内容

- 新增 `live_smoke_core` 和 `live_guard_smoke` subsets，分别覆盖核心 live happy path / confirmation / wrong-user 以及核心 guard block。
- eval report 新增 `baseline_metadata`，包含 `model`、`provider`、`prompt_hash`、`tool_schema_hash`、`action_specs_hash` 和 `eval_backend`。
- report metrics 汇总 `total_token_usage` 与 `average_llm_loop_iterations`；per-case result 保留 `llm_token_usage`、`llm_loop_iterations`、`tool_call_count`、`guard_blocks`。
- live triage 新增 root cause taxonomy，并从 trace 中生成 triage bundle：user messages、assistant messages、LLM responses、tool calls、guard context、DB assertion diff。

### 架构边界检查

- production runtime 未新增 case-specific parser。
- Phase 9 只扩展 eval/report/triage surfaces，不改变 `AgentLoop`、`ToolGateway` 或 `WriteActionGuard` 的裁决路径。
- live eval 仍是 manual/release smoke，不进入普通 CI gate。

### 验证证据

- `uv run ruff check .`
- `uv run python -m pytest -q`
- `uv run python -m app.cli.eval --subset curated_mvp --trials 1 --max-workers 1 --no-progress`
- `uv run python -m app.cli.eval --subset curated_mvp --trials 1 --max-workers 1 --no-progress --live`
- `uv run python -m app.cli.eval --subset live_smoke_core --trials 1 --max-workers 1 --no-progress --live`
- `uv run python -m app.cli.eval --subset live_guard_smoke --trials 1 --max-workers 1 --no-progress --live`

### 后续风险

- Phase 10 才优化 prompt/tool schema；Phase 9 只负责观测和归因。
- live eval 的失败要先通过 `app.eval.live_triage` 归因，不能直接解释为代码回归。
- `scripted_tool_loop` 仍是命名契约，后续若需要 deterministic tool-loop baseline 再接入 scripted provider。

## Phase 10：Prompt and Tool Schema Optimization

### 目标

基于 Phase 9 的真实失败样本优化 prompt、tool schema 和 state summary，减少错工具、缺参数、无谓拒绝和回复不稳定。

### 现状 Review

当前 prompt 已能驱动 tool-calling runtime；tool schemas 从 registry/action specs 生成。`AgentLoop` 还有 auto-load 和 premature-refusal correction，这些兜底说明模型在部分场景下仍可能没有严格按“先读后写、让 guard 裁决”的理想路径行动。

### 建议变更

1. Tool description 从“功能说明”升级为“选择策略”：
   - when to use。
   - when not to use。
   - required prior reads。
   - guard block 后如何解释。
2. 参数 schema 加强：
   - enum。
   - list item 类型。
   - optional vs required 的明确表达。
   - payment method、shipping method、cancel reason 的约束。
3. state summary 增强：
   - authenticated user。
   - loaded orders/users。
   - pending action。
   - write locks。
   - recent guard block。
   - recent tool error。
4. prompt regression harness：
   - 同一 case 在 prompt 改动前后比较 tool call 序列和 final state。
   - prompt hash 进入 eval report。
5. 把 auto-load 和 premature-refusal correction 纳入指标：
   - `auto_load_count`
   - `premature_refusal_corrected_count`
   - 长期目标是下降，而不是无限依赖。

### 验收标准

- live smoke 的 wrong_tool / missing_required_args 明显下降。
- prompt 改动有 replay 或 live smoke 证据。
- tool schema hash 变化能在 report 中追踪。
- runtime 不新增面向具体 case 的 intent parser。

### Phase Review 重点

- 优化是否来自失败样本，而不是凭感觉改 prompt。
- schema 是否仍从单一事实来源派生。
- auto-load/correction 是否被监控，而不是悄悄扩大。

### Phase 10 Review

Phase 10 将优化收敛在 LLM 可见契约，而不是新增 case-specific intent parser：

- `ToolRegistry.tool_schemas_for_llm()` 的 description 从功能说明升级为选择契约，包含 when to use、when not to use、required prior reads 和 guard block 后的解释方式。
- 参数 schema 继续从 registry/action specs 派生，并补强 `order_id`、`item_ids`、`new_item_ids`、`payment_method_id` 的 pattern 约束，保留已有 enum、required 和 `additionalProperties: false`。
- `ContextBuilder` 的 state summary 新增 recent guard block 和 recent tool error，让模型下一轮能基于最近失败信号修正行为。
- eval report metrics 新增 `auto_load_count` 和 `premature_refusal_corrected_count`，用于长期监控 runtime 兜底依赖是否下降。

验证重点：

- `tool_schema_hash` 会随 schema/description contract 变化进入 Phase 9 baseline metadata。
- live smoke 需要继续观察 pass rate、token usage、tool call count、`auto_load_count` 和 `premature_refusal_corrected_count`。
- Phase 11 可以基于这些指标做 trace compare/workbench，不需要先扩 tau coverage。

2026-06-15 验证结果：

- `curated_mvp` scripted：11/11，通过。
- `curated_mvp` live：11/11，`total_tokens=72484`，`auto_load_count=0`，`premature_refusal_corrected_count=0`。
- `live_smoke_core` live：6/6，`total_tokens=40003`，`auto_load_count=0`，`premature_refusal_corrected_count=0`。
- `live_guard_smoke` live：3/3，`total_tokens=19777`，`auto_load_count=0`，`premature_refusal_corrected_count=0`。

## Phase 11：Replay Debugger and Workbench AgentOps

### 目标

把 trace replay 从测试能力升级成日常调试工具，让失败 case 可以快速定位、复现和比较。

### 现状 Review

`TraceReplayHarness` 已能从 trace artifact 提取 LLM responses 和 tool results，驱动 `AgentLoop` 回放。Workbench 已能展示 timeline、tool results、audit logs，但还不是完整的 AgentOps 调试台。

### 建议变更

1. Replay CLI：
   - replay single trace。
   - replay trace directory。
   - replay one turn。
   - fail fast on tool mismatch。
2. Trace compare：
   - compare two traces for same case。
   - diff messages、LLM responses、tool calls、guard blocks、DB hashes、assistant final response。
3. Workbench replay mode：
   - load trace artifact。
   - inspect turn-by-turn LLM response。
   - inspect tool observation。
   - inspect guard context。
   - inspect state diff。
4. Eval report browser：
   - list cases。
   - filter by failure category。
   - open trace。
   - open replay。
5. Triage bundle：
   - one directory per failure case。
   - includes report excerpt、trace、prompt metadata、DB diff。

### 验收标准

- 一个 failed live case 可以在 2-3 分钟内定位到 root cause。
- trace compare 能解释 prompt/schema/runtime 改动导致的行为差异。
- Workbench 能查看 replay trace，不只运行预设 case。
- replay 不执行真实 write tool；所有工具结果来自 recorded trace。

### Phase Review 重点

- replay 是否忠实复现原始 turn。
- Workbench 是否仍保持演示清晰，不被调试功能压垮。
- trace artifact schema 是否保持向后兼容。

## Phase 12：Capability Expansion and Tau Coverage

### 目标

在架构边界、guard context、live eval 和 replay 调试都稳定后，再扩大 tau retail task 支持率。

### 现状 Review

原设计背景提到 full tau ingestion 后，系统支持 69 个 tau retail supported task 中的 32 个。当前项目已经具备核心写操作和 guard 架构，但要提高 tau 覆盖率，不能回到硬编码 intent/slot 分支。

### 建议变更

1. Tau task gap analysis：
   - task 缺工具。
   - task 有工具但 schema 不足。
   - task 有 schema 但 prompt 不稳定。
   - task 被 guard policy 正确拒绝。
   - task 数据 fixture 不支持。
2. 按能力族扩展：
   - order lookup。
   - cancellation。
   - address/payment/shipping modification。
   - returns。
   - exchanges。
   - unsupported transfer。
3. 新增能力优先顺序：
   - 先补 read/tool/schema gap。
   - 再补 guard policy。
   - 最后补 prompt examples。
4. Synthetic variation：
   - 同一能力族生成语言变体。
   - 变换信息顺序。
   - 多轮补充缺失参数。
   - confirmation 改口。
5. 目标阶梯：
   - 稳定 40+/69。
   - 稳定 50+/69。
   - 冲刺 55+/69。

### 验收标准

- tau coverage 提升不依赖 runtime case-specific parser。
- 每个新增支持能力至少有 scripted case、live smoke 或 replay evidence。
- mutation_error_rate 保持 0。
- guard block no-write invariant 保持 100%。

### Phase Review 重点

- 覆盖率提升来自工具/schema/prompt/guard，而不是旧式 routing。
- 新能力没有扩大写风险。
- synthetic 变体是否真的覆盖表达泛化，而不是重复 happy path。

## Phase 13：Portfolio and Release Hardening

### 目标

把项目打磨成可长期展示和面试讲解的稳定作品。

### 现状 Review

README、portfolio architecture 和 Workbench 已经有较好的作品集结构。下一步是让“打开即懂、运行即有证据、深入能讲清”的体验更稳定。

### 建议变更

1. README 增加最新 verified metrics：
   - pytest count。
   - curated eval pass rate。
   - live smoke latest result。
2. Portfolio architecture 增加：
   - runtime/harness boundary diagram。
   - guard block context example。
   - live eval triage example。
   - replay compare example。
3. Demo artifacts 固化：
   - one successful write trace。
   - one guard block trace。
   - one confirmation denied trace。
   - one live failure triage bundle。
4. Release checklist：
   - tests。
   - ruff。
   - scripted eval。
   - live smoke if API key available。
   - docs links valid。
   - screenshots updated。

### 验收标准

- README 中所有链接有效，包括本路线图。
- 新人可以按 README 在 10 分钟内跑起 Workbench。
- 面试讲解能从 README 进入 portfolio architecture，再进入 trace evidence。
- 文档不夸大 scripted/offline demo 为 live LLM 能力。

### Phase Review 重点

- 项目叙事是否准确，不把 harness 成果包装成 production LLM 能力。
- demo 是否稳定。
- 文档和代码是否同步。

## 推荐执行顺序

推荐先做：

1. Phase 10：Prompt and Tool Schema Optimization。
2. Phase 11-13：在 Phase 9/10 的 baseline 稳定后扩展 tau coverage。

Phase 7、Phase 8 和 Phase 9 已完成，是后续所有增长的地基。Phase 11-13 可以穿插推进，但不建议在 Phase 10 prompt/schema baseline 前大规模扩 tau coverage。

## 下一份实施计划建议

下一份可执行 plan 建议聚焦 Phase 10，文件命名：

`docs/superpowers/plans/2026-06-14-phase10-prompt-tool-schema-optimization.md`

Phase 10 plan 应拆成这些任务：

1. 基于 Phase 9 live triage 结果挑选 prompt/schema 优化目标。
2. 强化 tool descriptions 的 when-to-use / when-not-to-use / guard-block explanation。
3. 强化参数 schema 的 enum、required/optional、list item constraints。
4. 比较 prompt/schema hash 变化前后的 scripted/live baseline。
5. 跑 full pytest、ruff、curated scripted eval、curated live eval、`live_smoke_core` 和 `live_guard_smoke`。
