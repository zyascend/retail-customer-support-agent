# Phase 8a: Agent Generalization Core — 设计文档

日期：2026-06-13
状态：设计中（待用户审阅）

## 1. 目标

从 Phase 7 的单一合成世界（seed=42）升级为系统化泛化评测核心。证明 Agent 不是记住固定案例，而是在不同合成世界中真正具备泛化能力。

## 2. 通俗理解

- **Phase 7** = 在一个假世界里手写了 7 道题
- **Phase 8a** = 自动在多个假世界里出 15 道题，自动判卷，出成绩单
- **目标**：15 道题全部通过

## 3. 架构决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Variant 变化维度 | 不同 seed / 不同合成世界 | 核心目标是世界级泛化；Phase 8b 单独处理语言变体 |
| Oracle 生成方式 | 自动派生 | variant 声明类型（如 `cancel_success`），oracle 自动计算所有 expected 字段 |
| Family 定义位置 | `app/synthetic/families.py` | 与 generator、adapter 同包，复用 `SyntheticDBGenerator` |
| Oracle 定义位置 | `app/synthetic/oracle.py` | 独立模块，family 和 oracle 职责分离 |
| Eval 集成 | 新增 `generalization` subset | 不改 EvalCase 模型，通过 family generator 动态生成 EvalCase |
| Report 集成 | 扩展现有 metrics | 新增 family/variant_type/seed/failure_source 维度 |

## 4. 模块结构

```
app/synthetic/                         # 已有
├── generator.py   — SyntheticDBGenerator (不变)
├── adapter.py     — SyntheticRetailTools + Adapter (不变)
├── oracle.py      — 🆕 DeterministicOracle 数据类 + derive_oracle()
└── families.py    — 🆕 ScenarioFamily 定义 + VariantGenerator

app/eval/
├── cases.py       — 扩展：get_cases() 支持 "generalization" subset
├── runner.py      — 扩展：batch run + family metadata 注入
└── metrics.py     — 扩展：generalization report 聚合维度

tests/
└── test_generalization.py  — 🆕 单元测试
```

## 5. 数据模型 (`oracle.py`)

```python
@dataclass
class DeterministicOracle:
    """从 variant 类型自动派生的标准答案"""
    expected_user_id: str
    expected_intent: str
    order_id: str | None
    expected_write_lock: str | None
    expected_order_status: str | None
    expected_confirmation_status: str
    expected_guard_block_reason: str | None
    expected_no_write: bool
    expected_tool_names: list[str]
    expected_db_assertions: dict
    expected_tool_sequence: list[str]
```

`derive_oracle(world, entities, variant_type) -> DeterministicOracle` 根据 variant_type 自动填充所有字段。variant_type 枚举包括：

- `cancel_success` — pending 订单确认取消
- `cancel_block_nonpending` — 非 pending 订单阻止取消
- `cancel_block_wrong_user` — 他人订单阻止操作
- `shipping_success_express` — standard → express 成功
- `shipping_success_overnight` — standard → overnight 成功
- `shipping_block_same_method` — 相同配送方式阻止
- `shipping_block_nonpending` — 非 pending 订单阻止
- `shipping_block_unknown_method` — 无效配送方式阻止
- `coupon_transfer_no_write` — 优惠券/折扣/赔偿请求 → transfer

## 6. Scenario Family (`families.py`)

### ScenarioFamily

```python
@dataclass
class ScenarioFamily:
    name: str                  # "cancel" | "modify_shipping" | "coupon_refusal"
    capability: str            # capability 标签
    policy_area: str           # policy 标签
    variants: list[FamilyVariant]
    
    def generate(self, seed: int) -> ScenarioVariant: ...
```

### FamilyVariant

```python
@dataclass
class FamilyVariant:
    variant_id: str            # "cancel_success_s100"
    variant_type: str          # 类型枚举值
    seed: int                  # 合成世界种子
    entity_selector: Callable  # 从世界中选取合适的实体
    message_template: Callable # 拼装对话
```

### 三个 Family 的 15 个 Variant

#### cancel family (5 variants, seeds 100-104)

| variant_id | seed | variant_type | 场景 |
|-----------|------|-------------|------|
| cancel_success_s100 | 100 | cancel_success | pending 订单确认取消 |
| cancel_success_s101 | 101 | cancel_success | 同上，不同世界 |
| cancel_success_s102 | 102 | cancel_success | 同上，不同世界 |
| cancel_block_nonpending_s103 | 103 | cancel_block_nonpending | 非 pending 订单阻止 |
| cancel_block_wrong_user_s104 | 104 | cancel_block_wrong_user | 他人订单阻止操作 |

#### modify_shipping family (5 variants, seeds 200-204)

| variant_id | seed | variant_type | 场景 |
|-----------|------|-------------|------|
| shipping_express_s200 | 200 | shipping_success_express | standard→express + credit card |
| shipping_overnight_s201 | 201 | shipping_success_overnight | standard→overnight + credit card |
| shipping_block_same_s202 | 202 | shipping_block_same_method | 同方法阻止 |
| shipping_block_nonpending_s203 | 203 | shipping_block_nonpending | 非 pending 订单阻止 |
| shipping_block_unknown_s204 | 204 | shipping_block_unknown_method | 无效配送方式阻止 |

#### coupon_refusal family (5 variants, seeds 300-304)

| variant_id | seed | variant_type | 场景 |
|-----------|------|-------------|------|
| coupon_transfer_s300 | 300 | coupon_transfer_no_write | 要折扣 → transfer |
| coupon_transfer_s301 | 301 | coupon_transfer_no_write | 要赔偿 → transfer |
| coupon_transfer_s302 | 302 | coupon_transfer_no_write | 要优惠 → transfer |
| coupon_transfer_s303 | 303 | coupon_transfer_no_write | 同上，不同世界 |
| coupon_transfer_s304 | 304 | coupon_transfer_no_write | 同上，不同世界 |

## 7. 实体选取逻辑

每个 variant 的 `entity_selector` 从合成世界中选取合适的实体：

- **cancel_success**: 选取 status=pending、user_id 匹配的订单
- **cancel_block_nonpending**: 选取 status≠pending 的订单
- **cancel_block_wrong_user**: 选取不属于当前用户的订单
- **shipping_success_express/overnight**: 选取 status=pending、shipping=standard 的订单
- **shipping_block_same_method**: 选取现有 shipping 不等于目标方法的 pending 订单（然后用现有方法作为目标）
- **shipping_block_nonpending**: 选取 status≠pending 的订单
- **shipping_block_unknown_method**: 选取任意 pending 订单（对话中使用无效配送方式名）
- **coupon_transfer_no_write**: 选取任意属于当前用户的订单（不实际写操作）

如果选取不到合适实体（如 seed 生成的世界没有 pending 订单），则 fallback 到下一个 seed。

## 8. Oracle 自动派生 (`oracle.py`)

```python
VARIANT_ORACLE_DERIVERS: dict[str, Callable] = {
    "cancel_success": _derive_cancel_success,
    "cancel_block_nonpending": _derive_cancel_block_nonpending,
    "cancel_block_wrong_user": _derive_cancel_block_wrong_user,
    "shipping_success_express": _derive_shipping_success_express,
    "shipping_success_overnight": _derive_shipping_success_overnight,
    "shipping_block_same_method": _derive_shipping_block_same,
    "shipping_block_nonpending": _derive_shipping_block_nonpending,
    "shipping_block_unknown_method": _derive_shipping_block_unknown,
    "coupon_transfer_no_write": _derive_coupon_transfer,
}
```

每个派生函数接收 `(world, entities)` 返回 `DeterministicOracle`。所有字段从 variant_type + 实体信息自动计算，无需人工为每个 variant 填写。

## 9. Eval 集成

### cases.py 扩展

```python
def get_cases(subset: str) -> list[EvalCase]:
    if subset == "generalization":
        return build_generalization_cases()
    # ... 已有逻辑

def build_generalization_cases() -> list[EvalCase]:
    cases = []
    for family in ALL_FAMILIES:
        for variant in family.variants:
            scenario = family.generate(variant.seed)
            cases.append(scenario.to_eval_case())
    return cases
```

### runner.py 扩展

在 `EvalCaseResult` 或运行流程中注入：
- `scenario_family` — 所属 family 名称
- `variant_type` — variant 类型
- `seed` — 生成种子
- `failure_source` — 失败来源分类

### CLI

```bash
uv run phase2-eval --subset generalization --trials 1
```

## 10. Report 扩展 (`metrics.py`)

新增聚合维度：
- 按 `scenario_family` 聚合（每个 family 的通过率）
- 按 `variant_type` 聚合（success 型 vs guard_block 型 vs no_write 型）
- 按 `failure_source` 分类（parsing / planning / guard / tool_mutation / response）

失败来源分类规则：
- **parsing**: intent 识别错误
- **planning**: action_planner 选择错误操作
- **guard**: guard 误拦或漏拦
- **tool_mutation**: DB 变更与预期不符
- **response**: 最终回复不符合预期

## 11. Gate 定义

- 15 个 generated cases 全部通过（pass=1）
- generated no-write cases（coupon_refusal family）保持 DB hash 不变
- generated success cases（cancel/modiify_shipping）仅修改预期字段
- seeded generated batch 可完全复现（同 seed 同结果）

## 12. 验收标准

- [ ] 一个 seeded generated batch 可以完全复现
- [ ] 15 个 generated gate cases 全部通过
- [ ] generated no-write cases 保持 DB hash 不变
- [ ] generated successful write cases 只修改预期字段
- [ ] report 能清晰说明失败来自 parsing、planning、guard 还是 tool execution
- [ ] 现有 `curated_mvp`（11 case）、`generalized_mvp`（30 case）、`synthetic_seeded_v1`（7 case）仍然通过
- [ ] 单元测试覆盖 oracle 派生逻辑和 entity selector
- [ ] `uv run ruff check .` 通过
- [ ] `uv run ruff format --check .` 通过

## 13. 待实现任务

1. 创建 `app/synthetic/oracle.py`（DeterministicOracle + derive_oracle）
2. 创建 `app/synthetic/families.py`（ScenarioFamily + 3 个 family 定义 + VariantGenerator）
3. 扩展 `app/eval/cases.py`（`get_cases()` 支持 `"generalization"` subset + `build_generalization_cases()`）
4. 扩展 `app/eval/runner.py`（场景族元数据注入 + failure_source 分类）
5. 扩展 `app/eval/metrics.py`（generalization report 聚合维度）
6. 新增 `tests/test_generalization.py`（单元测试覆盖 oracle 派生 + entity selector + 端到端 15 cases）
7. 运行 generalization gate 验证（15 cases 全部通过）
8. 回归验证（curated_mvp / generalized_mvp / synthetic_seeded_v1 通过）
