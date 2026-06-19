# Bad Case 数据飞轮设计

> 日期：2026-06-19
> 状态：Approved

## 目标

建立 eval failure → 归因 → 变体生成 → golden 回归的自动化闭环，使系统"越用越聪明"。

## 现状分析

| 组件 | 状态 | 位置 |
|------|------|------|
| `classify_failure()` (runner) | ✅ 14+ failure labels | `app/eval/runner.py:585-686` |
| `classify_failure()` (triage) | ✅ 6 buckets + 7 root causes | `app/eval/live_triage.py` |
| `failure_source` 映射 | ✅ parsing/planning/guard/tool_mutation/response | `app/eval/metrics.py:193-209` |
| Synthetic generator | ✅ 15 FamilyVariant + language L1/L2/L3 | `app/synthetic/` |
| 自动修复动作 | ❌ 缺失 | — |
| Bad case → 文件导出 | ❌ 缺失 | — |
| Bad case → golden set | ❌ 缺失 | — |
| Bad case → 变体生成 | ❌ 缺失 | — |

核心差距：**triage 分类但不执行**。飞轮在每个转换点断裂。

## 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 自动化边界 | **半自动** | 自动收集/归因/变体/golden，修复需人工确认 |
| Golden set 存储 | **YAML 文件** | 独立可审计，可 git-tracked |
| 变体生成策略 | **复用语言变体 L1/L2** | 已有 `build_language_variants()` 基础设施 |
| 实现方案 | **Flywheel Pipeline** | 四阶段职责分离，可独立测试 |

## 架构

```
eval report ──→ collect ──→ generate ──→ promote ──→ check
                  │            │            │          │
                  ▼            ▼            ▼          ▼
            bad_cases/    bad_cases/   golden.yaml  回归报告
            <date>.yaml   <date>_       (回归集)
                          variants.yaml
```

### 四阶段

#### Stage 1: `flywheel collect` — Bad Case 收集

```bash
uv run flywheel collect --report artifacts/phase2/reports/eval-abc123.json
```

1. 读取 eval report JSON
2. 过滤 `passed == False` 的 results
3. 对每个失败 case 调用 `classify_failure()` + `infer_root_cause()` + `failure_source` 映射
4. 组装 bad case 记录（完整 EvalCase 字段 + 诊断信息）
5. 去重：同一 `case_id` 在同日文件中只保留最后一次失败记录
6. 写入 `cases/bad_cases/<YYYY-MM-DD>.yaml`

#### Stage 2: `flywheel generate` — 变体生成

```bash
uv run flywheel generate [--input cases/bad_cases/2026-06-19.yaml] [--output cases/bad_cases/2026-06-19_variants.yaml]
```

1. 读取 bad_cases 文件
2. 过滤已有 L1/L2 变体的 case
3. 调用 `build_language_variants(messages, variant_type, entities)` 生成 L1/L2
4. Synthetic case 用 `SyntheticDBGenerator.from_seed(seed)` 重建 world
5. 写入 `_variants.yaml`

**限制：** 只对有 `variant_type` 的 case 生成变体（synthetic/generalization family）。tau 和 curated hand-written case 不生成变体（oracle 无法自动推导）。

#### Stage 3: `flywheel golden promote` — 合入 Golden Set

```bash
uv run flywheel golden promote <case_id>
uv run flywheel golden promote --batch cases/bad_cases/2026-06-19.yaml
```

1. 从 bad_cases YAML 查找 case
2. 展示 case 摘要（failure_label、root_cause、suggested_next_action）
3. 用户确认（`y`/`s`/`q`）
4. 写入 `cases/golden.yaml`，设置 `expected_pass: true`
5. 源 bad_cases YAML 标记 `promoted: true`

#### Stage 4: `flywheel check` — 回归校验

```bash
uv run flywheel check [--live]
```

1. 读取 `cases/golden.yaml`，构造 EvalCase 列表
2. 注册为临时 subset `golden`
3. 调用 `CuratedEvalRunner` 跑全量
4. 对比结果：
   - `expected_pass: true` 且 fail → **回归失败**
   - `expected_pass: false` 且 pass → **意外通过**（记录）
5. 输出摘要 + 退出码（有回归 → exit 1）

## 文件结构

```
app/eval/
  flywheel.py          # 飞轮四阶段编排 (~300 行)
  bad_case_store.py    # bad case YAML I/O (~150 行)
  golden_set.py        # golden set 管理 + 回归校验 (~200 行)
app/cli/
  flywheel.py          # CLI 入口

cases/
  bad_cases/            # 自动生成，git-tracked
    2026-06-19.yaml
  golden.yaml          # 手动确认合入的回归 golden set
```

## 数据模型

### bad_cases YAML

```yaml
collected_at: "2026-06-19T10:30:00Z"
eval_run_id: eval-abc123
subset: generalized_mvp

bad_cases:
  - case_id: modify_shipping_001_L1
    source_case_id: modify_shipping_001
    failure_label: wrong_tool
    failure_bucket: tool_selection
    root_cause: prompt_gap
    failure_source: planning
    messages: [...]
    expected_user_id: U1001
    expected_intent: modify_shipping_method
    order_id: "#W1234567"
    expected_write_lock: null
    expected_order_status: null
    expected_confirmation_status: confirmed
    expected_guard_block_reason: null
    expected_no_write: false
    expected_tool_names:
      - get_order_details
      - modify_pending_order_shipping_method
    expected_assistant_contains: null
    max_turns: 8
    subset: generalization
    scenario_family: modify_shipping
    variant_type: shipping_success_express
    language_variation_level: L1
    seed: 200
    expected_db_assertions: {}
    expected_tool_sequence: []
    promoted: false
    diagnostics:
      actual_tool_names: [get_order_details]
      suggested_next_action: "Compare expected and actual tool calls..."
```

### golden.yaml

```yaml
version: 1
entries:
  - case_id: modify_shipping_001_L1
    added_at: "2026-06-20T08:00:00Z"
    promoted_from: bad_cases/2026-06-19.yaml
    failure_label: wrong_tool
    root_cause: prompt_gap
    expected_pass: true
    messages: [...]
    expected_user_id: U1001
    expected_intent: modify_shipping_method
    order_id: "#W1234567"
    expected_write_lock: null
    expected_order_status: null
    expected_confirmation_status: confirmed
    expected_guard_block_reason: null
    expected_no_write: false
    expected_tool_names:
      - get_order_details
      - modify_pending_order_shipping_method
    expected_assistant_contains: null
    max_turns: 8
    subset: golden
    scenario_family: modify_shipping
    variant_type: shipping_success_express
    language_variation_level: L1
    seed: 200
    expected_db_assertions: {}
    expected_tool_sequence: []
```

## 与现有系统的集成

| 现有组件 | 集成方式 |
|---------|---------|
| `classify_failure()` | Stage 1 直接复用 |
| `infer_root_cause()` | Stage 1 直接复用 |
| `failure_source_map` | Stage 1 直接复用 |
| `build_language_variants()` | Stage 2 直接复用 |
| `SyntheticDBGenerator.from_seed()` | Stage 2 重建 world |
| `CuratedEvalRunner` | Stage 4 直接复用 |
| `EvalCase` | YAML ↔ EvalCase 序列化/反序列化 |
| `build_comparison_artifact()` | Stage 4 内部调用 |

## 自动化边界

| 动作 | 自动/手动 |
|------|----------|
| eval failure → 收集 bad case | 自动 |
| bad case → 生成变体 | 自动 |
| 修复代码后 → 标记已修复 | 手动 |
| 已修复 case → 合入 golden | 半自动（需确认） |
| golden set → 回归校验 | 自动（可 CI 触发） |
| prompt/schema/guard 自动修改 | 手动（不在范围内） |

## 测试策略

| 模块 | 测试方式 |
|------|---------|
| `bad_case_store.py` | pytest + tmpdir，roundtrip YAML ↔ dataclass |
| `golden_set.py` | 构造 golden entries，断言 promote/check 行为 |
| `flywheel.py` 编排 | fixture eval report → collect → generate → promote → check |
| `app/cli/flywheel.py` | subprocess 测试 |

所有测试走 mock 或 synthetic adapter，不依赖 real LLM。
