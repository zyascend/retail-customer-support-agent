# Tau Retail Task Space Analysis

## 1. 概述

**分析日期**: 2026-06-13
**数据来源**: `/Users/theyang/Documents/ai/AgentProject/data_sources/retail_customer_support_transaction_agent/current_tau3_bench/domains/retail`
**Task 总数**: 114
**Split 分布**: train 74 / test 40

## 2. Task 空间统计

### 2.1 Split 分布

| Split | Task 数量 |
|-------|----------|
| train | 74 |
| test  | 40 |
| **合计** | **114** |

### 2.2 Reward Basis 分布

| Reward Basis | 数量 |
|-------------|------|
| DB | 2 |
| DB + NL_ASSERTION | 112 |

### 2.3 Action 数量分布

- **最小**: 0
- **最大**: 13
- **平均**: 4.8

### 2.4 工具使用频率 (Top 15)

| 工具 | 出现次数 |
|------|---------|
| get_order_details | 168 |
| find_user_id_by_name_zip | 61 |
| get_user_details | 57 |
| get_product_details | 54 |
| return_delivered_order_items | 41 |
| modify_pending_order_items | 39 |
| exchange_delivered_order_items | 35 |
| cancel_pending_order | 25 |
| modify_pending_order_address | 24 |
| find_user_id_by_email | 14 |
| calculate | 13 |
| modify_user_address | 11 |
| transfer_to_human_agents | 4 |
| get_item_details | 3 |
| modify_pending_order_payment | 1 |

## 3. 工具覆盖分析

### 3.1 Agent 已支持工具 vs tau3 要求工具

| 工具 | 状态 | 出现次数 |
|------|------|---------|
| calculate | ⚠️ 辅助工具（partial） | 11 |
| cancel_pending_order | ✅ 已支持 | 18 |
| exchange_delivered_order_items | ✅ 已支持 | 29 |
| find_user_id_by_email | ✅ 已支持 | 11 |
| find_user_id_by_name_zip | ✅ 已支持 | 57 |
| get_item_details | ⚠️ 辅助工具（partial） | 1 |
| get_order_details | ✅ 已支持 | 64 |
| get_product_details | ✅ 已支持 | 34 |
| get_user_details | ✅ 已支持 | 55 |
| modify_pending_order_address | ✅ 已支持 | 20 |
| modify_pending_order_items | ✅ 已支持 | 35 |
| modify_pending_order_payment | ✅ 已支持 | 1 |
| modify_user_address | ✅ 已支持 | 10 |
| return_delivered_order_items | ✅ 已支持 | 31 |
| transfer_to_human_agents | ✅ 已支持 | 4 |

### 3.2 缺失工具详情

#### `calculate` (辅助工具)
- 出现次数: 11
- 影响 task: 16, 21, 28, 38, 44, 45, 46, 47, 49, 61, 63
- 评估: 辅助计算/查询，Agent 主流程不受阻，标记为 partial

#### `get_item_details` (辅助工具)
- 出现次数: 1
- 影响 task: 21
- 评估: 辅助计算/查询，Agent 主流程不受阻，标记为 partial

## 4. 分类结果

### 4.1 总览

| 分类 | 数量 | 占比 |
|------|------|------|
| supported | 69 | 60.5% |
| partial | 43 | 37.7% |
| unsupported | 2 | 1.8% |

### 4.2 按 Split 分布

- **train**: supported 43, partial 29, unsupported 2
- **test**: supported 26, partial 14, unsupported 0

### 4.3 Partial 子类别

| 子类别 | 数量 |
|--------|------|
| partial_missing_tool | 2 |
| partial_multi | 9 |
| partial_nl_assertion | 32 |

### 4.4 Unsupported 子类别

| 子类别 | 数量 | Task IDs |
|--------|------|----------|
| unsupported_unknown | 2 | 24, 57 |

### 4.5 完整 Task 分类清单

| Task ID | Split | 状态 | 子类别 | 工具数 | NL Assertion | 备注 |
|---------|-------|------|--------|--------|-------------|------|
| 0 | train | supported | - | 5 | - | All tools supported, no NL assertions, no policy concerns. |
| 1 | train | supported | - | 5 | - | All tools supported, no NL assertions, no policy concerns. |
| 2 | train | partial | partial_nl_assertion | 11 | ✓ | has NL assertions |
| 3 | train | partial | partial_nl_assertion | 12 | ✓ | has NL assertions |
| 4 | train | partial | partial_nl_assertion | 13 | ✓ | has NL assertions |
| 5 | test | supported | - | 5 | - | All tools supported, no NL assertions, no policy concerns. |
| 6 | train | supported | - | 6 | - | All tools supported, no NL assertions, no policy concerns. |
| 7 | train | supported | - | 6 | - | All tools supported, no NL assertions, no policy concerns. |
| 8 | train | supported | - | 6 | - | All tools supported, no NL assertions, no policy concerns. |
| 9 | test | supported | - | 6 | - | All tools supported, no NL assertions, no policy concerns. |
| 10 | train | supported | - | 5 | - | All tools supported, no NL assertions, no policy concerns. |
| 11 | train | supported | - | 6 | - | All tools supported, no NL assertions, no policy concerns. |
| 12 | test | supported | - | 5 | - | All tools supported, no NL assertions, no policy concerns. |
| 13 | train | supported | - | 5 | - | All tools supported, no NL assertions, no policy concerns. |
| 14 | train | supported | - | 6 | - | All tools supported, no NL assertions, no policy concerns. |
| 15 | train | supported | - | 7 | - | All tools supported, no NL assertions, no policy concerns. |
| 16 | train | partial | partial_multi | 9 | ✓ | uses auxiliary tools: calculate; has NL assertions |
| 17 | test | supported | - | 6 | - | All tools supported, no NL assertions, no policy concerns. |
| 18 | test | supported | - | 5 | - | All tools supported, no NL assertions, no policy concerns. |
| 19 | train | partial | partial_nl_assertion | 7 | ✓ | has NL assertions |
| 20 | train | supported | - | 10 | - | All tools supported, no NL assertions, no policy concerns. |
| 21 | train | partial | partial_multi | 12 | ✓ | uses auxiliary tools: calculate, get_item_details; has NL assertions |
| 22 | train | supported | - | 7 | - | All tools supported, no NL assertions, no policy concerns. |
| 23 | train | supported | - | 12 | - | All tools supported, no NL assertions, no policy concerns. |
| 24 | train | unsupported | unsupported_unknown | 0 | ✓ | Task has no expected actions. |
| 25 | train | supported | - | 6 | - | All tools supported, no NL assertions, no policy concerns. |
| 26 | test | supported | - | 8 | - | All tools supported, no NL assertions, no policy concerns. |
| 27 | test | supported | - | 6 | - | All tools supported, no NL assertions, no policy concerns. |
| 28 | train | partial | partial_multi | 11 | ✓ | uses auxiliary tools: calculate; has NL assertions |
| 29 | train | partial | partial_nl_assertion | 6 | ✓ | has NL assertions |
| 30 | train | supported | - | 13 | - | All tools supported, no NL assertions, no policy concerns. |
| 31 | train | supported | - | 12 | - | All tools supported, no NL assertions, no policy concerns. |
| 32 | test | supported | - | 13 | - | All tools supported, no NL assertions, no policy concerns. |
| 33 | test | partial | partial_nl_assertion | 6 | ✓ | has NL assertions |
| 34 | train | partial | partial_nl_assertion | 6 | ✓ | has NL assertions |
| 35 | train | supported | - | 7 | - | All tools supported, no NL assertions, no policy concerns. |
| 36 | test | partial | partial_nl_assertion | 1 | ✓ | has NL assertions |
| 37 | train | partial | partial_nl_assertion | 4 | ✓ | has NL assertions |
| 38 | test | partial | partial_multi | 4 | ✓ | uses auxiliary tools: calculate; has NL assertions |
| 39 | test | partial | partial_nl_assertion | 5 | ✓ | has NL assertions |
| 40 | test | partial | partial_nl_assertion | 4 | ✓ | has NL assertions |
| 41 | train | supported | - | 10 | - | All tools supported, no NL assertions, no policy concerns. |
| 42 | test | supported | - | 10 | - | All tools supported, no NL assertions, no policy concerns. |
| 43 | train | partial | partial_nl_assertion | 5 | ✓ | has NL assertions |
| 44 | train | partial | partial_multi | 5 | ✓ | uses auxiliary tools: calculate; has NL assertions |
| 45 | test | partial | partial_multi | 5 | ✓ | uses auxiliary tools: calculate; has NL assertions |
| 46 | train | partial | partial_multi | 7 | ✓ | uses auxiliary tools: calculate; has NL assertions |
| 47 | train | partial | partial_multi | 7 | ✓ | uses auxiliary tools: calculate; has NL assertions |
| 48 | train | supported | - | 6 | - | All tools supported, no NL assertions, no policy concerns. |
| 49 | test | partial | partial_missing_tool | 10 | - | uses auxiliary tools: calculate |
| 50 | train | supported | - | 1 | - | All tools supported, no NL assertions, no policy concerns. |
| 51 | test | supported | - | 6 | - | All tools supported, no NL assertions, no policy concerns. |
| 52 | train | supported | - | 5 | - | All tools supported, no NL assertions, no policy concerns. |
| 53 | test | supported | - | 6 | - | All tools supported, no NL assertions, no policy concerns. |
| 54 | train | partial | partial_nl_assertion | 12 | ✓ | has NL assertions |
| 55 | test | supported | - | 13 | - | All tools supported, no NL assertions, no policy concerns. |
| 56 | test | supported | - | 7 | - | All tools supported, no NL assertions, no policy concerns. |
| 57 | train | unsupported | unsupported_unknown | 0 | - | Task has no expected actions. |
| 58 | train | supported | - | 6 | - | All tools supported, no NL assertions, no policy concerns. |
| 59 | train | partial | partial_nl_assertion | 5 | ✓ | has NL assertions |
| 60 | test | partial | partial_nl_assertion | 4 | ✓ | has NL assertions |
| 61 | test | partial | partial_missing_tool | 5 | - | uses auxiliary tools: calculate |
| 62 | test | partial | partial_nl_assertion | 5 | ✓ | has NL assertions |
| 63 | train | partial | partial_multi | 7 | ✓ | uses auxiliary tools: calculate; has NL assertions |
| 64 | test | supported | - | 8 | - | All tools supported, no NL assertions, no policy concerns. |
| 65 | test | supported | - | 3 | - | All tools supported, no NL assertions, no policy concerns. |
| 66 | train | supported | - | 5 | - | All tools supported, no NL assertions, no policy concerns. |
| 67 | train | partial | partial_nl_assertion | 5 | ✓ | has NL assertions |
| 68 | test | partial | partial_nl_assertion | 4 | ✓ | has NL assertions |
| 69 | train | supported | - | 4 | - | All tools supported, no NL assertions, no policy concerns. |
| 70 | test | partial | partial_nl_assertion | 1 | ✓ | has NL assertions |
| 71 | test | supported | - | 2 | - | All tools supported, no NL assertions, no policy concerns. |
| 72 | train | supported | - | 2 | - | All tools supported, no NL assertions, no policy concerns. |
| 73 | train | supported | - | 1 | - | All tools supported, no NL assertions, no policy concerns. |
| 74 | test | supported | - | 2 | - | All tools supported, no NL assertions, no policy concerns. |
| 75 | train | supported | - | 1 | - | All tools supported, no NL assertions, no policy concerns. |
| 76 | train | partial | partial_nl_assertion | 2 | ✓ | has NL assertions |
| 77 | test | supported | - | 1 | - | All tools supported, no NL assertions, no policy concerns. |
| 78 | train | supported | - | 3 | - | All tools supported, no NL assertions, no policy concerns. |
| 79 | test | supported | - | 1 | - | All tools supported, no NL assertions, no policy concerns. |
| 80 | train | supported | - | 1 | - | All tools supported, no NL assertions, no policy concerns. |
| 81 | train | supported | - | 2 | - | All tools supported, no NL assertions, no policy concerns. |
| 82 | train | supported | - | 1 | - | All tools supported, no NL assertions, no policy concerns. |
| 83 | train | supported | - | 1 | - | All tools supported, no NL assertions, no policy concerns. |
| 84 | train | supported | - | 1 | - | All tools supported, no NL assertions, no policy concerns. |
| 85 | train | supported | - | 1 | - | All tools supported, no NL assertions, no policy concerns. |
| 86 | test | supported | - | 2 | - | All tools supported, no NL assertions, no policy concerns. |
| 87 | train | supported | - | 4 | - | All tools supported, no NL assertions, no policy concerns. |
| 88 | train | supported | - | 1 | - | All tools supported, no NL assertions, no policy concerns. |
| 89 | train | partial | partial_nl_assertion | 1 | ✓ | has NL assertions |
| 90 | test | supported | - | 1 | - | All tools supported, no NL assertions, no policy concerns. |
| 91 | train | supported | - | 2 | - | All tools supported, no NL assertions, no policy concerns. |
| 92 | train | supported | - | 2 | - | All tools supported, no NL assertions, no policy concerns. |
| 93 | train | supported | - | 1 | - | All tools supported, no NL assertions, no policy concerns. |
| 94 | test | supported | - | 1 | - | All tools supported, no NL assertions, no policy concerns. |
| 95 | train | partial | partial_nl_assertion | 2 | ✓ | has NL assertions |
| 96 | train | supported | - | 2 | - | All tools supported, no NL assertions, no policy concerns. |
| 97 | test | supported | - | 2 | - | All tools supported, no NL assertions, no policy concerns. |
| 98 | train | supported | - | 3 | - | All tools supported, no NL assertions, no policy concerns. |
| 99 | train | supported | - | 2 | - | All tools supported, no NL assertions, no policy concerns. |
| 100 | test | supported | - | 2 | - | All tools supported, no NL assertions, no policy concerns. |
| 101 | test | supported | - | 3 | - | All tools supported, no NL assertions, no policy concerns. |
| 102 | test | supported | - | 3 | - | All tools supported, no NL assertions, no policy concerns. |
| 103 | train | partial | partial_nl_assertion | 4 | ✓ | has NL assertions |
| 104 | train | partial | partial_nl_assertion | 5 | ✓ | has NL assertions |
| 105 | train | partial | partial_nl_assertion | 1 | ✓ | has NL assertions |
| 106 | train | partial | partial_nl_assertion | 1 | ✓ | has NL assertions |
| 107 | train | partial | partial_nl_assertion | 2 | ✓ | has NL assertions |
| 108 | test | partial | partial_nl_assertion | 1 | ✓ | has NL assertions |
| 109 | train | partial | partial_nl_assertion | 3 | ✓ | has NL assertions |
| 110 | train | partial | partial_nl_assertion | 3 | ✓ | has NL assertions |
| 111 | test | partial | partial_nl_assertion | 3 | ✓ | has NL assertions |
| 112 | train | supported | - | 3 | - | All tools supported, no NL assertions, no policy concerns. |
| 113 | train | partial | partial_nl_assertion | 2 | ✓ | has NL assertions |

## 5. NL Assertion 分析

- **含 NL assertion 的 task 数**: 40
- **NL assertion 总数**: 61

### 5.1 按类型分布

| 类型 | 数量 | 说明 |
|------|------|------|
| must_say | 61 | Agent 必须说出特定信息 |
| must_not_say | 0 | Agent 不得提及特定内容 |
| must_convey | 0 | Agent 必须传达概念（措辞不限） |

### 5.2 代表性示例

**must_say**:
- Agent should tell the user that there are 10 t-shirt options available.
- Agent should tell the user that there are 10 t-shirt options available.
- Agent should tell the user that there are 10 t-shirt options available.

### 5.3 与现有 eval 能力的映射

- `must_say` 类型可部分映射到 `expected_assistant_contains`，但 tau3 的 assertion 往往要求精确数值（如退款金额），当前 agent 的响应文本可能措辞不同但语义正确。
- `must_not_say` 类型当前无直接对应的 eval 断言机制。
- `must_convey` 类型最适合 `expected_assistant_contains`，但仍需人工判断。
- **建议**: Phase 9 首批 ingestion 中将 NL assertion 标记为 `partial`，不作为 gate；后续可引入 LLM-based NL assertion evaluator。

### 5.4 含 NL Assertion 的 Task 列表

共 40 个 task: 2, 3, 4, 16, 19, 21, 24, 28, 29, 36, 37, 38, 39, 40, 43, 44, 45, 46, 47, 54, 59, 60, 62, 63, 67, 68, 70, 76, 89, 95, 103, 104, 105, 106, 107, 108, 109, 110, 111, 113

## 6. 按 Capability 维度聚合

| Capability | 总数 | Supported | Partial | Unsupported | Train | Test |
|-----------|------|-----------|---------|-------------|-------|------|
| cancel | 18 | 12 | 6 | 0 | 13 | 5 |
| exchange | 28 | 20 | 8 | 0 | 18 | 10 |
| lookup | 5 | 2 | 3 | 0 | 2 | 3 |
| modify_address | 17 | 11 | 6 | 0 | 11 | 6 |
| modify_items | 17 | 8 | 9 | 0 | 10 | 7 |
| modify_payment | 1 | 0 | 1 | 0 | 0 | 1 |
| modify_user_address | 3 | 0 | 3 | 0 | 1 | 2 |
| return | 20 | 13 | 7 | 0 | 15 | 5 |
| transfer | 3 | 3 | 0 | 0 | 2 | 1 |
| unknown | 2 | 0 | 0 | 2 | 2 | 0 |

### 6.2 与现有 Capability Matrix 对照

现有 capability matrix（`docs/phase5-capability-matrix.md`）覆盖的能力：

| Capability | 现有 Eval 覆盖 | tau3 Task 数 | 差距 |
|-----------|---------------|-------------|------|
| cancel | generalized_mvp | 18 | ⚠️ 需扩展 |
| exchange | generalized_mvp | 28 | ⚠️ 需扩展 |
| lookup | curated_mvp + generalized_mvp | 5 | ✅ 接近 |
| modify_address | generalized_mvp | 17 | ⚠️ 需扩展 |
| modify_items | generalized_mvp | 17 | ⚠️ 需扩展 |
| modify_payment | generalized_mvp | 1 | ✅ 接近 |
| modify_user_address | generalized_mvp | 3 | ✅ 接近 |
| return | generalized_mvp | 20 | ⚠️ 需扩展 |
| transfer | generalized_mvp | 3 | ✅ 接近 |

## 7. 已知问题 Task

`task_issues/` 目录包含 3 个历史执行问题记录：

- `task_4_issue_2b74ee61.json`
- `task_5_issue_770466c1.json`
- `task_7_issue_9a37c151.json`

这些文件是 tau3 benchmark 的执行日志（包含 termination_reason、reward_info 等），
而非 task 定义本身的问题。它们记录了 agent 在 tau3 原生环境中执行时的失败案例，
可作为 Phase 9 smoke test 的参考——优先验证 task 4/5/7 在我们的 Agent 中能否通过。

## 8. Phase 9 首批 Ingestion 建议

### 8.1 推荐接入范围

- **全量 supported task**: 69 个（train 43 + test 26）
- **可考虑接入的 partial task**: 43 个
  - 其中 `partial_nl_assertion` 子类: 32 个（仅 NL assertion 差距，core workflow 完整）
  - 其中 `partial_missing_tool` 子类: 2 个
- **建议排除的 unsupported task**: 2 个

### 8.2 分阶段接入策略

**第一步: Smoke Test**
- 选取 5 个 supported task 验证 task → EvalCase 转换和 reward evaluation 流程
- 优先选择 task_issues 中已知有问题的 task（4/5/7），验证我们的 Agent 能否改善

**第二步: Supported 全量接入**
- 接入全部 69 个 supported task
- 新增 subset: `tau_retail_supported`
- 作为 Phase 9 的 gate

**第三步: Partial 接入**
- 接入 43 个 partial task，NL assertion 作为非 gate 参考维度
- 新增 subset: `tau_retail_partial`

### 8.3 风险提示

1. **NL Assertion 验证**: 40 个 task 有 NL assertion，当前无法自动验证。Phase 9 首批应将其作为非 gate 指标。
2. **`calculate` 工具**: 11 个 task 依赖此工具。Agent 可在 response 中包含退款金额而不显式调用 `calculate`，但 reward evaluation 可能期望此 tool call。
3. **DB State**: 所有 114 个 task 的 `initial_state` 为 null，tau3 使用完整 DB。Phase 9 需要确保每次 eval run 的 DB 初始状态一致。
4. **User Simulation**: tau3 task 的 `user_scenario.instructions` 定义了用户行为脚本。Phase 9 需要实现 user simulator adapter 来驱动多轮对话。
5. **Policy 差异**: tau3 的 `policy.md` 与我们的 guard rules 可能存在细微差异，需要在 smoke test 中逐条对照。

### 8.4 排除项

- 2 个 unsupported task（原因: 无 action 或包含完全不支持的工具）
- 短期内不考虑 `get_item_details` 工具实现（仅 3 个 task 使用）
- 不引入 `calculate` 工具（Agent 的 LLM 推理可替代简单数学计算）

## 9. Phase 12 Coverage Expansion Queue

### 9.1 Coverage rungs

| Metric | Value |
|--------|-------|
| current_supported | 69 |
| live_promoted_count | 11 |
| effective_supported | 80 |
| target_total | 69 |
| total_tasks | 114 |
| stable_40_plus | True |
| stable_50_plus | True |
| stable_55_plus | True |
| remaining_to_40 | 0 |
| remaining_to_50 | 0 |
| remaining_to_55 | 0 |
| remaining_to_all_tasks | 34 |
| current_rung | stable_55_plus |
| next_target | None |
| remaining_to_next | 0 |
| safe_candidate_count | 33 |
| schema_ready_count | 0 |
| projected_supported_after_safe_candidates | 113 |
| can_reach_next_with_safe_candidates | True |

### 9.2 Next candidates

| Task ID | Category | Priority | Blocking reasons |
|---------|----------|----------|------------------|
| 2 | prompt_or_response_gap | 30 | NL assertion requires response evidence |
| 3 | prompt_or_response_gap | 30 | NL assertion requires response evidence |
| 4 | prompt_or_response_gap | 30 | NL assertion requires response evidence |
| 19 | prompt_or_response_gap | 30 | NL assertion requires response evidence |
| 24 | prompt_or_response_gap | 30 | NL assertion requires response evidence |
| 29 | prompt_or_response_gap | 30 | NL assertion requires response evidence |
| 33 | prompt_or_response_gap | 30 | NL assertion requires response evidence |
| 34 | prompt_or_response_gap | 30 | NL assertion requires response evidence |
| 36 | prompt_or_response_gap | 30 | NL assertion requires response evidence |
| 37 | prompt_or_response_gap | 30 | NL assertion requires response evidence |

### 9.3 Phase 12 Live Evidence

| Metric | Value |
|--------|-------|
| eval_run_id | eval-7070677ce432 |
| subset | tau_phase12_schema_ready |
| eval_backend | live |
| created_at | 2026-06-15T07:51:43.659533+00:00 |
| passed_count | 2 |
| case_count | 2 |
| promoted_task_ids | 49, 61 |
| pass_rate | 1.0000 |
| tool_call_success_rate | 0.9500 |
| mutation_error_rate | 0.0000 |
| promotable | True |

#### Additional Phase 12 Evidence

| Subset | Eval Run | Passed | Pass Rate | Promotable | Failure labels |
|--------|----------|--------|-----------|------------|----------------|
| tau_phase12_nl_evidence | eval-43cc70fe58ee | 9/9 | 1.0000 | True | - |

### 9.4 Expansion rule

Phase 12 coverage must come from tool/schema/prompt/guard changes, not runtime case-specific parser branches.
