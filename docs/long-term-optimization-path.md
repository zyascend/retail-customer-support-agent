# 长期优化路径

日期：2026-06-13

这份路线图定义 `retail-customer-support-agent` 的长期优化方向。当前北极星是：

> 面向 AI Agent / LLM 应用工程师面试官的作品集展示。

项目要证明的不只是“能调用 LLM”，而是能构建一个受业务政策约束、能安全调用工具、能执行交易型写操作、能被评测、能被观测、能被现场演示的 Agent 系统。

后续阶段会加入 synthetic 泛化能力和 full benchmark ingestion，但近期优先级是先把现有系统讲清楚、展示好，让面试官能快速看懂工程价值。

## 指导原则

- 把项目当作 AI Agent 工程作品集，而不仅是 benchmark runner。
- 用证据说话：eval 结果、trace replay、guard audit、DB 状态变化、no-write invariant。
- deterministic guard 是最终安全边界；LLM 提供语义弹性，但不能拥有 unchecked write authority。
- 每个阶段都应该独立有价值，完成后项目仍然保持 demo-ready。
- 清晰区分三条主线：
  - 标准 eval 覆盖：`curated_mvp` 和 `generalized_mvp`。
  - synthetic 泛化：生成新的零售世界，证明不是背固定 case。
  - 产品化展示：Workbench 和 AgentOps 检查界面。

## 当前基线

Phase 5 后的项目基线：

- `curated_mvp`：11 个 case。
- `generalized_mvp`：30 个 case。
- deterministic eval 当前能通过上述两个 subset。
- Agent runtime 已经从巨型 `runtime.py` 拆分到多个更聚焦的模块：
  - `app/agent/parsers.py`
  - `app/agent/builders.py`
  - `app/agent/llm_client.py`
  - `app/agent/pipeline.py`
  - `app/agent/plan_handlers.py`
- Workbench 已支持本地单会话 demo loop。
- 还不能直接跑 tau retail 的 full train/test split。
- 还没有 synthetic retail world。

近期已知卫生项：

- `ruff check .` 仍有 import 排序和 unused import 问题。
- Workbench 功能可用，但还不是为面试展示优化过的交互。
- README 仍偏开发阶段记录，不够像作品集入口。

## Phase 6：Portfolio-Grade Presentation Layer

### 目标

让 AI Agent 工程面试官在 3-5 分钟内看懂项目价值。

这一阶段不以新增核心 Agent 能力为主，而是把已经跑通的系统包装成一个清晰、有证据、有演示路径的作品集。

### 范围

文档：

- 重写 README，围绕作品集叙事组织：
  - 项目解决什么问题。
  - 为什么交易型 Agent 需要写操作安全。
  - 核心架构是什么。
  - 如何跑 deterministic demo。
  - 如何跑 eval。
  - 指标分别证明什么。
  - 如何打开 Workbench。
- 新增作品集架构文档，例如 `docs/portfolio-architecture.md`。
- 保留历史 phase docs，但不要让它们成为新读者的第一入口。

Workbench demo polish：

- 默认展示最有说服力的 demo case。
- 按展示故事对 demo case 分组：
  - 成功写操作：confirmation + DB mutation。
  - Guard block：no-write invariant。
  - Confirmation deny/change。
  - Transfer 或 unsupported request。
- 优化 case 标签，让面试官不读源码也知道每个 case 想证明什么。
- 强化 pending action 区域。
- 让 timeline 里的关键证据更容易扫描：
  - intent 和 slots。
  - policy decision。
  - tool call。
  - guard block。
  - write audit。
  - DB mutation。
- 这一阶段只做展示型交互优化，不做完整产品级重设计。

工程卫生：

- 修复 Ruff 报告的 import 排序和 unused import。
- 保持现有测试和 eval 绿色。
- 避免无关大重构。

### 建议任务

1. 先写 README 新结构，再分段替换当前 README。
2. 新增 `docs/portfolio-architecture.md`，覆盖：
   - 12-node workflow。
   - ToolGateway 和 WriteActionGuard。
   - deterministic + LLM dual-track 设计。
   - eval 和 trace artifact 流程。
   - Workbench 在 demo 中的角色。
3. 更新 Workbench case 标签和默认展示顺序。
4. 优化 Workbench 关键证据的信息层级。
5. 修复 Ruff import hygiene。
6. 跑完整验证。

### 验收标准

- README 可以作为项目作品集入口。
- 新读者不用读旧 phase plan，也能跑一个 Workbench demo 和一个 eval 命令。
- `uv run python -m pytest tests/ -q` 通过。
- `uv run ruff check .` 通过。
- `uv run phase2-eval --subset generalized_mvp --trials 1 --no-progress --json` 报告 30/30。
- 在 `workbench/` 下 `npm run build` 通过。

## Phase 7：Synthetic Retail Sandbox v1

### 目标

证明 Agent 不是记住固定 tau retail cases，而是能处理一个新生成的零售世界：新用户、新订单、新商品、新支付方式，以及新增交易能力。

这一阶段引入 seed-based synthetic domain，同时复用现有 AgentRuntime、ToolGateway、guard 思路、eval runner 概念和 Workbench demo loop。

### 架构决策

采用 SyntheticRetailAdapter overlay。

synthetic 路径应该提供一个 retail-compatible runtime，包含 synthetic DB state 和 tools。它不应该污染 tau retail 数据，也不应该过早把核心 runtime 改成庞大的 domain framework。

### 范围

Synthetic world generation：

- 基于 seed 生成一份小型独立 DB snapshot。
- 包含：
  - users。
  - orders。
  - products。
  - item variants。
  - payment methods。
  - shipping methods。
- 同一个 seed 和 scenario id 必须生成可复现的 world。
- 每个 scenario 使用独立 DB snapshot 或隔离 runtime state。

Tool compatibility：

- 尽量复用现有 retail-style tools：
  - 用户查找。
  - 用户详情。
  - 订单详情。
  - 商品 / item 详情。
  - synthetic schema 支持的现有写操作。
- 新增一个写工具：
  - `modify_pending_order_shipping_method`。

新增配送方式修改能力：

- intent：`modify_shipping_method`。
- tool：`modify_pending_order_shipping_method`。
- required slots：
  - `order_id`。
  - `shipping_method`。
  - 收费升级时需要 `payment_method_id`。
- shipping methods：
  - `standard`：免费。
  - `express`：额外 9.99。
  - `overnight`：额外 24.99。
- guard rules：
  - 用户必须已认证。
  - 订单必须属于当前认证用户。
  - 写操作前必须已经加载订单详情。
  - 订单状态必须是 `pending`。
  - 新配送方式必须不同于当前配送方式。
  - 新配送方式必须可用。
  - 收费升级必须使用用户名下 payment method。
  - 如果使用 gift card，余额必须覆盖 fee delta。
  - 必须 explicit confirmation。
- mutation：
  - 更新订单 `shipping_method`。
  - 记录 `shipping_fee_delta`。
  - 写入 write lock：`order:<order_id>:modify_shipping_method`。
  - 写入 audit log。

优惠券 / 补偿边界：

- 支持识别 coupon、discount、compensation 请求。
- v1 不新增发券 tool。
- 用户要求折扣、优惠券、补偿时，应稳定拒绝或转人工。
- 这些请求必须 no DB mutation、no write lock。

### 建议 Eval Subset

新增 synthetic seeded subset，例如：

```bash
uv run phase2-eval --subset synthetic_seeded_v1 --seed 42
```

第一版 scenarios：

- `synthetic_shipping_express_success`
- `synthetic_shipping_overnight_gift_card_insufficient`
- `synthetic_shipping_processed_order_block`
- `synthetic_coupon_refusal_no_write`
- `synthetic_compensation_then_shipping_success`

### 建议任务

1. 定义 synthetic DB schema 和 seed generator。
2. 新增 `SyntheticRetailAdapter` 或等价 runtime factory。
3. 新增 synthetic read tools 和 shipping method mutation tool。
4. 扩展 action specs，加入 `modify_pending_order_shipping_method`。
5. 扩展 deterministic intent / slot parsing，支持配送方式修改。
6. 扩展 guard，加入 shipping method policy 和 payment coverage 校验。
7. 新增 synthetic eval cases 和 DB assertions。
8. 在 Workbench 加一个 fixed-seed synthetic scenario 的最小入口。

### 验收标准

- 固定 seed 能生成同样的 synthetic DB 和 scenario 定义。
- synthetic eval v1 通过。
- coupon / compensation cases 保持 DB hash 不变。
- shipping method success case 只有在 confirmation 后才写 DB。
- 现有 tau retail `curated_mvp` 和 `generalized_mvp` 仍然通过。

## Phase 8：Agent Generalization Lab

### 目标

从少量 synthetic scenarios 升级到系统化泛化评测。

这一阶段要展示 Agent 能处理 unseen wording、unseen scenario combinations，以及自动生成的合法 / 非法业务情境。

### 范围

Scenario generation：

- 按能力生成 scenario families：
  - lookup。
  - cancel。
  - modify address。
  - modify payment。
  - modify items。
  - return。
  - exchange。
  - modify shipping method。
  - unsupported coupon / compensation。
- 同时生成 success cases 和 guard-block cases。
- 根据生成的 scenario 自动生成 expected DB assertions。

Language variation：

- 同一个底层任务生成多种自然语言表达。
- 覆盖不同措辞、信息不完整、多轮对话。
- 保留 seeded deterministic variants，保证 report 可复现。

Oracle generation：

- 每个 generated scenario 都要生成：
  - expected final DB assertion。
  - 适用时的 expected no-write invariant。
  - 适用时的 expected write lock。
  - policy block case 的 expected guard reason。
  - expected confirmation status。

Reporting：

- 新增 generalization report，并按以下维度聚合：
  - capability。
  - policy area。
  - guard reason。
  - scenario family。
  - language variant。
- 区分失败来源：
  - parsing。
  - planning。
  - guard。
  - tool mutation。
  - response communication。

Workbench：

- 增加最小版 “Generate Scenario” 流程。
- 支持输入 seed 和随机生成 seed。
- 展示生成的 customer、order state、request、expected oracle 和 trace。

### 建议任务

1. 从 Phase 7 抽出 scenario definition primitives。
2. 增加 seeded scenario family generators。
3. 增加 language variant templates。
4. 增加 oracle generation。
5. 扩展 eval runner，使其接收 generated scenario batches。
6. 扩展 report artifacts，加入 scenario family metadata。
7. 在 Workbench 增加 synthetic scenario generation UI。

### 验收标准

- 一个 seeded generated batch 可以完全复现。
- generated no-write cases 保持 DB hash 不变。
- generated successful write cases 只修改预期字段。
- report 能清晰说明失败来自 parsing、planning、guard 还是 tool execution。

## Phase 9：Full Tau Retail Ingestion

### 目标

支持完整 tau retail dataset split，而不只是手写 eval subsets。

这一阶段和 Synthetic Sandbox 的价值不同：tau ingestion 证明能对齐标准数据集；Synthetic Sandbox 证明架构具备泛化能力。

### 范围

Dataset ingestion：

- 读取 `domains/retail/tasks.json`。
- 读取 `domains/retail/split_tasks.json`。
- 构建以下 eval subsets：
  - `tau_retail_train`
  - `tau_retail_test`
  - `tau_retail_all`
- 保留 task metadata：
  - task id。
  - split。
  - reward basis。
  - source dataset path。
  - dataset commit 或 checksum。

User simulation：

- 决定 v1 使用 scripted task instructions，还是接 user simulator adapter。
- 第一版建议保守：避免把 agent failure 和 user simulator randomness 混在一起；如果使用 simulator，report 必须明确标记随机性。

Reward evaluation：

- 以 task file 里的实际 `reward_basis` 为准。
- 支持 DB checks。
- 支持 required communication / NL assertion checks。
- 不支持的 reward mode 必须显式记录为 unsupported，而不是静默通过。

CLI：

```bash
uv run phase2-eval --subset tau_retail_train
uv run phase2-eval --subset tau_retail_test
uv run phase2-eval --subset tau_retail_all
```

Dashboard：

- 展示 split、reward basis 和 dataset metadata。
- 支持 curated、generalized、synthetic、full tau results 对比。

### 建议任务

1. 增加 tau task loader。
2. 增加 tau split loader。
3. 定义 tau task 到 eval case 的转换逻辑。
4. 实现 reward-basis-aware assertions。
5. 增加 CLI subset names。
6. 增加 report metadata 和 dashboard fields。
7. 先跑一个小的 tau smoke subset，再跑 full train/test。

### 验收标准

- `tau_retail_train`、`tau_retail_test`、`tau_retail_all` 都是合法 subset。
- report 清楚展示 dataset root、task count、split、reward basis。
- unsupported task patterns 会用明确 failure label 失败，而不是静默成功。
- 现有 curated、generalized、synthetic subsets 仍然可用。

## Phase 10：LLM Engineering Upgrade

### 目标

让 LLM-backed path 更可信，同时保持 deterministic guardrails 作为最终安全边界。

这一阶段提升语义鲁棒性、prompt 可维护性、model/prompt 对比能力，但不能让 LLM output 成为交易安全的最终裁决。

### 范围

Prompt contracts：

- 围绕更强的 contract 重写 prompt 文件：
  - identity and role。
  - behavioral rules。
  - negative constraints。
  - supported intents and slots。
  - tool usage rules。
  - output schema。
  - error recovery guidance。
  - few-shot examples。
- prompt 继续版本化，并在 artifacts 中记录 hash。

Dual-track behavior：

- 分开记录 deterministic decisions 和 LLM decisions。
- 保留 conservative merge 行为。
- 把 divergence 作为 observability signal。
- 在 dashboard / report 中展示 divergence：
  - LLM helped。
  - LLM disagreed but guard prevented unsafe action。
  - LLM failed JSON or response format。

Model and prompt comparison：

- 支持带 prompt / model label 跑 eval。
- 对比：
  - pass rate。
  - DB accuracy。
  - mutation error rate。
  - guard block behavior。
  - LLM JSON error rate。
  - latency。

### 建议任务

1. 重写 `core_contract`、`intent_slot`、`policy_reasoner`、`action_planner`、`response_generator` prompts。
2. 增加 prompt contract tests，检查 placeholders 和 hash metadata。
3. 增加 LLM divergence metrics。
4. 改进 LLM JSON failure classification。
5. 增加 prompt / model comparison artifact。
6. 分别跑 deterministic eval 和 LLM-backed exploratory eval。

### 验收标准

- deterministic eval 保持绿色。
- LLM-backed runs 产出结构化 divergence 和 error metrics。
- report 中能看到 prompt versions 和 hashes。
- 文档明确说明：决定写操作安全的是 guardrails，不是 LLM confidence。

## Phase 11：AgentOps Workbench Product Polish

### 目标

把本地 Workbench 从 demo panel 升级成更强的 AgentOps inspection surface。

这一阶段是产品化打磨，应建立在 Phase 6 的 demo polish 和 Phase 7-8 的 synthetic 能力之上。

### 范围

Run history：

- 保存 recent runs。
- 打开历史 traces。
- 比较两个 runs。
- 按 case、subset、status、failure label、guard reason 过滤。

Trace compare：

- 对比 timeline steps。
- 对比 tool calls。
- 对比 DB hashes 和 mutations。
- 对比 policy decisions 和 divergence。

Eval report browser：

- 加载 report artifacts。
- 浏览 case results。
- 深入 failed cases。
- 从 eval result 跳转到 trace replay。

Synthetic scenario browser：

- 按 seed 生成 scenario。
- 随机 seed。
- 保存 generated scenarios。
- replay generated scenarios。
- 并排展示 generated oracle 和 actual result。

视觉与交互 polish：

- 提升信息层级。
- 让 guard blocks、writes、pending confirmations 更明显。
- 保持密集、运营工具感，而不是 marketing layout。
- 避免把关键证据藏在太深的点击路径里。

### 建议任务

1. 定义 Workbench 的信息架构：run history、eval reports、synthetic scenarios。
2. 增加本地 artifact indexing。
3. 增加 report browser views。
4. 增加 trace compare view。
5. 增加 synthetic scenario browser。
6. 打磨视觉层级和响应式表现。
7. 为 README 增加截图或 demo clips。

### 验收标准

- 用户不手动打开 JSON，也能检查成功写操作、guard block 和 synthetic scenario。
- eval report 和 trace replay 互相连通。
- Workbench 中能看到 synthetic scenario generation。
- Workbench 能支撑作品集展示，不依赖命令行上下文。

## 推荐执行顺序

1. Phase 6：Portfolio-Grade Presentation Layer。
2. Phase 7：Synthetic Retail Sandbox v1。
3. Phase 8：Agent Generalization Lab。
4. Phase 9：Full Tau Retail Ingestion。
5. Phase 10：LLM Engineering Upgrade。
6. Phase 11：AgentOps Workbench Product Polish。

Phase 6 应该先做，因为它能立刻提升现有工作的展示价值，也为后续阶段提供展示入口。Phase 7 随后做，因为 synthetic generalization 是证明 Agent 没有背固定 cases 的最强证据。Full tau ingestion 很有价值，但不应该阻塞作品集主线。

## 待决问题

- Phase 6 的作品集架构文档最终文件名和结构。
- Phase 7 synthetic tooling 放在 `app/synthetic/`，还是 `app/tools/synthetic_retail.py`。
- synthetic eval 是直接复用 `phase2-eval`，还是新增更清晰的 `phase7-synthetic-eval` script。
- Phase 11 的 Workbench 产品化应在 full tau ingestion 前做到什么程度。
- 如果面试反馈更关注 LLM 行为而不是 benchmark 广度，是否把 LLM prompt upgrade 提前到 full tau ingestion 前。
