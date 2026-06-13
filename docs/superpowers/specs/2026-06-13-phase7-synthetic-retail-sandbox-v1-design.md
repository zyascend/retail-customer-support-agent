# Phase 7: Synthetic Retail Sandbox v1 — 设计文档

日期：2026-06-13
状态：设计中（待用户审阅）

## 1. 目标

证明 Agent 不是记住固定 tau retail cases，而是能处理一个新生成的零售世界：新用户、新订单、新商品、新支付方式，以及新增交易能力（配送方式修改）。

## 2. 架构决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Synthetic 模块位置 | `app/synthetic/` 独立包 | 容纳 generator、adapter、tools，Phase 8a 加 scenario family 时有空间 |
| Eval 集成 | 复用 `phase2-eval --subset synthetic_seeded_v1` | 不改 EvalCase 模型，eval runner 做最小适配 |
| Adapter 关系 | 独立实现，不继承 `LocalRetailTools` | 干净隔离，synthetic 世界有独立数据结构（shipping_method 等），独立演进 |

## 3. Synthetic 世界 Schema

```json
{
  "users": {
    "U1": {
      "user_id": "U1",
      "name": {"first_name": "Alice", "last_name": "Wang"},
      "email": "alice.wang@example.com",
      "address": {"address1": "...", "city": "...", "state": "...", "country": "US", "zip": "02108"},
      "payment_methods": {
        "credit_card_001": {"source": "credit_card", "brand": "Visa", "last_four": "1234"},
        "gift_card_001": {"source": "gift_card", "balance": 15.0}
      }
    }
  },
  "orders": {
    "#W1001": {
      "order_id": "#W1001",
      "user_id": "U1",
      "status": "pending",
      "items": [
        {"item_id": "10000001", "product_id": "P1", "name": "Ergonomic Chair", "price": 199.99, "options": {}}
      ],
      "address": {...},
      "payment_history": [
        {"transaction_type": "payment", "amount": 199.99, "payment_method_id": "credit_card_001"}
      ],
      "shipping_method": "standard",
      "shipping_fee": 0.0
    }
  },
  "products": {
    "P1": {
      "product_id": "P1",
      "name": "Ergonomic Chair",
      "variants": {
        "10000001": {"item_id": "10000001", "name": "Black", "price": 199.99, "available": true, "options": {}},
        "10000002": {"item_id": "10000002", "name": "White", "price": 199.99, "available": true}
      }
    }
  },
  "shipping_methods": {
    "standard":  {"name": "Standard",  "fee": 0.0},
    "express":   {"name": "Express",   "fee": 9.99},
    "overnight": {"name": "Overnight", "fee": 24.99}
  }
}
```

- 完全兼容 `get_order_from_db()`、`get_user_from_db()` 的函数签名
- 新增 `shipping_method` / `shipping_fee` 只在 synthetic orders 上有
- seed 决定一切，同 seed 同 world
- v1 规模：10 users, 50 orders, 30 products (90 variants), 每人 2-4 payment methods

## 4. 模块结构

```
app/synthetic/
├── __init__.py
├── generator.py    # SyntheticDBGenerator — seed → world dict
└── adapter.py      # SyntheticRetailAdapter + SyntheticRetailTools
```

## 5. World Generator (`generator.py`)

```python
class SyntheticDBGenerator:
    def __init__(self, seed: int = 42): ...
    def generate(self) -> dict: ...
    def to_file(self, path: Path) -> None: ...

    @classmethod
    def from_seed(cls, seed: int) -> dict: ...
```

- 使用 Python `random` 模块 + 固定 seed，100% 可复现
- 生成纯 dict，不依赖 tau2/外部数据源
- `to_file()` 写入 `artifacts/phase7/synthetic_worlds/<seed>.json`

## 6. SyntheticRetailAdapter + SyntheticRetailTools (`adapter.py`)

### SyntheticRetailTools

实现和 `LocalRetailTools` 完全平行的接口：`.tools` dict、`.tool_type()`、`.get_hash()`。

**Read tools（8 个，和 tau retail 一致）**：
`find_user_id_by_email`、`find_user_id_by_name_zip`、`get_user_details`、`get_order_details`、`get_product_details`、`get_item_details`、`list_all_product_types`

**Write tools（7 个已有 + 1 个新增）**：
已有的 `cancel_pending_order`、`modify_pending_order_address`、`modify_pending_order_items`、`modify_pending_order_payment`、`return_delivered_order_items`、`exchange_delivered_order_items`、`modify_user_address`，及新增的 `modify_pending_order_shipping_method`。

**Generic**：`calculate`、`transfer_to_human_agents`

### 新写操作：modify_pending_order_shipping_method

```python
def modify_pending_order_shipping_method(
    self, order_id: str, shipping_method: str, payment_method_id: str | None = None
) -> dict:
    order = self._get_order(order_id)
    assert order["status"] == "pending"
    old_fee = self.db["shipping_methods"][order["shipping_method"]]["fee"]
    new_fee = self.db["shipping_methods"][shipping_method]["fee"]
    fee_delta = new_fee - old_fee
    order["shipping_method"] = shipping_method
    order["shipping_fee"] = new_fee
    if fee_delta > 0 and payment_method_id:
        order["payment_history"].append({
            "transaction_type": "shipping_upgrade",
            "amount": round(fee_delta, 2),
            "payment_method_id": payment_method_id,
        })
    return copy.deepcopy(order)
```

### SyntheticRetailAdapter

```python
class SyntheticRetailAdapter:
    def __init__(self, seed: int = 42):
        self.seed = seed

    def create_runtime(self) -> RetailRuntime:
        db = SyntheticDBGenerator.from_seed(self.seed)
        tools = SyntheticRetailTools(db)
        return RetailRuntime(db=tools.db, tools=tools, policy="synthetic-policy", source="synthetic")
```

复用现有 `RetailRuntime` dataclass，`ToolGateway` / `ToolRegistry` 完全不感知差异。

## 7. action_specs 扩展

在 `WRITE_ACTION_REGISTRY` 中新增：

```python
WriteActionSpec(
    name="modify_pending_order_shipping_method",
    display="Modify Shipping Method",
    tool_name="modify_pending_order_shipping_method",
    intent="modify_shipping_method",
    required_args=("order_id", "shipping_method"),
    required_slots=("order_id", "shipping_method"),
    order_status_check="pending",
    resource_type="order",
    risk="medium",
),
```

在 `tool_constraints_for_llm()` 中添加约束描述。

自动派生到 `WRITE_ACTION_NAMES`、`WRITE_TOOL_NAMES`、`WRITE_INTENTS` → guard Layer 0 自动放行。

## 8. Write Guard 扩展 (`guard.py`)

### `_validate_policy()` 新增分支

```python
if action.tool_name == "modify_pending_order_shipping_method":
    return self._validate_shipping_method_change(db, order, args)
```

### `_validate_shipping_method_change()` 新方法

校验顺序：
1. 订单状态 = `pending` → 否则 `non_pending_order_cannot_be_modified`（复用已有）
2. 新配送方式 ≠ 当前 → 否则 `same_shipping_method`
3. 新配送方式在 `shipping_methods` 中存在 → 否则 `unknown_shipping_method`
4. 如果是收费升级（fee_delta > 0）：
   - 必须提供 `payment_method_id` → `payment_method_required_for_upgrade`
   - payment method 必须归用户所有 → 复用已有 `payment_method_not_owned`
   - 如果是 gift card，余额 ≥ fee_delta → 复用已有 `gift_card_balance_insufficient`

### `_resource_lock()` 新增

```python
if action.tool_name == "modify_pending_order_shipping_method":
    return f"order:{args.get('order_id')}:modify_shipping_method"
```

### `_summary()` 新增对应分支

### 新增 block reason

| Block Reason | 触发条件 |
|-------------|---------|
| `non_pending_order_cannot_be_modified` | 订单非 pending（复用已有） |
| `same_shipping_method` | 新配送方式 = 当期 |
| `unknown_shipping_method` | 不在 shipping_methods 中 |
| `payment_method_required_for_upgrade` | 收费升级但未提供 payment |
| `payment_method_not_owned` | 复用已有 |
| `gift_card_balance_insufficient` | 复用已有，对 fee_delta 检查 |

## 9. Parser 扩展 (`parsers.py`)

### 新增 intent

`SUPPORTED_INTENTS` 中新增 `"modify_shipping_method"`。

### 意图识别（`infer_intent()`）

```python
# Coupon / discount / compensation → transfer（最先判断）
if re.search(r"\b(coupon|discount|compensation|refund|money back)\b", lowered):
    if not re.search(r"\breturn\b", lowered) or "money" in lowered:
        return "transfer"

# Shipping method modification
if "shipping" in lowered and re.search(r"\b(change|modify|update|upgrade|switch)\b", lowered):
    return "modify_shipping_method"
if re.search(r"\b(upgrade|expedite)\b.*\bshipping\b", lowered):
    return "modify_shipping_method"
if re.search(r"\b(overnight|express|standard)\b.*\bshipping\b", lowered):
    return "modify_shipping_method"
```

### 配送方式槽位提取 (`parse_shipping_method()`)

```python
SHIPPING_ALIASES = {
    "standard": "standard", "regular": "standard", "normal": "standard", "free": "standard",
    "express": "express", "expedited": "express",
    "overnight": "overnight", "next day": "overnight", "next-day": "overnight",
}
```

## 10. Eval Cases

在 `app/eval/cases.py` 中新增 `SYNTHETIC_SEEDED_V1`，subset = `"synthetic_seeded_v1"`。

| case_id | 场景 | 预期结果 |
|---------|------|---------|
| `synthetic_shipping_express_success` | standard → express，用 credit card 付 9.99 | allow, order.shipping_method=express, payment_history 追加 shipping_upgrade |
| `synthetic_shipping_overnight_gift_card_insufficient` | standard → overnight (24.99)，gift card 余额 15.00 | guard block: `gift_card_balance_insufficient` |
| `synthetic_shipping_processed_order_block` | 对 status=processing 的订单改配送 | guard block: `non_pending_order_cannot_be_modified` |
| `synthetic_shipping_same_method_block` | express → express | guard block: `same_shipping_method` |
| `synthetic_shipping_unknown_method_block` | 要求 "drone delivery"（无效） | guard block: `unknown_shipping_method` |
| `synthetic_coupon_refusal_no_write` | 用户要求折扣券 | policy_decision=transfer, no DB mutation |
| `synthetic_compensation_then_shipping_success` | 用户先要求补偿（transfer），再要求改配送（success） | 多轮 resilience：第一轮 transfer 无 mutation，第二轮 shipping allow + mutation |

## 11. Eval Runner 适配

在 `runner.py` 中，当 subset 为 `synthetic_seeded_v1` 时：
- 读取 `--seed`（默认 42）
- 调用 `SyntheticDBGenerator.from_seed(seed)` 生成 DB
- 创建 `SyntheticRetailTools(db)` → `RetailRuntime`
- 传入 `AgentRuntime`

改动量约 10-15 行。

### CLI

```bash
uv run phase2-eval --subset synthetic_seeded_v1 --seed 42 --trials 1
```

## 12. Workbench 最小入口

在 Workbench 中加一个 fixed-seed synthetic scenario 展示（1 个 case），证明 synthetic world 可以在 Workbench 中运行。改动量最小（加一个 demo case 配置）。

## 13. 验收标准

- [ ] 固定 seed 能生成同样的 synthetic DB 和 scenario 定义
- [ ] synthetic eval v1 全部通过（7 case）
- [ ] coupon / compensation case DB hash 不变（no-write invariant）
- [ ] shipping method success case 只在 confirmation 后才写 DB
- [ ] shipping method block cases 给出稳定 guard reason
- [ ] 现有 `curated_mvp`（11 case）和 `generalized_mvp`（30 case）仍然通过
- [ ] 单元测试覆盖新增 guard block reason
- [ ] `uv run ruff check .` 通过
- [ ] `uv run ruff format --check .` 通过

## 14. 待实现任务

1. 创建 `app/synthetic/` 包（`__init__.py`, `generator.py`, `adapter.py`）
2. 实现 `SyntheticDBGenerator`（seed → world dict）
3. 实现 `SyntheticRetailTools`（read + write + generic tools）
4. 实现 `SyntheticRetailAdapter.create_runtime()`
5. 在 `action_specs.py` 中新增 `modify_pending_order_shipping_method`
6. 在 `guard.py` 中新增 `_validate_shipping_method_change()` 及相关分支
7. 在 `parsers.py` 中新增 shipping intent 识别 + 槽位提取 + coupon/compensation → transfer
8. 在 `cases.py` 中新增 `SYNTHETIC_SEEDED_V1`（7 个 EvalCase）
9. 适配 eval runner 支持 synthetic subset
10. 新增 guard 单元测试（覆盖 shipping method block reason）
11. 新增 synthetic eval 验证
12. Workbench 最小展示入口（1 个 fixed-seed case）
