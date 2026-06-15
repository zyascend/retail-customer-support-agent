# Phase 11 Workbench AgentOps Design Spec

日期：2026-06-15
状态：待评审

## 目标

在不破坏现有 Workbench 演示能力的前提下，把 Workbench 扩展成可日常使用的 AgentOps 调试台。

Phase 11 第一版聚焦三个结果：

1. Workbench 能发现并打开 eval report。
2. Workbench 能从失败 case 跳转到对应 trace 细节。
3. Workbench 能清晰展示 turn timeline、LLM response、tool observation、guard context 和 DB diff。

这不是一个“重做 Workbench UI”的 phase，而是把现有演示面板拆出明确的调试工作面，服务 live eval 失败归因、prompt/schema 回归分析和 portfolio 演示。

## 背景

截至 Phase 10，项目已经具备：

- `TraceReplayHarness`：可从 trace artifact 提取 LLM responses 和 tool results。
- live eval baseline / failure taxonomy：失败 case 已有 root cause、triage bundle 和 trace 路径。
- Workbench：可运行 demo case、查看 timeline、tool results、audit logs。

缺口在于这些能力还没有形成一条顺滑的调试路径。当前 Workbench 更像运行时演示面板，不是 AgentOps 调试台：

- 只能围绕 session 和 demo case 工作。
- 不能浏览已有 eval report。
- 不能从失败 case 直接打开 trace。
- Inspector 不能按调试语义区分 LLM response、tool observation、guard context、DB diff。

## 非目标

- 不在 Workbench 内执行真实 replay。
- 不在本 phase 提供 trace compare UI。
- 不修改 production runtime 主路径。
- 不把 `WorkbenchSnapshot` 扩展成同时承载 demo 运行态和 agentops 调试态的混合模型。
- 不要求新的 artifact 生成流程；Phase 11 只消费现有 report、trace 和 triage bundle 能提供的数据。

## 架构决策

### 决策 1：Workbench 拆成 Demo 和 AgentOps 两个工作面

Workbench 顶层 UI 明确区分两个 workspace：

- `Demo`
  - 继续使用当前 session 驱动模型。
  - 用于脚本案例演示、手动发消息、观察 runtime 行为。
- `AgentOps`
  - 新增只读调试模型。
  - 用于发现 eval report、过滤 case、查看 triage 信息和 trace 详情。

两个工作面共享壳层布局、视觉风格和部分只读展示组件，但不共享状态 contract。

### 决策 2：AgentOps 不复用 `WorkbenchSnapshot`

`WorkbenchSnapshot` 是 demo runtime 的运行态快照，字段围绕 session、business state 和 run controls 设计。把 report/trace/triage 数据塞进同一个 contract，会造成：

- 类型含义变模糊。
- API 返回结构不可预测。
- 前端状态分支快速膨胀。

因此 AgentOps 使用新的只读 contract：

- `AgentOpsReportSummary`
- `AgentOpsReportDetail`
- `AgentOpsCaseDetail`
- `AgentOpsTraceDetail`

### 决策 3：AgentOps 后端只提供资源型 API

AgentOps 不创建 `AgentRuntime` session，不执行工具，不变更 DB。后端只负责：

- artifact 发现
- report 读取与摘要
- case triage 组装
- trace 到 UI detail/timeline 的映射

这样可以保持 production runtime 单一路径不变，也避免“调试台”成为新的隐式 harness。

## 系统结构

### Demo 工作面

沿用现有结构：

```text
React Demo UI
  -> /api/sessions/*
  -> WorkbenchSessionManager / WorkbenchSession
  -> AgentRuntime
  -> trace artifact
```

### AgentOps 工作面

新增结构：

```text
React AgentOps UI
  -> /api/agentops/*
  -> app/workbench/agentops.py
  -> report discovery / triage bundle / trace reader
  -> read-only mapped view models
```

### 后端模块边界

建议新增：

- `app/workbench/agentops.py`
  - artifact discovery
  - report loading
  - case detail assembly
  - trace detail assembly
  - trace -> timeline/detail mapping
- `app/workbench/agentops_models.py`
  - Pydantic response models

保留现有：

- `app/workbench/api.py`
- `app/workbench/session.py`
- `app/workbench/snapshot.py`

原则：

- `session.py` 只服务 Demo。
- `snapshot.py` 只产出 Demo snapshot。
- AgentOps 的 artifact 读取与映射不反向依赖 Demo session 逻辑。

## 数据模型

### Report 列表

`GET /api/agentops/reports`

返回内容：

- `run_id`
- `report_path`
- `created_at`
- `eval_backend`
- `model`
- `provider`
- `subset`
- `pass_count`
- `fail_count`
- `failure_case_count`

用途：

- 让 UI 展示“可打开的评估运行列表”。
- 支持按 backend、subset、时间排序。

### Report 详情

`GET /api/agentops/reports/{run_id}`

返回内容：

- report 基础 metadata
- baseline metadata
  - `model`
  - `provider`
  - `prompt_hash`
  - `tool_schema_hash`
  - `action_specs_hash`
  - `eval_backend`
- 聚合指标
  - `pass_rate`
  - `tool_call_count`
  - `guard_block_count`
  - `total_token_usage`
  - `average_llm_loop_iterations`
- case 列表
  - `case_id`
  - `subset`
  - `passed`
  - `failure_label`
  - `root_cause`
  - `trace_artifact_path`

### Case 调试详情

`GET /api/agentops/cases/{run_id}/{case_id}`

返回内容：

- `case_id`
- `run_id`
- `subset`
- `passed`
- `failure_label`
- `root_cause`
- `trace_artifact_path`
- `user_messages`
- `assistant_messages`
- `guard_context`
- `db_assertion_diff`
- `tool_calls`
- `trace_summary`
  - `message_count`
  - `llm_response_count`
  - `tool_call_count`
  - `guard_block_count`

这个接口是对 `eval report + triage bundle + trace metadata` 的组合视图，前端不需要自己拼三份数据。

### Trace 详情

`GET /api/agentops/traces/{trace_id}`

返回内容：

- `trace_id`
- `trace_artifact_path`
- `metadata`
- `timeline`
- `turns`
- `final_state`
- `db_hashes`
- `llm_responses`
- `tool_calls`

其中：

- `timeline` 用于 Workbench 中部时间线。
- `turns` 用于按轮次查看 `user -> llm -> tool -> assistant`。
- `tool_calls` 保留完整 `block_context` 和 `observation`。

Phase 11 第一版明确提供：

- `GET /api/agentops/traces?path=...`

用于直接按绝对路径打开 trace artifact；路径无效时返回结构化错误。

## 交互设计

### 顶层导航

Workbench 顶部从单一视图改为双 tab：

- `Demo`
- `AgentOps`

切换 tab 不共享内部状态：

- Demo 保持自己的 session、selected case、timeline selection。
- AgentOps 保持自己的 selected report、filters、selected case、selected trace event。

### AgentOps 页面布局

建议使用三栏：

1. 左栏：Report / Case Browser
   - report 列表
   - 当前 report metadata 概览
   - case filters
     - pass / fail
     - `failure_label`
     - `root_cause`
     - `subset`
   - case 列表
2. 中栏：Trace Timeline
   - turn-by-turn timeline
   - 支持点击事件切换 Inspector 内容
   - 默认定位到最后一个关键失败点或最后一个事件
3. 右栏：Inspector
   - `LLM Response`
   - `Tool Observation`
   - `Guard Context`
   - `DB Diff`
   - `Trace Metadata`

### 调试主路径

标准路径：

1. 打开 AgentOps。
2. 选择一个 eval report。
3. 过滤到失败 case。
4. 选择某个 case。
5. 自动加载 case triage 详情和 trace timeline。
6. 点击 timeline 中的某个 tool call 或 message。
7. 在 Inspector 查看对应的 LLM response、tool observation、guard context、DB diff。

补充路径：

- 用户直接输入 trace 路径并打开单个 trace。

### Inspector 语义

当前 Inspector 主要是原样打印 JSON。Phase 11 第一版改成“调试语义优先”：

- `LLM Response`
  - 当前 turn 的 assistant content
  - finish reason
  - token usage
  - raw tool call 列表
- `Tool Observation`
  - tool name
  - arguments
  - status
  - observation
  - error
- `Guard Context`
  - block reason
  - block context
  - retryable
- `DB Diff`
  - expected / actual diff
  - final hash / initial hash

如果当前事件不具备某块信息，对应区块显示空状态，不显示误导性占位值。

## 数据流

### Report 浏览

```text
AgentOps UI
  -> GET /api/agentops/reports
  -> 选择 report
  -> GET /api/agentops/reports/{run_id}
  -> 过滤 case
```

### Case 调试

```text
选择 case
  -> GET /api/agentops/cases/{run_id}/{case_id}
  -> 读取 trace_artifact_path
  -> GET /api/agentops/traces/{trace_id}
  -> 展示 timeline + inspector
```

### 直接打开 trace

```text
输入 trace path / trace id
  -> GET /api/agentops/traces/{trace_id} 或 trace path 接口
  -> 展示 timeline + inspector
```

## Artifact 发现策略

AgentOps 需要能从 `artifact_dir` 中发现 report 和 trace。第一版策略保持简单：

- report：扫描约定 report 目录，按修改时间倒序返回。
- trace：通过 report case 中记录的 `trace_artifact_path` 直接定位。
- triage：优先从 report case 结果字段构造；若已有 triage bundle 文件则读取，没有也不报错。

原则：

- 不要求 artifact 命名重构。
- 不要求额外索引数据库。
- 不改变 eval runner 的输出结构。

## 错误处理

所有 AgentOps API 都返回与现有 Workbench 一致的结构化错误。

需要覆盖的错误场景：

- `report_not_found`
- `trace_not_found`
- `case_not_found`
- `invalid_trace_path`
- `artifact_parse_error`

错误处理原则：

- 发现不到 artifact 时，返回 recoverable error。
- 单个 report/case 解析失败不应影响整个 report 列表。
- UI 在右栏保留错误面板，而不是整页白屏。

## 安全与边界

Phase 11 的 AgentOps 是只读能力，必须满足：

- 不创建 `AgentRuntime`。
- 不调用真实工具。
- 不写 DB。
- 不依赖 replay 执行工具结果。
- 只消费已有 artifact。

敏感信息处理沿用现有 Workbench redaction 逻辑。trace / report / triage 中进入 UI 的用户信息继续做脱敏，至少覆盖：

- email
- phone
- address
- zip
- payment

## 向后兼容

必须保持：

- `/api/sessions/*` 原行为不变。
- `WorkbenchSnapshot` 原 contract 不变。
- `offline_demo` / `llm` mode 不变。
- Demo 工作面的 case 演示、step、run-all、manual message 行为不变。

允许新增但不替换：

- `/api/agentops/*`
- AgentOps 前端类型与组件
- 新的只读 mapper

## 测试策略

### 后端

1. artifact discovery / parsing
   - 能发现 report 列表。
   - 能读取 report 详情。
   - 缺失 trace / 损坏 JSON 时返回结构化错误。
2. case detail assembly
   - 能从 report + triage + trace 组装 case 详情。
   - `guard_context`、`db_assertion_diff`、`trace_artifact_path` 映射正确。
3. trace mapping
   - 能把 trace 映射成 timeline、turns、Inspector 可读 detail。
   - block context 和 tool observation 不丢失。
4. API
   - `/api/agentops/reports`
   - `/api/agentops/reports/{run_id}`
   - `/api/agentops/cases/{run_id}/{case_id}`
   - `/api/agentops/traces/{trace_id}`

### 前端

1. 类型收敛
   - Demo 类型与 AgentOps 类型不混用。
2. 渲染状态
   - report 列表渲染
   - case filter + selection
   - timeline 选择
   - Inspector 四块内容显示
   - 错误状态显示
3. 构建验证
   - `npm --prefix workbench run build`

### 手动验收

必须能完整走通：

1. 打开 Workbench。
2. 切换到 AgentOps。
3. 打开一个 eval report。
4. 过滤到失败 case。
5. 打开 case。
6. 在 timeline 中选中关键 tool call。
7. 在 Inspector 看到 guard context 和 DB diff。

## 验收标准

- Workbench 顶层已明确区分 `Demo` 和 `AgentOps`。
- Demo 原有功能和 API contract 未回归。
- AgentOps 能浏览 report 列表并打开 report 详情。
- AgentOps 能从失败 case 进入 trace 详情。
- Inspector 能分区展示 LLM response、tool observation、guard context、DB diff。
- 整个 AgentOps 路径不执行真实 replay，不调用真实写工具。
- `pytest`、`ruff check` 和 Workbench 前端构建通过。

## Phase 11 第一版边界

本 phase 故意不做：

- replay 执行按钮
- trace compare UI
- prompt/schema baseline diff 可视化
- report 跨运行对比

这些能力都建立在本 phase 的只读 AgentOps 入口之上，后续再扩。

## 风险与缓解

### 风险 1：Demo 与 AgentOps 状态耦合

缓解：

- 拆分前端类型。
- 拆分后端 API。
- 不复用 `WorkbenchSnapshot`。

### 风险 2：artifact 结构不一致导致 UI 易碎

缓解：

- 后端做统一 mapping。
- 前端只消费稳定 view model。
- 对缺失字段提供空状态而不是崩溃。

### 风险 3：调试能力侵入 runtime

缓解：

- AgentOps 只读。
- 不创建 runtime session。
- 不执行 replay。

## 实施建议

实现时先从后端只读 contract 和测试入手，再做前端切页与 Inspector。推荐顺序：

1. 新增 AgentOps response models 和 artifact discovery。
2. 新增 AgentOps API 与后端测试。
3. 新增前端 AgentOps 类型和 API client。
4. 新增顶层 tab 切换与 AgentOps 浏览器。
5. 扩展 Timeline / Inspector 为可复用只读展示组件。
6. 跑后端测试、前端构建和手动验收。
