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
- 控制阶段边界，避免把展示层、benchmark、synthetic 泛化、LLM 工程和 Workbench 产品化混成一个大任务。
- 清晰区分三条主线：
  - 标准 eval 覆盖：`curated_mvp`、`generalized_mvp`、未来的 tau full split。
  - synthetic 泛化：生成新的零售世界，证明不是背固定 case。
  - 产品化展示：Workbench、trace、report 和 AgentOps 检查界面。

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

正在进行或已规划但需要纳入路线图的工作：

- `docs/superpowers/plans/2026-06-13-prompt-engineering-dual-track.md` 已经定义 prompt engineering / dual-track 的详细计划。
- 这部分工作与本文中的 Phase 10 高度相关，因此 Phase 10 需要拆成：
  - Phase 10A：当前 prompt engineering plan 的落地和收尾。
  - Phase 10B：后续 model comparison、prompt variant testing、divergence deep analysis 和 prompt caching measurement。

近期已知卫生项：

- `ruff check .` 仍有 import 排序和 unused import 问题。
- Workbench 功能可用，但还不是为面试展示优化过的交互。
- README 仍偏开发阶段记录，不够像作品集入口。

## 跨阶段质量基线

所有阶段都应尽量维护以下基线：

- Python tests：`uv run python -m pytest tests/ -q`
- Ruff lint：`uv run ruff check .`
- Ruff format：`uv run ruff format --check .`
- Curated eval：`uv run phase2-eval --subset curated_mvp --trials 1 --no-progress --json`
- Generalized eval：`uv run phase2-eval --subset generalized_mvp --trials 1 --no-progress --json`
- Workbench build：在 `workbench/` 下运行 `npm run build`
- 记录关键 latency baseline，避免后续阶段让 12-node pipeline 明显退化。

性能基线第一版不需要复杂监控系统。可以先在 eval summary 中保留 average latency，并在阶段验收时记录当前值和变化趋势。

## Phase 6：Portfolio-Grade Presentation Layer

### 目标

让 AI Agent 工程面试官在 3-5 分钟内看懂项目价值。

这一阶段不以新增核心 Agent 能力为主，而是把已经跑通的系统包装成一个清晰、有证据、有演示路径的作品集。

### 范围

文档：

- 重写 README，围绕作品集叙事组织。
- 新增作品集架构文档，例如 `docs/portfolio-architecture.md`。
- 保留历史 phase docs，但不要让它们成为新读者的第一入口。

README 建议结构：

1. Problem Statement：为什么交易型客服 Agent 难。
2. Architecture Overview：核心架构和图示。
3. Quick Start：3 步跑通本地 demo。
4. Demo Walkthrough：推荐演示路径。
5. Eval Overview：`curated_mvp`、`generalized_mvp`、关键指标。
6. Project Structure：主要模块说明。
7. Development Guide：测试、lint、eval、Workbench 命令。

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

Phase 6 的 Workbench 边界：

- 只调整 case 标签、默认顺序、信息层级和关键状态呈现。
- 不改组件架构。
- 不新增复杂路由。
- 不做 run history、trace compare、eval report browser、synthetic scenario browser。
- 上述深度探索能力留给 Phase 11。

演示材料：

- 产出一个 2 分钟 demo GIF 或短录屏，嵌入 README 或作为 README 链接。
- 如果自动化录屏成本过高，第一版可以用固定步骤的截图替代，但要保留后续自动化录屏任务。

工程卫生：

- 修复 Ruff 报告的 import 排序和 unused import。
- 增加 `ruff format --check .` 到验证清单。
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
5. 补一段 demo walkthrough，定义面试展示脚本。
6. 修复 Ruff import hygiene，并补充 format check。
7. 录制或生成一份 demo GIF / 截图材料。
8. 跑完整验证。

### 验收标准

- README 可以作为项目作品集入口。
- 新读者不用读旧 phase plan，也能跑一个 Workbench demo 和一个 eval 命令。
- Workbench 的 Phase 6 改动不引入新的组件架构和路由复杂度。
- demo GIF / 截图材料可用。
- `uv run python -m pytest tests/ -q` 通过。
- `uv run ruff check .` 通过。
- `uv run ruff format --check .` 通过。
- `uv run phase2-eval --subset generalized_mvp --trials 1 --no-progress --json` 报告 30/30。
- 在 `workbench/` 下 `npm run build` 通过。

## Phase 6.5：Security Architecture Audit & Documentation

### 目标

把项目最强的安全卖点变成可展示、可验证的证据：7-layer write guard、pending action、confirmation、no-write invariant、audit log 和 deterministic safety boundary。

这一阶段可以和 Phase 6 后半段并行，但文档上建议单独列出，因为写操作安全是交易型 Agent 的核心竞争力。

### 范围

安全架构文档：

- 新增或扩展安全架构文档，覆盖：
  - 写操作入口。
  - ToolGateway 与 WriteActionGuard 的边界。
  - 7-layer guard。
  - read-before-write。
  - ownership validation。
  - policy validation。
  - explicit confirmation。
  - resource lock。
  - idempotency。
  - audit log。
- 明确说明：LLM 不直接决定写操作安全，guard 才是最终裁决层。

测试覆盖梳理：

- 列出现有 guard 相关测试覆盖哪些风险。
- 标注未覆盖或弱覆盖区域。
- 将关键 no-write cases 和 mutation cases 映射到 capability matrix。

演示证据：

- 在 README 或 portfolio architecture 中展示一个 guard block trace。
- 展示一个 successful write trace，强调 confirmation 后才 mutation。

### 建议任务

1. 梳理 `WriteActionGuard` 的所有 block reason。
2. 将 guard rules 与 tests / eval cases 做映射。
3. 新增安全架构文档或合并进 `docs/portfolio-architecture.md` 的安全章节。
4. 在 Workbench demo walkthrough 中加入一个 guard block 场景。
5. 记录当前 mutation error rate 和 no-write invariant 结果。

### 验收标准

- 有清晰文档说明写操作安全边界。
- 每个核心写操作至少有成功 case 和安全 block/no-write 证据。
- `mutation_error_rate` 在核心 eval 中为 0。
- 面试官可以从文档和 Workbench 看到 guard 如何阻止错误写入。

## Phase 7：Synthetic Retail Sandbox v1

### 目标

证明 Agent 不是记住固定 tau retail cases，而是能处理一个新生成的零售世界：新用户、新订单、新商品、新支付方式，以及新增交易能力。

这一阶段引入 seed-based synthetic domain，同时复用现有 AgentRuntime、ToolGateway、guard 思路、eval runner 概念和 Workbench demo loop。

### 架构决策

采用 SyntheticRetailAdapter overlay。

SyntheticRetailAdapter 应该是一个独立 adapter，提供与现有 runtime 兼容的工具集合和 DB snapshot，而不是继承并改写现有 `RetailAdapter` 的内部实现。

推荐关系：

```text
AgentRuntime
  -> runtime factory / adapter selection
      -> Tau retail runtime（现有路径）
      -> Synthetic retail runtime（新增路径）
```

v1 不需要抽象出完整 domain plugin framework。只要保证 synthetic runtime 能被 ToolRegistry / ToolGateway 使用即可。

### 范围

Synthetic world generation：

- 基于 seed 生成一份小型独立 DB snapshot。
- v1 规模基线建议：
  - 10 users。
  - 50 orders。
  - 30 products。
  - 每个 product 3 个 variants，总计约 90 items。
  - 每个用户 2-4 个 payment methods。
  - 3 个 shipping methods。
- 同一个 seed 和 scenario id 必须生成可复现的 world。
- 每个 scenario 使用独立 DB snapshot 或隔离 runtime state。

Tool compatibility：

- 尽量复用现有 retail-style tools：
  - 用户查找。
  - 用户详情。
  - 订单详情。
  - 商品 / item 详情。
  - synthetic schema 支持的现有写操作。
- synthetic cases 复用 `EvalCase` 模型，必要时通过 `expected_db_assertions` 扩展断言。
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
- 拒绝时可提供替代方案，例如说明可以帮用户检查订单状态、修改配送方式或转人工，但不能直接发放补偿。
- 这些请求必须 no DB mutation、no write lock。

### 不采纳项说明

外部评审建议 v1 至少增加 2-3 个新写操作，例如 `apply_gift_card`、`split_order_shipping`、`add_order_note`。这个方向可以作为后续扩展池，但不建议进入 v1。

原因：

- Phase 7 的核心目标是证明 synthetic world + 新交易能力 + guard 可迁移，不是扩展大量业务面。
- 多个新写操作会同时增加 action specs、parser、planner、guard、tool、eval、Workbench 的变更面。
- 对作品集展示来说，一个设计完整、有收费和支付约束的 shipping method 写操作，比三个浅层写操作更有说服力。

后续扩展池：

- `add_order_note`：低风险写操作，适合展示审计和备注。
- `apply_gift_card`：支付相关写操作，适合展示余额和拆分支付。
- `split_order_shipping`：复杂履约操作，适合作为 synthetic v2 或 Phase 8 之后的增强。

### 建议 Eval Subset

新增 synthetic seeded subset，例如：

```bash
uv run phase2-eval --subset synthetic_seeded_v1 --seed 42
```

第一版 scenarios：

- `synthetic_shipping_express_success`
- `synthetic_shipping_overnight_gift_card_insufficient`
- `synthetic_shipping_processed_order_block`
- `synthetic_shipping_same_method_block`
- `synthetic_shipping_unknown_method_block`
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
- shipping method block cases 能给出稳定 guard reason。
- 现有 tau retail `curated_mvp` 和 `generalized_mvp` 仍然通过。

## Phase 8a：Agent Generalization Core

### 目标

从少量 synthetic scenarios 升级到可复现的系统化泛化评测核心。

Phase 8 原始范围过大，因此拆成 8a 和 8b。Phase 8a 只做核心泛化能力：scenario family generation、deterministic oracle 和基础 reporting。

### 范围

Scenario family generation：

- 按能力生成 scenario families，第一版至少覆盖：
  - cancel。
  - modify shipping method。
  - coupon / compensation refusal。
- 每个 family 生成 success cases 和 guard-block cases。
- 根据生成的 scenario 自动生成 expected DB assertions。

Oracle generation：

- 确定性 oracle 作为 gate：
  - expected final DB assertion。
  - expected no-write invariant。
  - expected write lock。
  - expected guard reason。
  - expected confirmation status。
- 通信质量 oracle 暂不作为 gate，只作为参考维度。

Reporting：

- 新增 generalization report，并按以下维度聚合：
  - capability。
  - policy area。
  - guard reason。
  - scenario family。
- 区分失败来源：
  - parsing。
  - planning。
  - guard。
  - tool mutation。
  - response communication。

最小 generalization gate：

- 3 个 scenario families。
- 每个 family 5 个 deterministic variants。
- 共 15 个 generated cases。
- 全部通过才视为 Phase 8a 完成。

### 建议任务

1. 从 Phase 7 抽出 scenario definition primitives。
2. 增加 seeded scenario family generators。
3. 增加 deterministic oracle generation。
4. 扩展 eval runner，使其接收 generated scenario batches。
5. 扩展 report artifacts，加入 scenario family metadata。
6. 增加最小 generalization gate。

### 验收标准

- 一个 seeded generated batch 可以完全复现。
- 15 个 generated gate cases 全部通过。
- generated no-write cases 保持 DB hash 不变。
- generated successful write cases 只修改预期字段。
- report 能清晰说明失败来自 parsing、planning、guard 还是 tool execution。

## Phase 8b：Language Variation 与 Synthetic Workbench

### 目标

在 Phase 8a 的 deterministic scenario core 上增加语言变化和 Workbench 展示能力。

这一阶段才处理更展示型、更交互型的能力，避免 Phase 8a 被 UI 和自然语言变体拖大。

### 范围

Language variation：

- L1：同义词替换，例如 cancel → void / stop / discontinue。
- L2：信息排列变化，例如 email 在句首、句尾或第二轮出现。
- L3：信息缺失 + 多轮对话，例如用户先说要取消但没给 order id，Agent 需要追问。
- 第一版优先使用模板和规则改写，保证可复现；LLM 生成可作为后续增强，但不能成为 gate 的唯一来源。

Workbench：

- 增加最小版 “Generate Scenario” 流程。
- 支持输入 seed 和随机生成 seed。
- 展示 generated customer、order state、request、expected oracle 和 trace。
- 支持 replay generated scenario。

### 建议任务

1. 增加 language variant templates。
2. 支持 L1/L2/L3 三档语言变化。
3. 增加 generated scenario 的 Workbench 展示入口。
4. 增加 replay generated scenario。
5. 在 report 中标记 language variation level。

### 验收标准

- seeded language variants 可复现。
- L1/L2 variants 进入 gate。
- L3 multi-turn variants 可作为非阻塞探索集，稳定后再提升为 gate。
- Workbench 能展示 generated scenario 和 replay trace。

## Phase 9a：Tau Task Space Analysis

### 目标

在 full tau ingestion 之前先做轻量调研，避免盲目接入 114 个 task 后才发现大量 unsupported pattern。

这一阶段是 Phase 9 的前置调研，不需要改变 Agent runtime。

### 范围

- 遍历 `domains/retail/tasks.json`。
- 读取 `domains/retail/split_tasks.json`。
- 统计 task 类型分布。
- 统计 reward basis 分布。
- 对照 capability matrix 标注：
  - supported。
  - partial。
  - unsupported。
- 定义 unsupported 分类：
  - `unsupported_tool`：需要 Agent 没有的工具。
  - `unsupported_policy`：策略规则在当前系统不可表达。
  - `unsupported_interaction`：需要多 Agent 或外部系统协作。
  - `unsupported_reward_mode`：reward mode 暂不支持。
  - `unsupported_unknown`：无法分类的兜底。

### 建议任务

1. 写 tau task analyzer。
2. 输出 task type / reward basis / split 统计。
3. 输出 supported / partial / unsupported 分类报告。
4. 将分析结果写入 `docs/tau-task-space-analysis.md`。
5. 基于分析结果决定 Phase 9 首批 ingestion 范围。

### 验收标准

- 有完整 task space 分析报告。
- 能清楚说明 full tau ingestion 的已知支持面和风险。
- Phase 9 不再把 user simulation 和 reward evaluation 作为开放架构问题悬空。

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

- 首版采用 scripted task instructions。
- User simulator adapter 放到 Phase 9.5 或后续增强，不作为首版 gate。
- 避免把 agent failure 和 user simulator randomness 混在一起。

Reward evaluation：

- 以 task file 里的实际 `reward_basis` 为准。
- 支持 DB checks。
- 支持 required communication / NL assertion checks。
- action-level checks 如果当前系统无法完全表达，应明确标记为 partial 或 unsupported。
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

1. 基于 Phase 9a 的分析结果定义首批 ingestion 范围。
2. 增加 tau task loader。
3. 增加 tau split loader。
4. 定义 tau task 到 eval case 的转换逻辑。
5. 实现 reward-basis-aware assertions。
6. 增加 CLI subset names。
7. 增加 report metadata 和 dashboard fields。
8. 先跑一个小的 tau smoke subset，再跑 full train/test。

### 验收标准

- `tau_retail_train`、`tau_retail_test`、`tau_retail_all` 都是合法 subset。
- report 清楚展示 dataset root、task count、split、reward basis。
- unsupported task patterns 会用明确 failure label 失败，而不是静默成功。
- 现有 curated、generalized、synthetic subsets 仍然可用。

## Phase 10A：Prompt Engineering Plan 收尾

### 目标

把当前已有的 prompt engineering / dual-track 计划正式纳入长期路线，并完成稳定化。

这一阶段对应已有计划：

```text
docs/superpowers/plans/2026-06-13-prompt-engineering-dual-track.md
```

### 范围

- 完成 prompt 重写。
- 完成 dual-track merge 相关改造。
- 完成 P0 stability fix。
- 保持 deterministic eval 绿色。
- 明确 LLM-backed path 的当前能力边界。

### 建议任务

1. 对照现有 prompt engineering plan 检查完成度。
2. 将已完成内容同步到 README / portfolio architecture。
3. 确认 prompt metadata 和 hashes 在 artifacts 中可见。
4. 跑 deterministic eval 和 LLM-backed exploratory eval。
5. 记录 LLM path 的已知失败类型。

### 验收标准

- 当前 prompt engineering plan 的核心任务完成或明确降级。
- deterministic eval 不回退。
- LLM-backed exploratory eval 产生可解释结果。
- 文档中能说明 prompt engineering 与 guard safety 的关系。

## Phase 10B：LLM Engineering Upgrade

### 目标

在 Phase 10A 的基础上，让 LLM-backed path 更可信、更可比较、更有作品集展示价值。

这一阶段提升 model / prompt 对比、divergence analysis 和 prompt caching 观测能力，但仍不让 LLM output 成为交易安全的最终裁决。

### 范围

Prompt and model comparison：

- 支持带 prompt / model label 跑 eval。
- 对比：
  - pass rate。
  - DB accuracy。
  - mutation error rate。
  - guard block behavior。
  - LLM JSON error rate。
  - latency。
  - prompt cache hit / reuse 情况。

Dual-track observability：

- 分开记录 deterministic decisions 和 LLM decisions。
- 保留 conservative merge 行为。
- 把 divergence 作为 observability signal。
- 在 dashboard / report 中展示：
  - LLM helped。
  - LLM disagreed but guard prevented unsafe action。
  - LLM failed JSON or response format。

Synthetic + LLM：

- 在 Phase 7 synthetic cases 上同时跑 deterministic 和 LLM-backed 模式。
- 用 synthetic cases 测试 unseen wording 和新 domain state 下的 LLM 表现。

### 建议任务

1. 增加 prompt / model comparison artifact。
2. 增加 LLM divergence metrics。
3. 改进 LLM JSON failure classification。
4. 增加 prompt caching 命中或复用情况测量。
5. 支持 synthetic cases 的 LLM-backed exploratory eval。
6. 输出一份 LLM engineering report。

### 验收标准

- deterministic eval 保持绿色。
- LLM-backed runs 产出结构化 divergence 和 error metrics。
- report 中能看到 prompt versions、hashes、model labels。
- prompt caching 或 prompt reuse 有可观察指标。
- 文档明确说明：决定写操作安全的是 guardrails，不是 LLM confidence。

## Phase 11：AgentOps Workbench Product Polish

### 目标

把本地 Workbench 从 demo panel 升级成更强的 AgentOps inspection surface。

这一阶段是产品化打磨，应建立在 Phase 6 的 demo polish 和 Phase 7-8 的 synthetic 能力之上。

### 范围

Run history：

- 首版用本地文件系统 + JSON trace artifacts，不引入 SQLite。
- 增加 artifact index。
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
- 注意 Phase 2 report artifact 格式变化时，需要同步改造 browser。

Synthetic scenario browser：

- 按 seed 生成 scenario。
- 随机 seed。
- 保存 generated scenarios。
- replay generated scenarios。
- 并排展示 generated oracle 和 actual result。

视觉与交互 polish：

- Phase 11 的视觉 polish 服务深度使用者，不做 marketing layout。
- 保持密集、运营工具感。
- 让 guard blocks、writes、pending confirmations 更明显。
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
- 首版 run history 不需要数据库，文件索引足够。

## 推荐执行顺序

建议的主线顺序：

1. Phase 6：Portfolio-Grade Presentation Layer。
2. Phase 6.5：Security Architecture Audit & Documentation。
3. Phase 10A：Prompt Engineering Plan 收尾。
4. Phase 7：Synthetic Retail Sandbox v1。
5. Phase 10B：LLM Engineering Upgrade。
6. Phase 9a：Tau Task Space Analysis。
7. Phase 8a：Agent Generalization Core。
8. Phase 8b：Language Variation 与 Synthetic Workbench。
9. Phase 9：Full Tau Retail Ingestion。
10. Phase 11：AgentOps Workbench Product Polish。

可并行关系：

- Phase 6 和 Phase 10A 可部分并行，但 README 最终内容应吸收 Phase 10A 的结论。
- Phase 9a 与 Phase 7/8 可并行，因为 tau task analysis 不强依赖 synthetic runtime。
- Phase 10B 可在 Phase 7 后启动，因为 synthetic cases 会成为 LLM-backed 泛化测试材料。
- Phase 11 应尽量靠后，避免在 report、synthetic、LLM artifact 尚未稳定时过早做重 UI。

依赖图：

```text
Phase 6 ──→ Phase 6.5 ──→ Phase 7 ──→ Phase 8a ──→ Phase 8b ──┐
    │                         │             │                  │
    └────→ Phase 10A ─────────┴──→ Phase 10B                   │
                              │                                │
Phase 9a ─────────────────────┴────────────→ Phase 9 ──────────┤
                                                               │
                                                               ↓
                                                           Phase 11
```

## 待决问题

1. Phase 6 的作品集架构文档最终文件名和结构。
2. Phase 7 synthetic tooling 放在 `app/synthetic/`，还是 `app/tools/synthetic_retail.py`。
3. synthetic eval 是直接复用 `phase2-eval`，还是新增更清晰的 `phase7-synthetic-eval` script。
4. Phase 8 的 language variation 是否允许 LLM 生成非 gate 探索集。
5. Phase 9 full tau ingestion 的首批 supported task 范围。
6. Phase 11 的 Workbench 产品化应在 full tau ingestion 前做到什么程度。
7. 是否把 prompt caching measurement 作为 Phase 10B 的硬验收标准，还是作为报告指标。
8. 跨 phase latency baseline 的具体阈值，例如平均耗时允许增长多少。
