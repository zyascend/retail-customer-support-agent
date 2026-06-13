# Phase 7: Synthetic Retail Sandbox v1 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 seeded synthetic retail world generator + 新增配送方式修改写操作 + 7 个 synthetic eval case，证明 Agent 的确定性格局能泛化到新世界。

**Architecture:** `app/synthetic/` 独立包（generator.py + adapter.py），复用现有 `RetailRuntime` / `ToolRegistry` / `ToolGateway` / `EvalCase`，仅在 `AgentRuntime.__init__` 增加一个可选的 `runtime` 注入参数。

**Tech Stack:** Python 3.12+, dataclasses, random (seeded), pytest, 现有 AgentRuntime + eval runner

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `app/synthetic/__init__.py` | 包初始化 |
| 新建 | `app/synthetic/generator.py` | Seed → synthetic world dict |
| 新建 | `app/synthetic/adapter.py` | SyntheticRetailTools + SyntheticRetailAdapter |
| 新建 | `tests/test_synthetic.py` | Generator + adapter + guard 合成测试 |
| 修改 | `app/agent/action_specs.py` | 新增 WriteActionSpec |
| 修改 | `app/agent/guard.py` | `_validate_shipping_method_change` + lock + summary |
| 修改 | `app/agent/parsers.py` | shipping intent + slots + coupon→transfer |
| 修改 | `app/agent/runtime.py` | `GUARD_USER_MESSAGES` + `AgentRuntime.runtime` 参数 |
| 修改 | `app/eval/cases.py` | `SYNTHETIC_SEEDED_V1` 7 个 case |
| 修改 | `app/eval/runner.py` | synthetic subset 适配 |
| 修改 | `pyproject.toml` | 新增 `phase7-synthetic-eval` script（可选） |

---

### Task 1: 创建 `app/synthetic/` 包骨架

**Files:**
- Create: `app/synthetic/__init__.py`

- [ ] **Step 1: 创建空的 `__init__.py`**

```python
# app/synthetic/__init__.py
from app.synthetic.generator import SyntheticDBGenerator
from app.synthetic.adapter import SyntheticRetailAdapter, SyntheticRetailTools

__all__ = ["SyntheticDBGenerator", "SyntheticRetailAdapter", "SyntheticRetailTools"]
```

- [ ] **Step 2: 验证导入不报错（ignore 因为其他文件还不存在，先 commit 占位）**

Run: `uv run python -c "import app.synthetic"`（预期会因 generator.py 不存在而报错 — 这是 Task 2 的事）

- [ ] **Step 3: Commit**

```bash
git add app/synthetic/__init__.py
git commit -m "feat: 创建 app/synthetic 包骨架"
```

---

### Task 2: 实现 SyntheticDBGenerator（TDD）

**Files:**
- Create: `app/synthetic/generator.py`
- Create: `tests/test_synthetic.py`（本 task 只写 generator 测试）

- [ ] **Step 1: 写生成器测试**

```python
# tests/test_synthetic.py
import json
import unittest

from app.synthetic.generator import SyntheticDBGenerator


class SyntheticDBGeneratorTests(unittest.TestCase):
    def test_same_seed_produces_same_world(self):
        g1 = SyntheticDBGenerator(seed=42)
        g2 = SyntheticDBGenerator(seed=42)
        world1 = g1.generate()
        world2 = g2.generate()
        self.assertEqual(world1, world2)

    def test_different_seeds_produce_different_worlds(self):
        g1 = SyntheticDBGenerator(seed=42)
        g2 = SyntheticDBGenerator(seed=99)
        world1 = g1.generate()
        world2 = g2.generate()
        self.assertNotEqual(world1, world2)

    def test_world_has_required_top_level_keys(self):
        g = SyntheticDBGenerator(seed=42)
        world = g.generate()
        for key in ("users", "orders", "products", "shipping_methods"):
            self.assertIn(key, world)

    def test_user_count_is_10(self):
        world = SyntheticDBGenerator(seed=42).generate()
        self.assertEqual(len(world["users"]), 10)

    def test_order_count_is_50(self):
        world = SyntheticDBGenerator(seed=42).generate()
        self.assertEqual(len(world["orders"]), 50)

    def test_product_count_is_30(self):
        world = SyntheticDBGenerator(seed=42).generate()
        self.assertEqual(len(world["products"]), 30)

    def test_each_product_has_3_variants(self):
        world = SyntheticDBGenerator(seed=42).generate()
        for product in world["products"].values():
            self.assertEqual(len(product["variants"]), 3)

    def test_shipping_methods_are_fixed_three(self):
        world = SyntheticDBGenerator(seed=42).generate()
        methods = world["shipping_methods"]
        self.assertEqual(len(methods), 3)
        for key in ("standard", "express", "overnight"):
            self.assertIn(key, methods)

    def test_standard_is_free(self):
        world = SyntheticDBGenerator(seed=42).generate()
        self.assertEqual(world["shipping_methods"]["standard"]["fee"], 0.0)

    def test_express_fee_is_9_99(self):
        world = SyntheticDBGenerator(seed=42).generate()
        self.assertEqual(world["shipping_methods"]["express"]["fee"], 9.99)

    def test_overnight_fee_is_24_99(self):
        world = SyntheticDBGenerator(seed=42).generate()
        self.assertEqual(world["shipping_methods"]["overnight"]["fee"], 24.99)

    def test_each_user_has_payment_methods(self):
        world = SyntheticDBGenerator(seed=42).generate()
        for user in world["users"].values():
            self.assertGreaterEqual(len(user["payment_methods"]), 1)
            self.assertLessEqual(len(user["payment_methods"]), 4)

    def test_each_user_has_name_email_address(self):
        world = SyntheticDBGenerator(seed=42).generate()
        for user in world["users"].values():
            self.assertIn("name", user)
            self.assertIn("first_name", user["name"])
            self.assertIn("email", user)
            self.assertIn("address", user)

    def test_each_order_has_shipping_fields(self):
        world = SyntheticDBGenerator(seed=42).generate()
        for order in world["orders"].values():
            self.assertIn("shipping_method", order)
            self.assertIn("shipping_fee", order)

    def test_order_user_ids_are_valid(self):
        world = SyntheticDBGenerator(seed=42).generate()
        user_ids = set(world["users"].keys())
        for order in world["orders"].values():
            self.assertIn(order["user_id"], user_ids)

    def test_order_status_distribution_is_reasonable(self):
        world = SyntheticDBGenerator(seed=42).generate()
        statuses = [o["status"] for o in world["orders"].values()]
        pending_count = sum(1 for s in statuses if s == "pending")
        self.assertGreater(pending_count, 20)  # at least ~60% pending

    def test_from_seed_classmethod(self):
        world = SyntheticDBGenerator.from_seed(42)
        self.assertIn("users", world)

    def test_to_file_writes_valid_json(self):
        import tempfile
        import os
        g = SyntheticDBGenerator(seed=42)
        world = g.generate()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "world.json")
            g.to_file(path)
            with open(path) as f:
                loaded = json.load(f)
            self.assertEqual(world, loaded)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python -m pytest tests/test_synthetic.py -v`
Expected: 全部 FAIL（`SyntheticDBGenerator` 未定义）

- [ ] **Step 3: 实现 `SyntheticDBGenerator`**

```python
# app/synthetic/generator.py
from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any, Dict


FIRST_NAMES = [
    "Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Heidi",
    "Ivan", "Judy", "Kevin", "Linda", "Mallory", "Nancy", "Oscar",
    "Peggy", "Quinn", "Ruth", "Steve", "Trudy",
]
LAST_NAMES = [
    "Wang", "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
    "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez",
    "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson",
]
CITIES = [
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix",
    "Philadelphia", "San Antonio", "San Diego", "Dallas", "Austin",
]
STATES = [
    "NY", "CA", "IL", "TX", "AZ", "PA", "TX", "CA", "TX", "TX",
]
PRODUCT_NAMES = [
    "Ergonomic Chair", "Standing Desk", "Monitor Arm", "Keyboard Tray",
    "Desk Lamp", "Filing Cabinet", "Bookshelf", "Office Mat",
    "Headset", "Webcam", "Mouse Pad", "Laptop Stand",
    "Cable Organizer", "Whiteboard", "Plant Pot", "Water Bottle",
    "Notebook", "Pen Set", "Sticky Notes", "Paper Shredder",
    "Desk Fan", "USB Hub", "External Drive", "Mouse",
    "Keyboard", "Monitor", "Speaker", "Charger",
    "Backpack", "Lunch Box",
]
VARIANT_OPTIONS_LIST = [
    [{"color": "Black"}, {"color": "White"}, {"color": "Gray"}],
    [{"size": "Small"}, {"size": "Medium"}, {"size": "Large"}],
    [{"material": "Plastic"}, {"material": "Metal"}, {"material": "Wood"}],
    [{"style": "Basic"}, {"style": "Premium"}, {"style": "Deluxe"}],
    [{"color": "Red"}, {"color": "Blue"}, {"color": "Green"}],
]

SHIPPING_METHODS = {
    "standard": {"name": "Standard", "fee": 0.0},
    "express": {"name": "Express", "fee": 9.99},
    "overnight": {"name": "Overnight", "fee": 24.99},
}

PAYMENT_SOURCES = ["credit_card", "gift_card", "paypal"]


class SyntheticDBGenerator:
    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self._rng = random.Random(seed)

    @classmethod
    def from_seed(cls, seed: int) -> dict:
        return cls(seed).generate()

    def to_file(self, path: Path) -> None:
        world = self.generate()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(world, indent=2, ensure_ascii=False))

    def generate(self) -> dict:
        self._rng = random.Random(self.seed)

        products = self._generate_products()
        users = self._generate_users()
        orders = self._generate_orders(users, products)

        return {
            "users": users,
            "orders": orders,
            "products": products,
            "shipping_methods": copy.deepcopy(SHIPPING_METHODS),
        }

    def _generate_products(self) -> dict:
        products: dict = {}
        for i in range(30):
            pid = f"P{i}"
            name = PRODUCT_NAMES[i % len(PRODUCT_NAMES)]
            options_pool = VARIANT_OPTIONS_LIST[i % len(VARIANT_OPTIONS_LIST)]
            variants: dict = {}
            for vi in range(3):
                item_id = f"{10000000 + i * 10 + vi}"
                price = round(self._rng.uniform(5.0, 300.0), 2)
                variants[item_id] = {
                    "item_id": item_id,
                    "name": f"{name} {options_pool[vi]}",
                    "price": price,
                    "available": self._rng.random() > 0.1,  # 90% available
                    "options": dict(options_pool[vi]),
                }
            products[pid] = {
                "product_id": pid,
                "name": name,
                "variants": variants,
            }
        return products

    def _generate_users(self) -> dict:
        users: dict = {}
        for i in range(10):
            uid = f"U{i}"
            first = self._rng.choice(FIRST_NAMES)
            last = self._rng.choice(LAST_NAMES)
            city_idx = i % len(CITIES)
            users[uid] = {
                "user_id": uid,
                "name": {"first_name": first, "last_name": last},
                "email": f"{first.lower()}.{last.lower()}{i}@example.com",
                "address": {
                    "address1": f"{self._rng.randint(1, 999)} Main St",
                    "address2": f"Apt {self._rng.randint(1, 50)}",
                    "city": CITIES[city_idx],
                    "state": STATES[city_idx],
                    "country": "US",
                    "zip": f"{self._rng.randint(10000, 99999)}",
                },
                "payment_methods": self._generate_payment_methods(uid, i),
            }
        return users

    def _generate_payment_methods(self, uid: str, idx: int) -> dict:
        methods: dict = {}
        count = self._rng.randint(2, 4)
        for j in range(count):
            source = PAYMENT_SOURCES[j % len(PAYMENT_SOURCES)]
            pmid = f"{source}_{uid}_{j}"
            if source == "credit_card":
                methods[pmid] = {
                    "source": "credit_card",
                    "brand": self._rng.choice(["Visa", "Mastercard", "Amex"]),
                    "last_four": f"{self._rng.randint(1000, 9999)}",
                }
            elif source == "gift_card":
                methods[pmid] = {
                    "source": "gift_card",
                    "balance": round(self._rng.uniform(5.0, 100.0), 2),
                }
            else:  # paypal
                methods[pmid] = {
                    "source": "paypal",
                    "email": f"paypal_{uid}_{j}@example.com",
                }
        return methods

    def _generate_orders(self, users: dict, products: dict) -> dict:
        orders: dict = {}
        user_ids = list(users.keys())
        product_ids = list(products.keys())
        shipping_keys = list(SHIPPING_METHODS.keys())
        statuses = ["pending"] * 30 + ["delivered"] * 10 + ["processing"] * 5 + ["cancelled"] * 5
        self._rng.shuffle(statuses)
        for i in range(50):
            oid = f"#W{1000 + i}"
            uid = self._rng.choice(user_ids)
            user = users[uid]
            # Pick 1-3 items from 1-2 products
            item_count = self._rng.randint(1, 3)
            selected_products = self._rng.sample(product_ids, min(item_count, len(product_ids)))
            items = []
            amount = 0.0
            for pid in selected_products:
                variants = products[pid]["variants"]
                variant = self._rng.choice(list(variants.values()))
                qty = 1
                items.append({
                    "item_id": variant["item_id"],
                    "product_id": pid,
                    "name": variant["name"],
                    "price": variant["price"],
                    "options": copy.deepcopy(variant["options"]),
                })
                amount += variant["price"] * qty
            # Pick a payment method for initial payment
            payment_method_ids = list(user["payment_methods"].keys())
            payment_method_id = self._rng.choice(payment_method_ids)
            shipping = self._rng.choice(shipping_keys)
            shipping_fee = SHIPPING_METHODS[shipping]["fee"]
            orders[oid] = {
                "order_id": oid,
                "user_id": uid,
                "status": statuses[i],
                "items": items,
                "address": copy.deepcopy(user["address"]),
                "payment_history": [
                    {
                        "transaction_type": "payment",
                        "amount": round(amount, 2),
                        "payment_method_id": payment_method_id,
                    }
                ],
                "shipping_method": shipping,
                "shipping_fee": shipping_fee,
            }
        return orders
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run python -m pytest tests/test_synthetic.py::SyntheticDBGeneratorTests -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add app/synthetic/generator.py tests/test_synthetic.py
git commit -m "feat: 实现 SyntheticDBGenerator — seed-based synthetic world 生成"
```

---

### Task 3: 实现 SyntheticRetailTools + SyntheticRetailAdapter（TDD）

**Files:**
- Create: `app/synthetic/adapter.py`
- Modify: `tests/test_synthetic.py`（追加 adapter 测试类）

- [ ] **Step 1: 写 adapter 测试**

在 `tests/test_synthetic.py` 末尾追加：

```python
class SyntheticRetailAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.synthetic.generator import SyntheticDBGenerator
        cls.world = SyntheticDBGenerator(seed=42).generate()
        from app.synthetic.adapter import SyntheticRetailTools
        cls.tools = SyntheticRetailTools(cls.world)
        from app.synthetic.adapter import SyntheticRetailAdapter
        cls.adapter = SyntheticRetailAdapter(seed=42)

    def test_tools_dict_has_read_tools(self):
        for name in ("find_user_id_by_email", "find_user_id_by_name_zip",
                     "get_user_details", "get_order_details",
                     "get_product_details", "get_item_details",
                     "list_all_product_types"):
            self.assertIn(name, self.tools.tools)

    def test_tools_dict_has_write_tools(self):
        for name in ("cancel_pending_order", "modify_pending_order_address",
                     "modify_pending_order_items", "modify_pending_order_payment",
                     "return_delivered_order_items", "exchange_delivered_order_items",
                     "modify_user_address", "modify_pending_order_shipping_method"):
            self.assertIn(name, self.tools.tools)

    def test_tools_dict_has_generic_tools(self):
        for name in ("calculate", "transfer_to_human_agents"):
            self.assertIn(name, self.tools.tools)

    def test_tool_type_classifies_read(self):
        self.assertEqual(self.tools.tool_type("find_user_id_by_email"), "read")
        self.assertEqual(self.tools.tool_type("get_order_details"), "read")

    def test_tool_type_classifies_write(self):
        self.assertEqual(self.tools.tool_type("cancel_pending_order"), "write")
        self.assertEqual(self.tools.tool_type("modify_pending_order_shipping_method"), "write")

    def test_tool_type_classifies_generic(self):
        self.assertEqual(self.tools.tool_type("calculate"), "generic")
        self.assertEqual(self.tools.tool_type("transfer_to_human_agents"), "generic")

    def test_get_hash_is_stable(self):
        h1 = self.tools.get_hash()
        h2 = self.tools.get_hash()
        self.assertEqual(h1, h2)

    def test_find_user_by_email_works(self):
        first_user = next(iter(self.world["users"].values()))
        email = first_user["email"]
        uid = self.tools.find_user_id_by_email(email)
        self.assertEqual(uid, first_user["user_id"])

    def test_get_order_details_works(self):
        first_order = next(iter(self.world["orders"].values()))
        oid = first_order["order_id"]
        order = self.tools.get_order_details(oid)
        self.assertEqual(order["order_id"], oid)

    def test_shipping_method_mutation_happy_path(self):
        # Find a pending order with standard shipping
        pending_orders = [
            o for o in self.world["orders"].values()
            if o["status"] == "pending" and o["shipping_method"] == "standard"
        ]
        if not pending_orders:
            self.skipTest("no pending standard-shipping order in seed 42")
        order = pending_orders[0]
        result = self.tools.modify_pending_order_shipping_method(
            order["order_id"], "express", payment_method_id=None
        )
        self.assertEqual(result["shipping_method"], "express")
        self.assertEqual(result["shipping_fee"], 9.99)

    def test_shipping_method_mutation_with_payment_upgrade(self):
        # Find a pending standard order whose user has a credit card
        pending_orders = [
            o for o in self.world["orders"].values()
            if o["status"] == "pending" and o["shipping_method"] == "standard"
        ]
        if not pending_orders:
            self.skipTest("no pending order in seed 42")
        order = pending_orders[0]
        user = self.world["users"][order["user_id"]]
        cc_id = next(
            (k for k, v in user["payment_methods"].items()
             if v.get("source") == "credit_card"),
            list(user["payment_methods"].keys())[0],
        )
        result = self.tools.modify_pending_order_shipping_method(
            order["order_id"], "overnight", payment_method_id=cc_id
        )
        self.assertEqual(result["shipping_method"], "overnight")
        self.assertEqual(result["shipping_fee"], 24.99)
        # Check that a shipping_upgrade transaction was appended
        last_txn = result["payment_history"][-1]
        self.assertEqual(last_txn["transaction_type"], "shipping_upgrade")
        self.assertEqual(last_txn["payment_method_id"], cc_id)

    def test_adapter_create_runtime_returns_retail_runtime(self):
        from app.tools.retail_adapter import RetailRuntime
        runtime = self.adapter.create_runtime()
        self.assertIsInstance(runtime, RetailRuntime)
        self.assertEqual(runtime.source, "synthetic")

    def test_adapter_runtime_db_has_correct_tables(self):
        runtime = self.adapter.create_runtime()
        db = runtime.tools.db
        for key in ("users", "orders", "products", "shipping_methods"):
            self.assertIn(key, db)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python -m pytest tests/test_synthetic.py::SyntheticRetailAdapterTests -v`
Expected: 全部 FAIL（`SyntheticRetailTools` 未定义）

- [ ] **Step 3: 实现 `SyntheticRetailTools` + `SyntheticRetailAdapter`**

```python
# app/synthetic/adapter.py
from __future__ import annotations

import copy
import json
from typing import Any, Callable, Dict

from app.synthetic.generator import SyntheticDBGenerator
from app.tools.retail_adapter import RetailRuntime

READ_TOOLS = {
    "find_user_id_by_email",
    "find_user_id_by_name_zip",
    "get_user_details",
    "get_order_details",
    "get_product_details",
    "get_item_details",
    "list_all_product_types",
}
WRITE_TOOLS = {
    "cancel_pending_order",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
    "exchange_delivered_order_items",
    "modify_pending_order_shipping_method",
}
GENERIC_TOOLS = {"calculate", "transfer_to_human_agents"}


class SyntheticRetailTools:
    def __init__(self, db: Dict[str, Any]) -> None:
        self.db = db
        self.tools: Dict[str, Callable[..., Any]] = {
            name: getattr(self, name)
            for name in sorted(READ_TOOLS | WRITE_TOOLS | GENERIC_TOOLS)
            if hasattr(self, name)
        }

    def tool_type(self, tool_name: str) -> str:
        if tool_name in READ_TOOLS:
            return "read"
        if tool_name in WRITE_TOOLS:
            return "write"
        return "generic"

    def get_hash(self) -> str:
        from app.ops.serialization import stable_hash
        return stable_hash(self.db)

    # ── Private helpers ──

    def _get_order(self, order_id: str) -> Dict[str, Any]:
        try:
            return self.db["orders"][order_id]
        except KeyError as exc:
            raise ValueError("Order not found") from exc

    def _get_user(self, user_id: str) -> Dict[str, Any]:
        try:
            return self.db["users"][user_id]
        except KeyError as exc:
            raise ValueError("User not found") from exc

    def _get_product(self, product_id: str) -> Dict[str, Any]:
        try:
            return self.db["products"][product_id]
        except KeyError as exc:
            raise ValueError("Product not found") from exc

    def _get_variant(self, product_id: str, item_id: str) -> Dict[str, Any]:
        product = self._get_product(product_id)
        try:
            return product["variants"][item_id]
        except KeyError as exc:
            raise ValueError("Variant not found") from exc

    def _get_payment_method(
        self, user_id: str, payment_method_id: str
    ) -> Dict[str, Any]:
        user = self._get_user(user_id)
        try:
            return user["payment_methods"][payment_method_id]
        except KeyError as exc:
            raise ValueError("Payment method not found") from exc

    def _get_current_payment_method_id(self, order: Dict[str, Any]) -> str | None:
        for entry in reversed(order.get("payment_history", [])):
            if entry.get("transaction_type") == "payment":
                return entry.get("payment_method_id")
        return None

    # ── Read tools ──

    def calculate(self, expression: str) -> str:
        if not all(char in "0123456789+-*/(). " for char in expression):
            raise ValueError("Invalid characters in expression")
        return str(round(float(eval(expression, {"__builtins__": None}, {})), 2))

    def find_user_id_by_email(self, email: str) -> str:
        for user_id, user in self.db["users"].items():
            if user["email"].lower() == email.lower():
                return user_id
        raise ValueError("User not found")

    def find_user_id_by_name_zip(
        self, first_name: str, last_name: str, zip: str
    ) -> str:
        for user_id, user in self.db["users"].items():
            name = user["name"]
            if (
                name["first_name"].lower() == first_name.lower()
                and name["last_name"].lower() == last_name.lower()
                and user["address"]["zip"] == zip
            ):
                return user_id
        raise ValueError("User not found")

    def get_user_details(self, user_id: str) -> Dict[str, Any]:
        return copy.deepcopy(self._get_user(user_id))

    def get_order_details(self, order_id: str) -> Dict[str, Any]:
        return copy.deepcopy(self._get_order(order_id))

    def get_product_details(self, product_id: str) -> Dict[str, Any]:
        return copy.deepcopy(self._get_product(product_id))

    def get_item_details(self, item_id: str) -> Dict[str, Any]:
        for product in self.db["products"].values():
            if item_id in product["variants"]:
                return copy.deepcopy(product["variants"][item_id])
        raise ValueError("Item not found")

    def list_all_product_types(self) -> str:
        product_dict = {
            product["name"]: product_id
            for product_id, product in self.db["products"].items()
        }
        return json.dumps(product_dict, sort_keys=True)

    # ── Write tools (existing) ──

    def cancel_pending_order(self, order_id: str, reason: str) -> Dict[str, Any]:
        order = self._get_order(order_id)
        assert order["status"] == "pending"
        assert reason in {"no longer needed", "ordered by mistake"}
        order["status"] = "cancelled"
        order["cancel_reason"] = reason
        return copy.deepcopy(order)

    def modify_pending_order_address(
        self, order_id: str, address1: str, address2: str,
        city: str, state: str, country: str, zip: str,
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        assert "pending" in order["status"]
        order["address"] = {
            "address1": address1, "address2": address2,
            "city": city, "state": state, "country": country, "zip": zip,
        }
        return copy.deepcopy(order)

    def modify_pending_order_items(
        self, order_id: str, item_ids: list[str], new_item_ids: list[str],
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        assert order["status"] == "pending"
        assert len(item_ids) == len(new_item_ids)
        for old_item_id, new_item_id in zip(item_ids, new_item_ids):
            matching_index = next(
                (idx for idx, item in enumerate(order["items"])
                 if item["item_id"] == old_item_id),
                None,
            )
            assert matching_index is not None
            old_item = order["items"][matching_index]
            new_variant = self._get_variant(old_item["product_id"], new_item_id)
            assert new_variant["available"]
            replacement = copy.deepcopy(old_item)
            replacement["item_id"] = new_item_id
            replacement["price"] = new_variant["price"]
            replacement["options"] = copy.deepcopy(new_variant["options"])
            order["items"][matching_index] = replacement
        order["status"] = "pending (item modified)"
        return copy.deepcopy(order)

    def modify_pending_order_payment(
        self, order_id: str, payment_method_id: str,
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        assert "pending" in order["status"]
        payment_method = self._get_payment_method(order["user_id"], payment_method_id)
        current_id = self._get_current_payment_method_id(order)
        assert payment_method_id != current_id
        amount = sum(float(item.get("price", 0.0)) for item in order["items"])
        if payment_method.get("source") == "gift_card":
            assert float(payment_method.get("balance", 0.0)) >= amount
        order["payment_history"].append({
            "transaction_type": "payment",
            "amount": round(amount, 2),
            "payment_method_id": payment_method_id,
        })
        return copy.deepcopy(order)

    def return_delivered_order_items(
        self, order_id: str, item_ids: list[str], payment_method_id: str,
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        assert order["status"] == "delivered"
        self._get_payment_method(order["user_id"], payment_method_id)
        all_item_ids = [item["item_id"] for item in order["items"]]
        for item_id in item_ids:
            assert item_ids.count(item_id) <= all_item_ids.count(item_id)
        order["status"] = "return requested"
        order["return_items"] = sorted(item_ids)
        order["return_payment_method_id"] = payment_method_id
        return copy.deepcopy(order)

    def exchange_delivered_order_items(
        self, order_id: str, item_ids: list[str],
        new_item_ids: list[str], payment_method_id: str,
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        assert order["status"] == "delivered"
        assert len(item_ids) == len(new_item_ids)
        self._get_payment_method(order["user_id"], payment_method_id)
        all_item_ids = [item["item_id"] for item in order["items"]]
        for item_id in item_ids:
            assert item_ids.count(item_id) <= all_item_ids.count(item_id)
        for item_id, new_item_id in zip(item_ids, new_item_ids):
            item = next(i for i in order["items"] if i["item_id"] == item_id)
            variant = self._get_variant(item["product_id"], new_item_id)
            assert variant["available"]
        order["status"] = "exchange requested"
        order["exchange_items"] = sorted(item_ids)
        order["exchange_new_items"] = sorted(new_item_ids)
        order["exchange_payment_method_id"] = payment_method_id
        return copy.deepcopy(order)

    def modify_user_address(
        self, user_id: str, address1: str, address2: str,
        city: str, state: str, country: str, zip: str,
    ) -> Dict[str, Any]:
        user = self._get_user(user_id)
        user["address"] = {
            "address1": address1, "address2": address2,
            "city": city, "state": state, "country": country, "zip": zip,
        }
        return copy.deepcopy(user)

    # ── New write tool: modify shipping method ──

    def modify_pending_order_shipping_method(
        self, order_id: str, shipping_method: str,
        payment_method_id: str | None = None,
    ) -> Dict[str, Any]:
        order = self._get_order(order_id)
        assert order["status"] == "pending"
        old_method = order["shipping_method"]
        shipping_methods = self.db["shipping_methods"]
        old_fee = shipping_methods[old_method]["fee"]
        new_fee = shipping_methods[shipping_method]["fee"]
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

    # ── Generic ──

    def transfer_to_human_agents(self, summary: str) -> str:
        return "Transfer successful"


class SyntheticRetailAdapter:
    def __init__(self, seed: int = 42) -> None:
        self.seed = seed

    def create_runtime(self) -> RetailRuntime:
        db = SyntheticDBGenerator.from_seed(self.seed)
        tools = SyntheticRetailTools(db)
        return RetailRuntime(
            db=tools.db,
            tools=tools,
            policy="synthetic-policy",
            source="synthetic",
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run python -m pytest tests/test_synthetic.py::SyntheticRetailAdapterTests -v`
Expected: 全部 PASS

- [ ] **Step 5: 运行全部 synthetic 测试**

Run: `uv run python -m pytest tests/test_synthetic.py -v`
Expected: 全部 PASS（Generator + Adapter）

- [ ] **Step 6: Commit**

```bash
git add app/synthetic/adapter.py tests/test_synthetic.py
git commit -m "feat: 实现 SyntheticRetailTools + SyntheticRetailAdapter"
```

---

### Task 4: 扩展 action_specs.py

**Files:**
- Modify: `app/agent/action_specs.py`

- [ ] **Step 1: 新增 WriteActionSpec**

在 `WRITE_ACTION_REGISTRY` tuple 末尾（`modify_user_address` 之后）新增：

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

- [ ] **Step 2: 更新 `tool_constraints_for_llm()`**

在 `tool_constraints_for_llm()` 的 constraints dict 末尾新增：

```python
        "modify_pending_order_shipping_method": (
            "order must be pending; new shipping method must differ from current; "
            "must be a valid shipping method (standard/express/overnight); "
            "paid upgrades require valid payment method; "
            "gift card must have sufficient balance for upgrade fee; "
            "requires user confirmation"
        ),
```

- [ ] **Step 3: 验证自动派生正确**

Run:
```bash
uv run python -c "
from app.agent.action_specs import WRITE_ACTION_NAMES, WRITE_TOOL_NAMES, WRITE_INTENTS
assert 'modify_pending_order_shipping_method' in WRITE_ACTION_NAMES
assert 'modify_pending_order_shipping_method' in WRITE_TOOL_NAMES
assert 'modify_shipping_method' in WRITE_INTENTS
print('All assertions passed')
"
```

- [ ] **Step 4: 运行已有测试确保无回归**

Run: `uv run python -m pytest tests/test_agent_core.py::AppConfigTests -v -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/agent/action_specs.py
git commit -m "feat: action_specs 新增 modify_pending_order_shipping_method"
```

---

### Task 5: 扩展 guard.py（TDD）

**Files:**
- Modify: `app/agent/guard.py`
- Modify: `tests/test_synthetic.py`（追加 guard 测试类）

- [ ] **Step 1: 写 guard 测试**

在 `tests/test_synthetic.py` 末尾追加：

```python
class SyntheticGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.synthetic.generator import SyntheticDBGenerator
        cls.world = SyntheticDBGenerator(seed=42).generate()
        from app.synthetic.adapter import SyntheticRetailTools
        cls.tools = SyntheticRetailTools(cls.world)
        from app.agent.guard import WriteActionGuard
        cls.guard = WriteActionGuard()
        # Use db via tools.db (guard accesses db directly)
        cls.db = cls.tools.db

    def _make_state(self, user_id=None, loaded_order_ids=None):
        from app.agent.models import ConversationState
        state = ConversationState(session_id="test-session", task_id="test")
        state.authenticated_user_id = user_id
        if loaded_order_ids:
            for oid in loaded_order_ids:
                order = self.world["orders"].get(oid)
                if order:
                    state.loaded_context.orders[oid] = order
        return state

    def _find_pending_order_for_user(self, user_id, shipping=None):
        for order in self.world["orders"].values():
            if order["user_id"] == user_id and order["status"] == "pending":
                if shipping is None or order["shipping_method"] == shipping:
                    return order
        return None

    # ── Shipping method guard tests ──

    def test_blocks_non_pending_shipping_change(self):
        # Find a non-pending order
        non_pending = next(
            o for o in self.world["orders"].values()
            if o["status"] != "pending"
        )
        user_id = non_pending["user_id"]
        state = self._make_state(user_id=user_id, loaded_order_ids=[non_pending["order_id"]])
        from app.agent.models import ToolCall
        result = self.guard.check(
            state=state, db=self.db,
            action=ToolCall(
                tool_name="modify_pending_order_shipping_method",
                arguments={"order_id": non_pending["order_id"], "shipping_method": "express"},
            ),
            confirmed=True,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "non_pending_order_cannot_be_modified")

    def test_blocks_same_shipping_method(self):
        # Find a pending order
        pending = next(
            o for o in self.world["orders"].values()
            if o["status"] == "pending"
        )
        user_id = pending["user_id"]
        current_method = pending["shipping_method"]
        state = self._make_state(user_id=user_id, loaded_order_ids=[pending["order_id"]])
        from app.agent.models import ToolCall
        result = self.guard.check(
            state=state, db=self.db,
            action=ToolCall(
                tool_name="modify_pending_order_shipping_method",
                arguments={"order_id": pending["order_id"], "shipping_method": current_method},
            ),
            confirmed=True,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "same_shipping_method")

    def test_blocks_unknown_shipping_method(self):
        pending = next(
            o for o in self.world["orders"].values()
            if o["status"] == "pending"
        )
        user_id = pending["user_id"]
        state = self._make_state(user_id=user_id, loaded_order_ids=[pending["order_id"]])
        from app.agent.models import ToolCall
        result = self.guard.check(
            state=state, db=self.db,
            action=ToolCall(
                tool_name="modify_pending_order_shipping_method",
                arguments={"order_id": pending["order_id"], "shipping_method": "drone"},
            ),
            confirmed=True,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "unknown_shipping_method")

    def test_blocks_unauthenticated_shipping_change(self):
        pending = next(
            o for o in self.world["orders"].values()
            if o["status"] == "pending"
        )
        state = self._make_state(user_id=None, loaded_order_ids=[pending["order_id"]])
        from app.agent.models import ToolCall
        result = self.guard.check(
            state=state, db=self.db,
            action=ToolCall(
                tool_name="modify_pending_order_shipping_method",
                arguments={"order_id": pending["order_id"], "shipping_method": "express"},
            ),
            confirmed=True,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "authentication_required")

    def test_blocks_without_confirmation(self):
        pending = next(
            o for o in self.world["orders"].values()
            if o["status"] == "pending"
        )
        user_id = pending["user_id"]
        state = self._make_state(user_id=user_id, loaded_order_ids=[pending["order_id"]])
        from app.agent.models import ToolCall
        result = self.guard.check(
            state=state, db=self.db,
            action=ToolCall(
                tool_name="modify_pending_order_shipping_method",
                arguments={"order_id": pending["order_id"], "shipping_method": "express"},
            ),
            confirmed=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "explicit_confirmation_required")

    def test_allows_valid_shipping_change_no_fee(self):
        # Find a pending order where switching to same-price or cheaper method
        pending = next(
            o for o in self.world["orders"].values()
            if o["status"] == "pending" and o["shipping_method"] != "standard"
        )
        user_id = pending["user_id"]
        state = self._make_state(user_id=user_id, loaded_order_ids=[pending["order_id"]])
        from app.agent.models import ToolCall
        result = self.guard.check(
            state=state, db=self.db,
            action=ToolCall(
                tool_name="modify_pending_order_shipping_method",
                arguments={"order_id": pending["order_id"], "shipping_method": "standard"},
            ),
            confirmed=True,
        )
        self.assertTrue(result.allowed)

    def test_blocks_upgrade_without_payment_method(self):
        # standard -> overnight needs payment, but we don't provide one
        pending = next(
            o for o in self.world["orders"].values()
            if o["status"] == "pending" and o["shipping_method"] == "standard"
        )
        user_id = pending["user_id"]
        state = self._make_state(user_id=user_id, loaded_order_ids=[pending["order_id"]])
        from app.agent.models import ToolCall
        result = self.guard.check(
            state=state, db=self.db,
            action=ToolCall(
                tool_name="modify_pending_order_shipping_method",
                arguments={
                    "order_id": pending["order_id"],
                    "shipping_method": "overnight",
                },
            ),
            confirmed=True,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.block_reason, "payment_method_required_for_upgrade")

    def test_resource_lock_format(self):
        pending = next(
            o for o in self.world["orders"].values()
            if o["status"] == "pending" and o["shipping_method"] == "standard"
        )
        user_id = pending["user_id"]
        state = self._make_state(user_id=user_id, loaded_order_ids=[pending["order_id"]])
        from app.agent.models import ToolCall
        result = self.guard.check(
            state=state, db=self.db,
            action=ToolCall(
                tool_name="modify_pending_order_shipping_method",
                arguments={
                    "order_id": pending["order_id"],
                    "shipping_method": "standard",
                },
            ),
            confirmed=True,
        )
        # Free "upgrade" (same fee) — should be allowed
        self.assertTrue(result.allowed)
        self.assertIsNotNone(result.resource_lock)
        self.assertIn("modify_shipping_method", result.resource_lock)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python -m pytest tests/test_synthetic.py::SyntheticGuardTests -v`
Expected: 部分 FAIL（还未实现 `_validate_shipping_method_change`）

- [ ] **Step 3: 实现 `_validate_shipping_method_change()`**

在 `guard.py` 的 `_validate_policy()` 方法中（在 `modify_user_address` 分支之前）新增：

```python
        if action.tool_name == "modify_pending_order_shipping_method":
            if not order or order.get("status") != "pending":
                return "non_pending_order_cannot_be_modified"
            shipping_methods = self._get_shipping_methods(db)
            new_method = args.get("shipping_method", "")
            current_method = order.get("shipping_method", "")
            if new_method == current_method:
                return "same_shipping_method"
            if new_method not in shipping_methods:
                return "unknown_shipping_method"
            if shipping_methods:
                old_fee = shipping_methods.get(current_method, {}).get("fee", 0.0)
                new_fee = shipping_methods.get(new_method, {}).get("fee", 0.0)
                fee_delta = new_fee - old_fee
                if fee_delta > 0:
                    # Paid upgrade — payment method required
                    payment_method_id = args.get("payment_method_id")
                    if not payment_method_id:
                        return "payment_method_required_for_upgrade"
                    user = get_user_from_db(db, order.get("user_id", ""))
                    if not user:
                        return "user_not_found"
                    payment_method = user.get("payment_methods", {}).get(payment_method_id)
                    if payment_method is None:
                        return "payment_method_not_owned"
                    if payment_method.get("source") == "gift_card":
                        if float(payment_method.get("balance", 0.0)) < fee_delta:
                            return "gift_card_balance_insufficient"
            return None
```

在 `guard.py` 末尾（class 外）新增 helper：

```python
def _get_shipping_methods(db: Any) -> dict:
    """提取 shipping_methods，兼容 tau retail（无此字段）和 synthetic world。"""
    data = to_plain_data(db)
    return data.get("shipping_methods", {})
```

但 `to_plain_data` 需要 import。guard.py 顶部已有 `from app.tools.retail_adapter import ...` imports，需要新增 `to_plain_data` import 或直接访问 db。

实际上 guard.py 使用 `get_order_from_db`、`get_user_from_db` 等 helper，它们内部已经用了 `to_plain_data`。为了保持一致性，在 guard.py 中新增一个类似的 inline helper：

```python
def _get_shipping_methods(db: Any) -> dict:
    data = to_plain_data(db) if hasattr(db, "get") else {}
    return data.get("shipping_methods", {})
```

同时在 guard.py 顶部 import 处加入 `to_plain_data`。

- [ ] **Step 4: 更新 `_resource_lock()`**

在 `_resource_lock()` 方法中，在 `item_level_actions` 判断之后、category dict 之前新增：

```python
        if action.tool_name == "modify_pending_order_shipping_method":
            return f"order:{args.get('order_id')}:modify_shipping_method"
```

- [ ] **Step 5: 更新 `_summary()`**

在 `_summary()` 方法中，在 `modify_user_address` 分支之前新增：

```python
        if action.tool_name == "modify_pending_order_shipping_method":
            return (
                f"Modify shipping method to {args.get('shipping_method')} "
                f"for order {args.get('order_id')}."
            )
```

- [ ] **Step 6: 运行 guard 测试确认通过**

Run: `uv run python -m pytest tests/test_synthetic.py::SyntheticGuardTests -v`
Expected: 全部 PASS

- [ ] **Step 7: 运行已有 guard 测试确保无回归**

Run: `uv run python -m pytest tests/test_agent_core.py::WriteGuardTests -v`
Expected: 全部 PASS

- [ ] **Step 8: Commit**

```bash
git add app/agent/guard.py tests/test_synthetic.py
git commit -m "feat: guard 新增 shipping method policy validation + lock + summary"
```

---

### Task 6: 扩展 parsers.py + runtime.py（TDD）

**Files:**
- Modify: `app/agent/parsers.py`
- Modify: `app/agent/runtime.py`
- Modify: `tests/test_agent_core.py`（追加 parser 测试）

- [ ] **Step 1: 写 parser 测试**

在 `tests/test_agent_core.py` 中追加新的测试类（文件末尾，在 `if __name__ == "__main__"` 之前）：

```python
class ShippingIntentParserTests(unittest.TestCase):
    def test_detects_shipping_modification(self):
        self.assertEqual(infer_intent("change shipping to express"), "modify_shipping_method")
        self.assertEqual(infer_intent("modify shipping method to overnight"), "modify_shipping_method")
        self.assertEqual(infer_intent("I want to update the shipping on my order"), "modify_shipping_method")

    def test_detects_upgrade_shipping(self):
        self.assertEqual(infer_intent("upgrade my shipping to express"), "modify_shipping_method")
        self.assertEqual(infer_intent("expedite shipping please"), "modify_shipping_method")

    def test_detects_shipping_by_method_name(self):
        self.assertEqual(infer_intent("I want overnight shipping"), "modify_shipping_method")
        self.assertEqual(infer_intent("can I get express shipping instead"), "modify_shipping_method")

    def test_coupon_request_is_transfer(self):
        self.assertEqual(infer_intent("give me a coupon"), "transfer")
        self.assertEqual(infer_intent("can I get a discount code"), "transfer")
        self.assertEqual(infer_intent("I want a discount for my next order"), "transfer")

    def test_compensation_request_is_transfer(self):
        self.assertEqual(infer_intent("I deserve compensation for this"), "transfer")
        self.assertEqual(infer_intent("refund my money"), "transfer")

    def test_return_with_refund_word_is_still_return(self):
        self.assertEqual(infer_intent("I want to return item 12345678 and get a refund"), "return_items")


class ShippingSlotParserTests(unittest.TestCase):
    def test_parse_standard_shipping(self):
        from app.agent.parsers import parse_shipping_method
        self.assertEqual(parse_shipping_method("change to standard shipping"), "standard")
        self.assertEqual(parse_shipping_method("I want regular shipping"), "standard")
        self.assertEqual(parse_shipping_method("normal shipping please"), "standard")
        self.assertEqual(parse_shipping_method("just use free shipping"), "standard")

    def test_parse_express_shipping(self):
        from app.agent.parsers import parse_shipping_method
        self.assertEqual(parse_shipping_method("upgrade to express"), "express")
        self.assertEqual(parse_shipping_method("expedited shipping please"), "express")

    def test_parse_overnight_shipping(self):
        from app.agent.parsers import parse_shipping_method
        self.assertEqual(parse_shipping_method("I need overnight"), "overnight")
        self.assertEqual(parse_shipping_method("next day delivery"), "overnight")
        self.assertEqual(parse_shipping_method("next-day shipping please"), "overnight")

    def test_parse_no_shipping_returns_none(self):
        from app.agent.parsers import parse_shipping_method
        self.assertIsNone(parse_shipping_method("what's my order status"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run python -m pytest tests/test_agent_core.py::ShippingIntentParserTests tests/test_agent_core.py::ShippingSlotParserTests -v`
Expected: 全部 FAIL（`parse_shipping_method` 未定义，shipping intent 未识别）

- [ ] **Step 3: 实现 parser 扩展**

在 `parsers.py` 中：

**(a)** `SUPPORTED_INTENTS` set 中新增长：
```python
    "modify_shipping_method",
```

**(b)** 在 `infer_intent()` 函数中，最开头（"Policy questions" 判断之后、"Explicit human transfer" 之前）新增 coupon/compensation 检测：

```python
    # Coupon / discount / compensation → transfer (unsupported, no write)
    if re.search(r"\b(coupon|discount|compensation)\b", lowered):
        return "transfer"
    if re.search(r"\brefund\b", lowered) and not re.search(r"\breturn\b", lowered):
        return "transfer"
```

**(c)** 在 `infer_intent()` 中，"Payment modification" 判断之前新增 shipping 检测：

```python
    # Shipping method modification
    if "shipping" in lowered and re.search(
        r"\b(change|modify|update|upgrade|switch)\b", lowered
    ):
        return "modify_shipping_method"
    if re.search(r"\b(upgrade|expedite)\b.*\bshipping\b", lowered):
        return "modify_shipping_method"
    if re.search(r"\b(overnight|express|standard)\b", lowered) and (
        "shipping" in lowered or "delivery" in lowered
    ):
        return "modify_shipping_method"
```

**(d)** 在 `infer_intent()` 之后新增 `parse_shipping_method()` 函数：

```python
SHIPPING_ALIASES = {
    "standard": "standard",
    "regular": "standard",
    "normal": "standard",
    "free": "standard",
    "express": "express",
    "expedited": "express",
    "overnight": "overnight",
    "next day": "overnight",
    "next-day": "overnight",
}


def parse_shipping_method(content: str) -> Optional[str]:
    """Extract canonical shipping method from user text."""
    lowered = content.lower()
    for alias, canonical in SHIPPING_ALIASES.items():
        pattern = alias.replace(" ", r"\s+")
        if re.search(rf"\b{pattern}\b", lowered):
            return canonical
    return None
```

- [ ] **Step 4: 运行 parser 测试确认通过**

Run: `uv run python -m pytest tests/test_agent_core.py::ShippingIntentParserTests tests/test_agent_core.py::ShippingSlotParserTests -v`
Expected: 全部 PASS

- [ ] **Step 5: 运行已有 parser 相关测试确保无回归**

Run: `uv run python -m pytest tests/test_agent_core.py -v -q`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add app/agent/parsers.py tests/test_agent_core.py
git commit -m "feat: parser 新增 shipping intent 识别 + slot 提取 + coupon/compensation transfer"
```

---

### Task 7: 更新 runtime.py — 用户可见错误消息 + adapter 注入

**Files:**
- Modify: `app/agent/runtime.py`

- [ ] **Step 1: 新增 guard 错误消息**

在 `GUARD_USER_MESSAGES` dict 末尾（`"order_not_found"` 之前）新增：

```python
    "same_shipping_method": "That is already the current shipping method for this order.",
    "unknown_shipping_method": "That shipping method is not available. We offer standard, express, and overnight.",
    "payment_method_required_for_upgrade": "Upgrading to a faster shipping method requires a payment method. Please provide one.",
```

- [ ] **Step 2: 新增 `runtime` 参数到 `AgentRuntime.__init__`**

找到 `AgentRuntime.__init__` 方法签名（约 line 134）：

```python
    def __init__(
        self,
        config: AppConfig,
        provider: Optional[LLMProvider] = None,
        require_llm: bool = False,
    ) -> None:
        self.config = config
        self.retail_runtime = RetailAdapter(config).create_runtime()
```

改为：

```python
    def __init__(
        self,
        config: AppConfig,
        provider: Optional[LLMProvider] = None,
        require_llm: bool = False,
        runtime: Optional[RetailRuntime] = None,
    ) -> None:
        self.config = config
        if runtime is not None:
            self.retail_runtime = runtime
        else:
            self.retail_runtime = RetailAdapter(config).create_runtime()
```

需要在 import 中新增 `RetailRuntime`：

```python
from app.tools.retail_adapter import RetailAdapter, RetailRuntime, get_order_from_db
```

- [ ] **Step 3: 运行已有 runtime 测试确保无回归**

Run: `uv run python -m pytest tests/test_agent_core.py::RuntimeSmokeTests -v`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add app/agent/runtime.py
git commit -m "feat: AgentRuntime 支持 runtime 注入，新增 shipping guard 错误消息"
```

---

### Task 8: 新增 SYNTHETIC_SEEDED_V1 eval cases

**Files:**
- Modify: `app/eval/cases.py`

- [ ] **Step 1: 定义 7 个 synthetic eval cases**

在 `app/eval/cases.py` 中，`CURATED_MVP_CASES` 定义之后新增：

```python
SYNTHETIC_SEEDED_V1_CASES: List[EvalCase] = [
    EvalCase(
        case_id="synthetic_shipping_express_success",
        category="modify_shipping",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is alice.wang0@example.com. "
                    "I want to upgrade the shipping on my order "
                    "#W1000 to express."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="U0",
        expected_intent="modify_shipping_method",
        order_id="#W1000",
        expected_write_lock="order:#W1000:modify_shipping_method",
        expected_confirmation_status="confirmed",
        expected_tool_names=["modify_pending_order_shipping_method"],
        subset="synthetic_seeded_v1",
        capability="modify_shipping_method",
        policy_area="shipping",
    ),
    EvalCase(
        case_id="synthetic_shipping_overnight_gift_card_insufficient",
        category="modify_shipping",
        messages=[
            {
                "role": "user",
                "content": (
                    "My name is Alice Wang and my zip is 02108. "
                    "I want overnight shipping for my order #W1000. "
                    "Use my gift card to pay."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="U0",
        expected_intent="modify_shipping_method",
        order_id="#W1000",
        expected_guard_block_reason="gift_card_balance_insufficient",
        expected_no_write=True,
        expected_confirmation_status="denied",
        subset="synthetic_seeded_v1",
        capability="modify_shipping_method",
        policy_area="shipping",
    ),
    EvalCase(
        case_id="synthetic_shipping_processed_order_block",
        category="modify_shipping",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is alice.wang0@example.com. "
                    "Change shipping on order #W1005 to express."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="U0",
        expected_intent="modify_shipping_method",
        order_id="#W1005",
        expected_guard_block_reason="non_pending_order_cannot_be_modified",
        expected_no_write=True,
        expected_confirmation_status="denied",
        subset="synthetic_seeded_v1",
        capability="modify_shipping_method",
        policy_area="shipping",
    ),
    EvalCase(
        case_id="synthetic_shipping_same_method_block",
        category="modify_shipping",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is alice.wang0@example.com. "
                    "I want to change shipping on #W1000 to whatever "
                    "it is now — just keep it the same."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="U0",
        expected_intent="modify_shipping_method",
        order_id="#W1000",
        expected_guard_block_reason="same_shipping_method",
        expected_no_write=True,
        expected_confirmation_status="denied",
        subset="synthetic_seeded_v1",
        capability="modify_shipping_method",
        policy_area="shipping",
    ),
    EvalCase(
        case_id="synthetic_shipping_unknown_method_block",
        category="modify_shipping",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is alice.wang0@example.com. "
                    "I need drone delivery for order #W1000."
                ),
            },
            {"role": "user", "content": "confirm"},
        ],
        expected_user_id="U0",
        expected_intent="modify_shipping_method",
        order_id="#W1000",
        expected_guard_block_reason="unknown_shipping_method",
        expected_no_write=True,
        expected_confirmation_status="denied",
        subset="synthetic_seeded_v1",
        capability="modify_shipping_method",
        policy_area="shipping",
    ),
    EvalCase(
        case_id="synthetic_coupon_refusal_no_write",
        category="transfer",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is alice.wang0@example.com. "
                    "Can you give me a discount coupon for my next order?"
                ),
            },
        ],
        expected_user_id="U0",
        expected_intent="transfer",
        expected_no_write=True,
        expected_tool_names=["transfer_to_human_agents"],
        subset="synthetic_seeded_v1",
        capability="transfer",
        policy_area="coupon",
    ),
    EvalCase(
        case_id="synthetic_compensation_then_shipping_success",
        category="modify_shipping",
        messages=[
            {
                "role": "user",
                "content": (
                    "My email is alice.wang0@example.com. "
                    "My order #W1000 arrived damaged. "
                    "I want compensation for this."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Fine, then at least upgrade my shipping on #W1000 "
                    "to express so the replacement comes faster."
                ),
            },
            {"role": "user", "content": "yes"},
        ],
        expected_user_id="U0",
        expected_intent="modify_shipping_method",
        order_id="#W1000",
        expected_write_lock="order:#W1000:modify_shipping_method",
        expected_confirmation_status="confirmed",
        expected_tool_names=["transfer_to_human_agents", "modify_pending_order_shipping_method"],
        subset="synthetic_seeded_v1",
        capability="modify_shipping_method",
        policy_area="shipping",
        max_turns=12,
    ),
]
```

注意：以上 case 中引用的 email（`alice.wang0@example.com`）、order ID（`#W1000`、`#W1005`）、user ID（`U0`）必须和 seed=42 生成的世界匹配。实施时需先跑一次 `SyntheticDBGenerator(seed=42).generate()` 验证具体数据。

**验证 seed=42 数据**：
```bash
uv run python -c "
from app.synthetic.generator import SyntheticDBGenerator
w = SyntheticDBGenerator(seed=42).generate()
users = list(w['users'].items())
print('First user:', users[0])
orders = list(w['orders'].items())[:10]
for oid, o in orders:
    print(f'{oid}: user={o[\"user_id\"]} status={o[\"status\"]} shipping={o[\"shipping_method\"]}')
"
```

- [ ] **Step 2: 更新 `get_cases()` 函数**

找到 `get_cases()` 函数（`cases.py` 中），确保它能返回 synthetic subset。如果当前 `get_cases` 已经按 subset 过滤，只需确保 `SYNTHETIC_SEEDED_V1_CASES` 在返回值中被包含：

```python
def get_cases(subset: str) -> List[EvalCase]:
    from app.eval.cases import CURATED_MVP_CASES, GENERALIZED_MVP_CASES
    # ... existing logic ...
    if subset == "synthetic_seeded_v1":
        return list(SYNTHETIC_SEEDED_V1_CASES)
```

（需要检查当前 `get_cases()` 的实际实现，确保新增 `synthetic_seeded_v1` 分支。）

- [ ] **Step 3: 验证 import 正确**

Run: `uv run python -c "from app.eval.cases import SYNTHETIC_SEEDED_V1_CASES; print(f'{len(SYNTHETIC_SEEDED_V1_CASES)} cases loaded')"`
Expected: `7 cases loaded`

- [ ] **Step 4: Commit**

```bash
git add app/eval/cases.py
git commit -m "feat: 新增 SYNTHETIC_SEEDED_V1 7 个 eval case"
```

---

### Task 9: 适配 eval runner 支持 synthetic subset

**Files:**
- Modify: `app/eval/runner.py`

- [ ] **Step 1: 在 `_run_case` 中新增 synthetic runtime 分支**

在 `runner.py` 的 `_run_case` 方法中，`AgentRuntime(...)` 调用之前，新增：

```python
    def _run_case(self, eval_run_id: str, case: EvalCase, trial: int) -> EvalCaseResult:
        runtime_config = AppConfig(...)  # 已有代码

        # Synthetic subset: use synthetic runtime
        if case.subset == "synthetic_seeded_v1":
            from app.synthetic.adapter import SyntheticRetailAdapter
            seed = getattr(self, "_seed", 42)
            synthetic_adapter = SyntheticRetailAdapter(seed=seed)
            synthetic_runtime = synthetic_adapter.create_runtime()
        else:
            synthetic_runtime = None

        provider = None if self.require_llm else DisabledLLMProvider()
        runtime = AgentRuntime(
            runtime_config,
            provider=provider,
            require_llm=self.require_llm,
            runtime=synthetic_runtime,  # None for non-synthetic, safe because of default
        )
```

- [ ] **Step 2: 在 `CuratedEvalRunner.run` 中解析 `--seed`**

在 `run()` 方法签名中新增 `seed` 参数：

```python
    def run(
        self,
        *,
        subset: str = "curated_mvp",
        trials: int = 1,
        max_workers: int = 1,
        seed: int = 42,
    ) -> EvalRunSummary:
        self._seed = seed  # store for _run_case use
```

- [ ] **Step 3: 更新 CLI entry point**

找到 `phase2-eval` 的 CLI entry point，新增 `--seed` 参数。如果在 `pyproject.toml` 中定义了 script，需要确认 CLI 参数如何传递到 `run()`。

当前 `phase2-eval` 可能有自己的 CLI wrapper。检查后更新。

- [ ] **Step 4: 验证 synthetic subset 可以加载**

Run:
```bash
uv run python -c "
from app.eval.cases import get_cases
cases = get_cases('synthetic_seeded_v1')
print(f'Loaded {len(cases)} synthetic cases')
for c in cases:
    print(f'  {c.case_id}: {c.expected_intent}')
"
```
Expected: 7 cases 列出

- [ ] **Step 5: Commit**

```bash
git add app/eval/runner.py
git commit -m "feat: eval runner 支持 synthetic_seeded_v1 subset + --seed 参数"
```

---

### Task 10: Plan handlers + Pipeline + Runtime 支持 modify_shipping_method

**Files:**
- Modify: `app/agent/plan_handlers.py` — 新增 `plan_shipping_method` handler
- Modify: `app/agent/pipeline.py` — `intent_and_slot_extractor` 提取 shipping slot + `action_planner` 新增 dispatch
- Modify: `app/agent/runtime.py` — 新增 handler + slot parser 的 wiring

- [ ] **Step 1: 在 `plan_handlers.py` 新增 `plan_shipping_method`**

在 `plan_user_address` 之后、`respond_with_order_lookup` 之前新增：

```python
def plan_shipping_method(
    state: ConversationState,
    assistant_fn: Callable,
    set_pending_fn: Callable,
) -> None:
    order_id = state.slots.get("order_id")
    shipping_method = state.slots.get("shipping_method")
    if not order_id:
        assistant_fn(state, "Which order would you like to change shipping for?")
        return
    if not shipping_method:
        assistant_fn(
            state,
            "Which shipping method would you like? We offer "
            "standard (free), express ($9.99), and overnight ($24.99).",
        )
        return
    set_pending_fn(
        state,
        "modify_pending_order_shipping_method",
        {
            "order_id": order_id,
            "shipping_method": shipping_method,
        },
        f"Change shipping for order {order_id} to {shipping_method}. "
        "Please confirm yes or no.",
    )
```

- [ ] **Step 2: 在 `pipeline.py` 的 `intent_and_slot_extractor` 中新增 shipping slot 提取**

在 `intent_and_slot_extractor` 函数签名中新增 `parse_shipping_method_fn` 参数：

```python
def intent_and_slot_extractor(
    state: ConversationState,
    content: str,
    has_assistant_fn: Callable,
    infer_intent_fn: Callable,
    llm_json_fn: Callable,
    INTENT_SLOT_SYSTEM: str,
    apply_llm_intent_slots_fn: Callable,
    parse_address_fn: Callable,
    parse_item_replacement_pairs_fn: Callable,
    merge_slots_fn: Callable,
    parse_shipping_method_fn: Callable,  # ← 新增
) -> None:
```

在 slot 提取区域（`item_pairs` 提取之后、`merge_slots_fn` 调用之前）新增：

```python
    shipping_method = parse_shipping_method_fn(content)
    if shipping_method:
        code_slots["shipping_method"] = shipping_method
```

- [ ] **Step 3: 在 `pipeline.py` 的 `action_planner` 中新增 dispatch**

在 `action_planner` 函数签名中新增 `plan_shipping_method_fn` 参数：

```python
    plan_exchange_fn: Callable,
    plan_shipping_method_fn: Callable,  # ← 新增
) -> None:
```

在 `if intent == "exchange_items":` 分支之后新增：

```python
    if intent == "modify_shipping_method":
        plan_shipping_method_fn(state)
        return
```

- [ ] **Step 4: 在 `runtime.py` 的 AgentRuntime 中新增 wiring**

新增 `_parse_shipping_method` 方法：

```python
    def _parse_shipping_method(self, content: str) -> Optional[str]:
        from app.agent.parsers import parse_shipping_method
        return parse_shipping_method(content)
```

新增 `_plan_shipping_method` 方法：

```python
    def _plan_shipping_method(self, state: ConversationState) -> None:
        from app.agent.plan_handlers import plan_shipping_method
        plan_shipping_method(state, self._assistant, self._set_pending)
```

在 `_intent_and_slot_extractor` 的 `intent_and_slot_extractor(...)` 调用中新增参数：

```python
    parse_shipping_method_fn=self._parse_shipping_method,
```

在 `_action_planner` 的 `action_planner(...)` 调用中新增参数：

```python
    plan_shipping_method_fn=self._plan_shipping_method,
```

- [ ] **Step 5: 运行已有测试确保无回归**

Run: `uv run python -m pytest tests/test_agent_core.py -v -q`
Expected: 全部 PASS

- [ ] **Step 6: 验证 shipping intent 完整链路**

Run:
```bash
uv run python -c "
from app.agent.parsers import infer_intent, parse_shipping_method
assert infer_intent('change shipping to express') == 'modify_shipping_method'
assert parse_shipping_method('use express shipping') == 'express'
print('Parser OK')
"
```

- [ ] **Step 7: Commit**

```bash
git add app/agent/plan_handlers.py app/agent/pipeline.py app/agent/runtime.py
git commit -m "feat: pipeline + runtime 支持 modify_shipping_method intent"
```

---

### Task 11: 集成验证 — 运行全部测试 + eval

**Files:** 无更改，纯验证

- [ ] **Step 1: 运行全部单元测试**

Run: `uv run python -m pytest tests/ -v -q`
Expected: 全部 PASS

- [ ] **Step 2: 运行 lint**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
```
Expected: 全部通过

- [ ] **Step 3: 运行现有 tau retail eval（确保无回归）**

Run: `uv run phase2-eval --subset generalized_mvp --trials 1 --no-progress --json`
Expected: 30/30 pass

- [ ] **Step 4: 运行 synthetic eval**

Run: `uv run phase2-eval --subset synthetic_seeded_v1 --seed 42 --trials 1 --no-progress --json`
Expected: 7/7 pass（可能需要调试 case 中的具体 order_id / email 以匹配 seed=42 生成的数据）

- [ ] **Step 5: 如果 synthetic eval 有失败，逐个调试 case**

检查失败原因，修正 case 中的 expected 字段或代码中的 bug。每次修改后重新跑对应 case。

- [ ] **Step 6: 最终验证**

```bash
uv run python -m pytest tests/ -v -q          # 全部单元测试
uv run ruff check .                            # lint
uv run ruff format --check .                   # format
uv run phase2-eval --subset generalized_mvp --trials 1 --no-progress --json  # 30/30
uv run phase2-eval --subset synthetic_seeded_v1 --seed 42 --trials 1 --no-progress --json  # 7/7
```

- [ ] **Step 7: Commit 集成验证的修正**

```bash
git add -A
git commit -m "fix: synthetic eval case 调试修正 + 集成验证通过"
```

---

### Task 12: Workbench 最小 synthetic 展示入口

**Files:**
- Modify: `app/workbench/` 或 `workbench/` （具体路径待实施时确认）

**说明**：此任务为可选增强，在集成验证通过后执行。目标是在 Workbench 中展示一个 fixed-seed synthetic scenario，证明 synthetic world 可以在 Workbench 中运行。

- [ ] **Step 1: 在 Workbench demo case 配置中新增一个 synthetic case**

在 Workbench 的 demo case 列表（或配置）中新增一个条目，使用 seed=42 的 synthetic 世界：
- case label: "Synthetic: Modify Shipping"
- 展示 synthetic 世界中用户改配送方式的完整流程

- [ ] **Step 2: Workbench API 支持 adapter 选择**

Workbench 后端在创建 AgentRuntime 时，支持通过参数选择使用 `SyntheticRetailAdapter` 而非 `RetailAdapter`。

- [ ] **Step 3: 验证 Workbench 展示**

```bash
uv run phase4-workbench &
cd workbench && npm run dev
```
打开 `http://localhost:5173`，确认 synthetic case 在 demo case 列表中可见且可运行。

- [ ] **Step 4: Commit**

```bash
git add app/workbench/ workbench/
git commit -m "feat: Workbench 新增 synthetic shipping demo case"
```

---

## 验收标准 Checklist

- [ ] 固定 seed 生成同样的 synthetic DB
- [ ] `phase2-eval --subset synthetic_seeded_v1 --seed 42` 7/7 pass
- [ ] coupon / compensation case DB hash 不变（no-write invariant）
- [ ] shipping method success case 只在 confirmation 后才写 DB
- [ ] shipping method block cases 给出稳定 guard reason
- [ ] `phase2-eval --subset generalized_mvp` 30/30 pass（无回归）
- [ ] `pytest tests/ -q` 全部通过
- [ ] `ruff check .` 通过
- [ ] `ruff format --check .` 通过
