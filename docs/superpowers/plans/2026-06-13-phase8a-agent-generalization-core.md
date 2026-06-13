# Phase 8a Agent Generalization Core — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Phase 7 的单一 seed 合成评测升级为系统化泛化评测核心 — 3 个 scenario family × 5 个 variant = 15 个自动生成案例，全部通过。

**Architecture:** 新增 `oracle.py`（标准答案自动派生）和 `families.py`（场景族定义 + 变体生成），扩展 `cases.py`/`runner.py`/`metrics.py` 以支持 generated batch 和 scene family 维度的报告聚合。每个 variant 使用不同 seed 生成独立合成世界，从世界中自动选取实体 + 拼装对话 + 派生 oracle。

**Tech Stack:** Python 3.12+, dataclasses, pytest, 复用现有 `SyntheticDBGenerator` + `SyntheticRetailAdapter`

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `app/synthetic/oracle.py` | 新建 | `DeterministicOracle` 数据类 + `derive_oracle()` |
| `app/synthetic/families.py` | 新建 | `FamilyVariant`, `ScenarioFamily`, 3 个 family 定义, `build_generalization_cases()` |
| `app/eval/cases.py` | 修改 | `EvalCase` 新增 `seed` 字段, `get_cases()` 支持 `"generalization"` |
| `app/eval/runner.py` | 修改 | `_run_case()` 处理 generalization subset, `EvalRunSummary` + `EvalCaseResult` 新增字段 |
| `app/eval/metrics.py` | 修改 | `build_failure_analysis()` 新增 family/variant_type 聚合维度 |
| `tests/test_generalization.py` | 新建 | oracle 派生逻辑 + entity selector + 端到端 15 case 验证 |

---

### Task 1: 创建 `DeterministicOracle` 数据类

**Files:**
- Create: `app/synthetic/oracle.py`
- Test: `tests/test_generalization.py`

- [ ] **Step 1: 写 `DeterministicOracle` 数据类**

```python
# app/synthetic/oracle.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class DeterministicOracle:
    """从 variant 类型自动派生的标准答案"""
    expected_user_id: str
    expected_intent: str
    order_id: str | None = None
    expected_write_lock: str | None = None
    expected_order_status: str | None = None
    expected_confirmation_status: str = "confirmed"
    expected_guard_block_reason: str | None = None
    expected_no_write: bool = False
    expected_tool_names: List[str] = field(default_factory=list)
    expected_db_assertions: Dict[str, Any] = field(default_factory=dict)
    expected_tool_sequence: List[str] = field(default_factory=list)
```

- [ ] **Step 2: Commit**

```bash
git add app/synthetic/oracle.py
git commit -m "feat: add DeterministicOracle data class"
```

---

### Task 2: 实现 `derive_oracle()` 核心派生函数

**Files:**
- Modify: `app/synthetic/oracle.py`
- Test: `tests/test_generalization.py`

- [ ] **Step 1: 写 cancel_success 的派生函数测试**

```python
# tests/test_generalization.py
import pytest
from app.synthetic.oracle import derive_oracle, DeterministicOracle
from app.synthetic.generator import SyntheticDBGenerator


def test_derive_cancel_success_oracle():
    world = SyntheticDBGenerator.from_seed(100)
    # 找一个 pending 订单
    pending_order = None
    for oid, order in world["orders"].items():
        if order["status"] == "pending":
            pending_order = order
            break
    assert pending_order is not None, "seed 100 must have at least one pending order"

    entities = {
        "order": pending_order,
        "user": world["users"][pending_order["user_id"]],
    }
    oracle = derive_oracle(world, entities, "cancel_success")
    
    assert oracle.expected_intent == "cancel_order"
    assert oracle.order_id == pending_order["order_id"]
    assert oracle.expected_user_id == pending_order["user_id"]
    assert oracle.expected_order_status == "cancelled"
    assert oracle.expected_write_lock == f"order:{pending_order['order_id']}:cancel"
    assert oracle.expected_confirmation_status == "confirmed"
    assert oracle.expected_no_write is False
    assert "cancel_pending_order" in oracle.expected_tool_names
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run python -m pytest tests/test_generalization.py::test_derive_cancel_success_oracle -v
```

- [ ] **Step 3: 实现 `derive_cancel_success`**

```python
# app/synthetic/oracle.py (追加)

def _derive_cancel_success(world: dict, entities: dict) -> DeterministicOracle:
    order = entities["order"]
    user = entities["user"]
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="cancel_order",
        order_id=order["order_id"],
        expected_write_lock=f"order:{order['order_id']}:cancel",
        expected_order_status="cancelled",
        expected_confirmation_status="confirmed",
        expected_no_write=False,
        expected_tool_names=["cancel_pending_order"],
    )
```

- [ ] **Step 4: 写 `derive_oracle()` 调度函数，先挂 cancel_success**

```python
# app/synthetic/oracle.py (追加)

VARIANT_ORACLE_DERIVERS = {
    "cancel_success": _derive_cancel_success,
}


def derive_oracle(world: dict, entities: dict, variant_type: str) -> DeterministicOracle:
    deriver = VARIANT_ORACLE_DERIVERS.get(variant_type)
    if deriver is None:
        raise ValueError(f"Unknown variant_type: {variant_type}")
    return deriver(world, entities)
```

- [ ] **Step 5: 运行测试确认通过**

```bash
uv run python -m pytest tests/test_generalization.py::test_derive_cancel_success_oracle -v
```

- [ ] **Step 6: 逐个添加其余 8 个派生函数及测试**

```python
# 每个派生函数约 10-15 行，完整代码:

def _derive_cancel_block_nonpending(world: dict, entities: dict) -> DeterministicOracle:
    order = entities["order"]
    user = entities["user"]
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="cancel_order",
        order_id=order["order_id"],
        expected_guard_block_reason="non_pending_order_cannot_be_cancelled",
        expected_no_write=True,
        expected_confirmation_status="confirmed",
        expected_tool_names=["cancel_pending_order"],
    )


def _derive_cancel_block_wrong_user(world: dict, entities: dict) -> DeterministicOracle:
    order = entities["order"]
    user = entities["user"]
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="cancel_order",
        order_id=order["order_id"],
        expected_no_write=True,
        # wrong_user 不是通过 guard_block_reason 拦截，而是身份解析层拦截
        # 所以不设 expected_guard_block_reason
        expected_tool_names=[],
    )


def _derive_shipping_success(world: dict, entities: dict) -> DeterministicOracle:
    order = entities["order"]
    user = entities["user"]
    target_method = entities.get("target_method", "express")
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="modify_shipping_method",
        order_id=order["order_id"],
        expected_write_lock=f"order:{order['order_id']}:modify_shipping_method",
        expected_confirmation_status="confirmed",
        expected_no_write=False,
        expected_tool_names=["modify_pending_order_shipping_method"],
    )


def _derive_shipping_block_same(world: dict, entities: dict) -> DeterministicOracle:
    order = entities["order"]
    user = entities["user"]
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="modify_shipping_method",
        order_id=order["order_id"],
        expected_guard_block_reason="same_shipping_method",
        expected_no_write=True,
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_pending_order_shipping_method"],
    )


def _derive_shipping_block_nonpending(world: dict, entities: dict) -> DeterministicOracle:
    order = entities["order"]
    user = entities["user"]
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="modify_shipping_method",
        order_id=order["order_id"],
        expected_guard_block_reason="non_pending_order_cannot_be_modified",
        expected_no_write=True,
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_pending_order_shipping_method"],
    )


def _derive_shipping_block_unknown(world: dict, entities: dict) -> DeterministicOracle:
    order = entities["order"]
    user = entities["user"]
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="modify_shipping_method",
        order_id=order["order_id"],
        expected_guard_block_reason="unknown_shipping_method",
        expected_no_write=True,
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_pending_order_shipping_method"],
    )


def _derive_coupon_transfer(world: dict, entities: dict) -> DeterministicOracle:
    user = entities["user"]
    order = entities.get("order")
    return DeterministicOracle(
        expected_user_id=user["user_id"],
        expected_intent="transfer",
        order_id=order["order_id"] if order else None,
        expected_no_write=True,
        expected_tool_names=["transfer_to_human_agents"],
    )
```

- [ ] **Step 7: 更新调度表**

```python
VARIANT_ORACLE_DERIVERS = {
    "cancel_success": _derive_cancel_success,
    "cancel_block_nonpending": _derive_cancel_block_nonpending,
    "cancel_block_wrong_user": _derive_cancel_block_wrong_user,
    "shipping_success_express": _derive_shipping_success,
    "shipping_success_overnight": _derive_shipping_success,
    "shipping_block_same_method": _derive_shipping_block_same,
    "shipping_block_nonpending": _derive_shipping_block_nonpending,
    "shipping_block_unknown_method": _derive_shipping_block_unknown,
    "coupon_transfer_no_write": _derive_coupon_transfer,
}
```

- [ ] **Step 8: 运行全部测试**

```bash
uv run python -m pytest tests/test_generalization.py -v
```

- [ ] **Step 9: Commit**

```bash
git add app/synthetic/oracle.py tests/test_generalization.py
git commit -m "feat: implement derive_oracle with 9 variant types"
```

---

### Task 3: Entity Selector — 从合成世界选取合适的实体

**Files:**
- Modify: `app/synthetic/oracle.py`
- Test: `tests/test_generalization.py`

- [ ] **Step 1: 写 entity selector 测试**

```python
def test_select_pending_order_for_cancel():
    world = SyntheticDBGenerator.from_seed(100)
    from app.synthetic.oracle import select_entity_for_variant
    entities = select_entity_for_variant(world, "cancel_success")
    assert entities["order"]["status"] == "pending"
    assert entities["user"]["user_id"] == entities["order"]["user_id"]


def test_select_non_pending_order():
    world = SyntheticDBGenerator.from_seed(103)
    from app.synthetic.oracle import select_entity_for_variant
    entities = select_entity_for_variant(world, "cancel_block_nonpending")
    assert entities["order"]["status"] != "pending"


def test_select_wrong_user_order():
    world = SyntheticDBGenerator.from_seed(104)
    from app.synthetic.oracle import select_entity_for_variant
    entities = select_entity_for_variant(world, "cancel_block_wrong_user")
    # 用户和订单不属于同一人
    assert entities["user"]["user_id"] != entities["order"]["user_id"]


def test_select_any_user_with_valid_email():
    """每个 variant 都需要一个 user，确保选中 user 有合法邮箱"""
    world = SyntheticDBGenerator.from_seed(300)
    from app.synthetic.oracle import select_entity_for_variant
    entities = select_entity_for_variant(world, "coupon_transfer_no_write")
    assert "@" in entities["user"]["email"]
```

- [ ] **Step 2: 实现 `select_entity_for_variant`**

```python
# app/synthetic/oracle.py (追加)

def select_entity_for_variant(world: dict, variant_type: str) -> dict:
    """从合成世界中选取适配 variant_type 的实体 (user + order)"""
    users = list(world["users"].values())
    orders = list(world["orders"].values())

    if variant_type == "cancel_success":
        for order in orders:
            if order["status"] == "pending":
                user = world["users"][order["user_id"]]
                return {"user": user, "order": order}
        raise ValueError("No pending order found for cancel_success")

    if variant_type == "cancel_block_nonpending":
        for order in orders:
            if order["status"] != "pending":
                user = world["users"][order["user_id"]]
                return {"user": user, "order": order}
        raise ValueError("No non-pending order found for cancel_block_nonpending")

    if variant_type == "cancel_block_wrong_user":
        # 找一个用户和一个不属于TA的订单
        if len(users) < 2 or len(orders) < 2:
            raise ValueError("Need at least 2 users and 2 orders for wrong_user variant")
        user = users[0]
        for order in orders:
            if order["user_id"] != user["user_id"]:
                return {"user": user, "order": order}
        raise ValueError("No order from different user found")

    if variant_type.startswith("shipping_success_"):
        target_method = variant_type.replace("shipping_success_", "")
        for order in orders:
            if order["status"] == "pending" and order.get("shipping_method") != target_method:
                user = world["users"][order["user_id"]]
                return {"user": user, "order": order, "target_method": target_method}
        raise ValueError(f"No pending order for shipping_success {target_method}")

    if variant_type == "shipping_block_same_method":
        for order in orders:
            if order["status"] == "pending":
                user = world["users"][order["user_id"]]
                return {"user": user, "order": order}
        raise ValueError("No pending order for shipping_block_same_method")

    if variant_type == "shipping_block_nonpending":
        for order in orders:
            if order["status"] != "pending":
                user = world["users"][order["user_id"]]
                return {"user": user, "order": order}
        raise ValueError("No non-pending order for shipping_block_nonpending")

    if variant_type == "shipping_block_unknown_method":
        for order in orders:
            if order["status"] == "pending":
                user = world["users"][order["user_id"]]
                return {"user": user, "order": order}
        raise ValueError("No pending order for shipping_block_unknown_method")

    if variant_type == "coupon_transfer_no_write":
        user = users[0] if users else None
        if user is None:
            raise ValueError("No users found")
        # 找一个属于该用户的订单（可选）
        user_orders = [o for o in orders if o["user_id"] == user["user_id"]]
        order = user_orders[0] if user_orders else None
        return {"user": user, "order": order}

    raise ValueError(f"Unknown variant_type: {variant_type}")
```

- [ ] **Step 3: 运行测试**

```bash
uv run python -m pytest tests/test_generalization.py -v
```

- [ ] **Step 4: Commit**

```bash
git add app/synthetic/oracle.py tests/test_generalization.py
git commit -m "feat: add select_entity_for_variant with entity selection logic"
```

---

### Task 4: ScenarioFamily 定义 + Variant 构建器

**Files:**
- Create: `app/synthetic/families.py`
- Test: `tests/test_generalization.py`

- [ ] **Step 1: 写 `FamilyVariant` 和 `ScenarioFamily` 数据类**

```python
# app/synthetic/families.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.eval.cases import EvalCase
from app.synthetic.generator import SyntheticDBGenerator
from app.synthetic.oracle import (
    DeterministicOracle,
    derive_oracle,
    select_entity_for_variant,
)


@dataclass
class FamilyVariant:
    """一个具体的测试变体定义"""
    variant_id: str
    variant_type: str
    seed: int
    capability: str
    policy_area: str
    category: str
    max_turns: int = 8

    def build_messages(self, entities: dict) -> List[Dict[str, str]]:
        """根据 variant_type 拼装对话消息"""
        user = entities["user"]
        order = entities.get("order")
        email = user["email"]
        variant_type = self.variant_type

        # --- cancel family ---
        if variant_type == "cancel_success":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. Cancel order {order['order_id']} "
                        f"because no longer needed."
                    ),
                },
                {"role": "user", "content": "yes"},
            ]
        if variant_type == "cancel_block_nonpending":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. Cancel order {order['order_id']} "
                        f"because no longer needed."
                    ),
                },
                {"role": "user", "content": "yes"},
            ]
        if variant_type == "cancel_block_wrong_user":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. Cancel order {order['order_id']} "
                        f"because ordered by mistake."
                    ),
                },
            ]

        # --- shipping family ---
        if variant_type == "shipping_success_express":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. I want to upgrade the shipping "
                        f"on my order {order['order_id']} to express."
                    ),
                },
                {"role": "user", "content": "yes"},
            ]
        if variant_type == "shipping_success_overnight":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. Change shipping on "
                        f"{order['order_id']} to overnight. Use my credit card."
                    ),
                },
                {"role": "user", "content": "yes"},
            ]
        if variant_type == "shipping_block_same_method":
            current_method = order.get("shipping_method", "standard")
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. Change shipping on "
                        f"{order['order_id']} to {current_method}."
                    ),
                },
                {"role": "user", "content": "yes"},
            ]
        if variant_type == "shipping_block_nonpending":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. Change shipping on "
                        f"{order['order_id']} to express."
                    ),
                },
                {"role": "user", "content": "yes"},
            ]
        if variant_type == "shipping_block_unknown_method":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. I need drone delivery "
                        f"for order {order['order_id']}."
                    ),
                },
                {"role": "user", "content": "confirm"},
            ]

        # --- coupon family ---
        if variant_type == "coupon_transfer_no_write":
            return [
                {
                    "role": "user",
                    "content": (
                        f"My email is {email}. Can you give me a discount "
                        f"coupon for my next order?"
                    ),
                },
            ]

        raise ValueError(f"Unknown variant_type: {variant_type}")

    def to_eval_case(self) -> EvalCase:
        """生成合成世界 + 选取实体 + 拼装对话 + 派生 oracle → EvalCase"""
        world = SyntheticDBGenerator.from_seed(self.seed)
        entities = select_entity_for_variant(world, self.variant_type)
        messages = self.build_messages(entities)
        oracle = derive_oracle(world, entities, self.variant_type)

        return EvalCase(
            case_id=self.variant_id,
            category=self.category,
            messages=messages,
            expected_user_id=oracle.expected_user_id,
            expected_intent=oracle.expected_intent,
            order_id=oracle.order_id,
            expected_write_lock=oracle.expected_write_lock,
            expected_order_status=oracle.expected_order_status,
            expected_confirmation_status=oracle.expected_confirmation_status,
            expected_guard_block_reason=oracle.expected_guard_block_reason,
            expected_no_write=oracle.expected_no_write,
            expected_tool_names=oracle.expected_tool_names,
            expected_tool_sequence=oracle.expected_tool_sequence,
            expected_db_assertions=oracle.expected_db_assertions,
            max_turns=self.max_turns,
            subset="generalization",
            capability=self.capability,
            policy_area=self.policy_area,
            seed=self.seed,
        )


@dataclass
class ScenarioFamily:
    name: str
    variants: List[FamilyVariant]


# ── 三个 Family 定义 ──

CANCEL_FAMILY = ScenarioFamily(
    name="cancel",
    variants=[
        FamilyVariant("cancel_success_s100", "cancel_success", 100,
                       "cancel_order", "order_lifecycle", "cancel"),
        FamilyVariant("cancel_success_s101", "cancel_success", 101,
                       "cancel_order", "order_lifecycle", "cancel"),
        FamilyVariant("cancel_success_s102", "cancel_success", 102,
                       "cancel_order", "order_lifecycle", "cancel"),
        FamilyVariant("cancel_block_nonpending_s103", "cancel_block_nonpending", 103,
                       "cancel_order", "order_status", "guard"),
        FamilyVariant("cancel_block_wrong_user_s104", "cancel_block_wrong_user", 104,
                       "cancel_order", "authentication", "guard"),
    ],
)

MODIFY_SHIPPING_FAMILY = ScenarioFamily(
    name="modify_shipping",
    variants=[
        FamilyVariant("shipping_express_s200", "shipping_success_express", 200,
                       "modify_shipping_method", "shipping", "modify_shipping"),
        FamilyVariant("shipping_overnight_s201", "shipping_success_overnight", 201,
                       "modify_shipping_method", "shipping", "modify_shipping"),
        FamilyVariant("shipping_block_same_s202", "shipping_block_same_method", 202,
                       "modify_shipping_method", "shipping", "modify_shipping"),
        FamilyVariant("shipping_block_nonpending_s203", "shipping_block_nonpending", 203,
                       "modify_shipping_method", "order_status", "modify_shipping"),
        FamilyVariant("shipping_block_unknown_s204", "shipping_block_unknown_method", 204,
                       "modify_shipping_method", "shipping", "modify_shipping"),
    ],
)

COUPON_REFUSAL_FAMILY = ScenarioFamily(
    name="coupon_refusal",
    variants=[
        FamilyVariant("coupon_transfer_s300", "coupon_transfer_no_write", 300,
                       "transfer", "coupon", "transfer"),
        FamilyVariant("coupon_transfer_s301", "coupon_transfer_no_write", 301,
                       "transfer", "coupon", "transfer"),
        FamilyVariant("coupon_transfer_s302", "coupon_transfer_no_write", 302,
                       "transfer", "coupon", "transfer"),
        FamilyVariant("coupon_transfer_s303", "coupon_transfer_no_write", 303,
                       "transfer", "coupon", "transfer"),
        FamilyVariant("coupon_transfer_s304", "coupon_transfer_no_write", 304,
                       "transfer", "coupon", "transfer"),
    ],
)

ALL_FAMILIES = [CANCEL_FAMILY, MODIFY_SHIPPING_FAMILY, COUPON_REFUSAL_FAMILY]


def build_generalization_cases() -> List[EvalCase]:
    """为所有 family 的所有 variant 生成 EvalCase"""
    cases: List[EvalCase] = []
    for family in ALL_FAMILIES:
        for variant in family.variants:
            cases.append(variant.to_eval_case())
    return cases
```

- [ ] **Step 2: 写端到端测试 — 验证 15 个 case 都能生成不抛异常**

```python
def test_all_15_variants_generate_without_error():
    from app.synthetic.families import ALL_FAMILIES
    for family in ALL_FAMILIES:
        for variant in family.variants:
            case = variant.to_eval_case()
            assert case.case_id == variant.variant_id
            assert case.subset == "generalization"
            assert case.expected_user_id
            assert case.expected_intent
            assert len(case.messages) >= 1


def test_cancel_family_has_5_variants():
    from app.synthetic.families import CANCEL_FAMILY
    assert len(CANCEL_FAMILY.variants) == 5


def test_all_families_total_15_variants():
    from app.synthetic.families import ALL_FAMILIES
    total = sum(len(f.variants) for f in ALL_FAMILIES)
    assert total == 15


def test_generated_case_is_reproducible():
    from app.synthetic.families import FamilyVariant
    v = FamilyVariant("test_s100", "cancel_success", 100,
                       "cancel_order", "order_lifecycle", "cancel")
    case1 = v.to_eval_case()
    case2 = v.to_eval_case()
    # 同 seed 生成相同 world → 相同 case
    assert case1.messages == case2.messages
    assert case1.expected_user_id == case2.expected_user_id
    assert case1.order_id == case2.order_id


def test_no_write_cases_have_no_write_flag():
    from app.synthetic.families import COUPON_REFUSAL_FAMILY
    for variant in COUPON_REFUSAL_FAMILY.variants:
        case = variant.to_eval_case()
        assert case.expected_no_write is True, f"{variant.variant_id} should be no-write"


def test_cancel_success_cases_expect_cancelled():
    from app.synthetic.families import CANCEL_FAMILY
    for variant in CANCEL_FAMILY.variants:
        if "success" in variant.variant_type:
            case = variant.to_eval_case()
            assert case.expected_order_status == "cancelled"
```

- [ ] **Step 3: 运行测试**

```bash
uv run python -m pytest tests/test_generalization.py -v
```

- [ ] **Step 4: Commit**

```bash
git add app/synthetic/families.py tests/test_generalization.py
git commit -m "feat: add ScenarioFamily + 3 families + build_generalization_cases"
```

---

### Task 5: EvalCase 新增 `seed` 字段，`get_cases()` 支持 generalization

**Files:**
- Modify: `app/eval/cases.py`

- [ ] **Step 1: 给 `EvalCase` 添加 `seed` 字段**

```python
# app/eval/cases.py — 在 EvalCase 数据类中新增一行:
@dataclass(frozen=True)
class EvalCase:
    # ... 已有字段 ...
    seed: Optional[int] = None  # 🆕 generalization variant 的合成世界种子
```

- [ ] **Step 2: 给 `_case_for_subset()` 添加 `seed` 传递**

```python
# app/eval/cases.py — 在 _case_for_subset 的构造函数中新增:
def _case_for_subset(case: EvalCase, subset: str) -> EvalCase:
    return EvalCase(
        # ... 已有字段 ...
        seed=case.seed,  # 🆕
    )
```

- [ ] **Step 3: 扩展 `get_cases()` 支持 generalization**

```python
# app/eval/cases.py — 在 get_cases 中新增分支:
def get_cases(subset: str) -> List[EvalCase]:
    if subset == "curated_mvp":
        return list(CURATED_MVP_CASES)
    if subset == "generalized_mvp":
        return list(GENERALIZED_MVP_CASES)
    if subset == "synthetic_seeded_v1":
        return list(SYNTHETIC_SEEDED_V1_CASES)
    if subset == "generalization":                         # 🆕
        from app.synthetic.families import build_generalization_cases  # 🆕
        return build_generalization_cases()                # 🆕
    raise ValueError("unsupported subset: " + subset)
```

- [ ] **Step 4: 验证现有用例仍然正常工作**

```bash
uv run python -c "from app.eval.cases import get_cases; assert len(get_cases('curated_mvp')) == 11"
uv run python -c "from app.eval.cases import get_cases; assert len(get_cases('generalized_mvp')) == 30"
uv run python -c "from app.eval.cases import get_cases; assert len(get_cases('synthetic_seeded_v1')) == 7"
uv run python -c "from app.eval.cases import get_cases; assert len(get_cases('generalization')) == 15"
```

- [ ] **Step 5: Commit**

```bash
git add app/eval/cases.py
git commit -m "feat: add seed field to EvalCase, support generalization subset in get_cases"
```

---

### Task 6: Runner 扩展 — 处理 generalization subset

**Files:**
- Modify: `app/eval/runner.py`

- [ ] **Step 1: 在 `_run_case()` 中处理 generalization subset 的 runtime 创建**

现在 `_run_case()` 对 `synthetic_seeded_v1` 使用 `getattr(self, "_seed", 42)` 作为全局 seed。对于 generalization，每个 case 携带自己的 `seed`，需要按 case 创建 runtime。

```python
# app/eval/runner.py — _run_case 方法中，替换 synthetic_seeded_v1 的判断逻辑:

# 替换前:
        if case.subset == "synthetic_seeded_v1":
            from app.synthetic.adapter import SyntheticRetailAdapter
            seed = getattr(self, "_seed", 42)
            synthetic_adapter = SyntheticRetailAdapter(seed=seed)
            synthetic_runtime = synthetic_adapter.create_runtime()
        else:
            synthetic_runtime = None

# 替换后:
        if case.subset in ("synthetic_seeded_v1", "generalization"):
            from app.synthetic.adapter import SyntheticRetailAdapter
            seed = getattr(case, "seed", None) or getattr(self, "_seed", 42)
            synthetic_adapter = SyntheticRetailAdapter(seed=seed)
            synthetic_runtime = synthetic_adapter.create_runtime()
        else:
            synthetic_runtime = None
```

- [ ] **Step 2: 给 `EvalCaseResult` 添加 family metadata 字段**

```python
# app/eval/runner.py — EvalCaseResult 数据类中新增:
@dataclass
class EvalCaseResult:
    # ... 已有字段 ...
    scenario_family: Optional[str] = None      # 🆕
    variant_type: Optional[str] = None         # 🆕
    seed: Optional[int] = None                 # 🆕
```

- [ ] **Step 3: 在 `_run_case()` 中传递 family metadata 到 result**

```python
# app/eval/runner.py — 在创建 EvalCaseResult 时新增:
        result = EvalCaseResult(
            # ... 已有字段 ...
            scenario_family=getattr(case, "capability", None),  # 复用 capability 作为 family tag
            variant_type=case.case_id,                           # case_id 编码了 variant 类型
            seed=getattr(case, "seed", None),                    # 🆕
        )
```

- [ ] **Step 4: Commit**

```bash
git add app/eval/runner.py
git commit -m "feat: runner handles generalization subset with per-case seed"
```

---

### Task 7: Metrics 扩展 — generalization report 聚合维度

**Files:**
- Modify: `app/eval/metrics.py`

- [ ] **Step 1: 在 `build_failure_analysis()` 中新增 family/variant_type 聚合**

```python
# app/eval/metrics.py — build_failure_analysis 函数中，在 return 之前追加:

    # 🆕 Generalization-specific aggregations
    family_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    variant_type_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    for result in result_list:
        family = getattr(result, "scenario_family", None) or "unknown"
        variant = getattr(result, "variant_type", None) or "unknown"
        family_counts[family][result.failure_label or "passed"] += 1
        variant_type_counts[variant][result.failure_label or "passed"] += 1

    # 🆕 failure_source 分类 (从 failure_label 映射)
    failure_source_map = {
        "wrong_intent": "parsing",
        "auth_failure": "parsing",
        "wrong_tool": "planning",
        "wrong_tool_sequence": "planning",
        "expected_guard_block_missing": "guard",
        "guard_blocked": "guard",
        "tool_exception": "tool_mutation",
        "unexpected_mutation": "tool_mutation",
        "mutation_missing": "tool_mutation",
        "db_state_mismatch": "tool_mutation",
        "db_assertion_mismatch": "tool_mutation",
        "confirmation_status_mismatch": "response",
        "confirmation_failure": "response",
        "response_mismatch": "response",
        "llm_json_failure": "planning",
    }
    source_counts: Counter[str] = Counter()
    for result in result_list:
        if result.failure_label:
            source = failure_source_map.get(result.failure_label, "unknown")
            source_counts[source] += 1
```

并在返回 dict 中新增：

```python
    return {
        # ... 已有字段 ...
        "family_counts": {
            family: dict(sorted(counts.items()))
            for family, counts in sorted(family_counts.items())
        },                                                          # 🆕
        "variant_type_counts": {
            variant: dict(sorted(counts.items()))
            for variant, counts in sorted(variant_type_counts.items())
        },                                                          # 🆕
        "failure_source_counts": dict(sorted(source_counts.items())),  # 🆕
    }
```

- [ ] **Step 2: Commit**

```bash
git add app/eval/metrics.py
git commit -m "feat: add generalization report aggregation by family, variant_type, failure_source"
```

---

### Task 8: EvalRunSummary 扩展 — 携带 family metadata

**Files:**
- Modify: `app/eval/runner.py`

- [ ] **Step 1: 在 `EvalRunSummary` 中新增字段**

```python
# app/eval/runner.py — EvalRunSummary 数据类:
@dataclass
class EvalRunSummary:
    # ... 已有字段 ...
    generalization_families: List[str] = field(default_factory=list)       # 🆕
    generalization_variant_count: int = 0                                  # 🆕
```

- [ ] **Step 2: 在 `run()` 方法中填充新字段**

```python
# app/eval/runner.py — run() 方法中，创建 EvalRunSummary 时新增:
        summary = EvalRunSummary(
            # ... 已有字段 ...
            generalization_families=sorted(set(
                getattr(r, "scenario_family", "") for r in results
            )) if subset == "generalization" else [],            # 🆕
            generalization_variant_count=len(results) if subset == "generalization" else 0,  # 🆕
        )
```

- [ ] **Step 3: Commit**

```bash
git add app/eval/runner.py
git commit -m "feat: add generalization metadata to EvalRunSummary"
```

---

### Task 9: 运行 generalization gate 验证

**Files:**
- (无代码变更，纯验证)

- [ ] **Step 1: 运行 generalization eval**

```bash
uv run phase2-eval --subset generalization --trials 1
```

- [ ] **Step 2: 检查结果 — 目标 15/15 pass**

- 查看 eval report `artifacts/phase2/reports/<eval_run_id>.json`
- 确认 `metrics.pass_1` = 1.0
- 确认 no-write cases（coupon family 的 5 个）DB hash 不变
- 确认 cancel_success cases（3 个）order status 变为 cancelled
- 确认 shipping_success cases（2 个）shipping_method 已修改

- [ ] **Step 3: 验证可复现性**

```bash
# 第一次运行
uv run phase2-eval --subset generalization --trials 1
# 记下 pass rate

# 第二次运行（同 seed → 同结果）
uv run phase2-eval --subset generalization --trials 1
# pass rate 应该完全一致
```

- [ ] **Step 4: Commit**（如有修复）

---

### Task 10: 回归验证 — 确保现有 subset 不受影响

**Files:**
- (无代码变更，纯验证)

- [ ] **Step 1: 运行 curated_mvp**

```bash
uv run phase2-eval --subset curated_mvp --trials 1
```

- [ ] **Step 2: 运行 generalized_mvp**

```bash
uv run phase2-eval --subset generalized_mvp --trials 1
```

- [ ] **Step 3: 运行 synthetic_seeded_v1**

```bash
uv run phase2-eval --subset synthetic_seeded_v1 --trials 1
```

- [ ] **Step 4: 确认全部通过，与基线一致**

---

### Task 11: Lint 和最终检查

- [ ] **Step 1: ruff check**

```bash
uv run ruff check .
```

- [ ] **Step 2: ruff format**

```bash
uv run ruff format --check .
```

- [ ] **Step 3: 全部单元测试**

```bash
uv run python -m pytest tests/ -v
```

- [ ] **Step 4: 最终 commit**

```bash
git add -A
git commit -m "chore: lint and final adjustments for Phase 8a generalization core"
```
