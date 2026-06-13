# Phase 8b: Language Variation 与 Synthetic Workbench — 设计文档

日期：2026-06-13
状态：已确认

## 1. 目标

在 Phase 8a 的 deterministic scenario core 上增加可复现语言变化，并把 generated scenario 接入 Workbench 展示与回放。Phase 8b 不引入 LLM 生成作为 gate，第一版只使用模板和规则改写，保证每个 seed、variant 和 language level 都能稳定复现。

## 2. 范围

本阶段实现最小可验收闭环：

- **L1 同义词变化**：对核心动词短语做规则替换，例如 cancel -> void / stop / discontinue。
- **L2 信息排列变化**：把 email、order id、目标动作的位置改写到句首、句尾或同一句不同顺序。
- **L3 信息缺失 + 多轮**：作为非阻塞探索集，生成缺 order id 或缺 email 的多轮脚本，但不进入 gate。
- **Workbench generated scenario 入口**：在 case catalog 中展示 generated scenario，包含 seed、language level、request messages、expected oracle 和 trace。
- **Replay generated scenario**：复用 Workbench 已有 `run-all` 流程，确保 selected generated case 能按自身 seed 创建 synthetic runtime 并回放脚本。

## 3. 非目标

- 不接入 LLM 生成自然语言变体。
- 不把 L3 纳入 pass gate。
- 不重写 Workbench 布局，只增加已有面板能消费的 metadata。
- 不新增独立 replay runner；Workbench 的 step/run-all 已足够表达回放。

## 4. 架构决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Language variation 位置 | `app/synthetic/language_variation.py` | 让语言改写和 family/oracle 分离，便于单独测试 |
| Gate subset | 复用 `generalization`，追加 L1/L2 cases | Phase 8a gate 已经接入 synthetic runtime 和报告 |
| L3 subset | 新增 `generalization_exploratory` | 非阻塞探索集不影响 8a/8b gate |
| EvalCase metadata | 增加 `variant_type`、`language_variation_level`、`scenario_family` | runner/report/workbench 都需要稳定字段，避免从 `case_id` 反推 |
| Workbench runtime | `synthetic_seeded_v1`、`generalization`、`generalization_exploratory` 都按 case seed 创建 synthetic runtime | generated scenario 必须使用自己的 synthetic world |
| Replay | 复用 `run-all` | 当前 session 已经保留 script cursor、trace 和 DB hash |

## 5. 数据模型

`EvalCase` 新增字段：

- `scenario_family: str | None`
- `variant_type: str | None`
- `language_variation_level: str | None`

`language_variation_level` 取值：

- `base`：Phase 8a 原始 deterministic text
- `L1`：同义词变化
- `L2`：信息排列变化
- `L3`：探索集多轮缺失信息

## 6. Language Variation

新增模块 `app/synthetic/language_variation.py`：

```python
@dataclass(frozen=True)
class LanguageVariant:
    level: str
    suffix: str
    messages: list[dict[str, str]]
    gate: bool
```

核心函数：

- `build_language_variants(base_messages, variant_type, entities) -> list[LanguageVariant]`
- `language_variant_levels_for_gate() -> tuple[str, ...]`

生成规则：

- `base` 总是保留。
- `L1` 保持 turn 数不变，只改写主要动作短语。
- `L2` 保持 turn 数不变，调整 email/order/action 的排列。
- `L3` 可增加 turn 数，用缺失信息触发 clarification；第一版只进入 exploratory subset。

## 7. Eval 集成

`build_generalization_cases()` 默认输出：

- 15 个 base cases。
- 每个 base case 派生 L1 和 L2，共 30 个 language gate variants。
- gate 总数为 45。

`build_generalization_exploratory_cases()` 输出：

- L3 variants。
- subset 为 `generalization_exploratory`。
- 不计入 `generalization` gate。

case id 规则：

- base 保持原 case id，例如 `cancel_success_s100`。
- L1/L2/L3 追加后缀，例如 `cancel_success_s100_l1`。

## 8. Reporting

`EvalCaseResult` 和 report artifact 保留：

- `scenario_family`
- `variant_type`
- `seed`
- `language_variation_level`

`build_failure_analysis()` 增加按 language variation level 的聚合，便于区分基础 scenario 问题和语言变化问题。

## 9. Workbench

Workbench case catalog 增加 generated scenario 分组：

- 展示 `generalization` 中的 generated cases。
- 序列化每个 case 的 seed、scenario family、variant type、language variation level、expected oracle 关键字段。
- `get_case_by_id()` 能找到 generalization 和 exploratory cases。

`WorkbenchSession._create_runtime_and_state_for()` 对 generated subsets 使用 `SyntheticRetailAdapter(seed=case.seed or 42)`。这样 `run-all` 时读取的 DB 与 scenario 生成时的 DB 一致。

## 10. 验收标准

- seeded L1/L2 language variants 可复现。
- `generalization` 包含 base + L1 + L2 cases，且每个 case 保留 seed、family、variant type、language level。
- L3 只出现在 `generalization_exploratory`。
- runner report 能按 language level 聚合。
- Workbench config 能返回 generated scenario metadata。
- Workbench selected generated case 能按自身 seed replay，并产生 trace。
