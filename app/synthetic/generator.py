# app/synthetic/generator.py
from __future__ import annotations

import copy
import json
import random
from pathlib import Path

FIRST_NAMES = [
    "Alice",
    "Bob",
    "Carol",
    "Dave",
    "Eve",
    "Frank",
    "Grace",
    "Heidi",
    "Ivan",
    "Judy",
    "Kevin",
    "Linda",
    "Mallory",
    "Nancy",
    "Oscar",
    "Peggy",
    "Quinn",
    "Ruth",
    "Steve",
    "Trudy",
]
LAST_NAMES = [
    "Wang",
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Rodriguez",
    "Martinez",
    "Hernandez",
    "Lopez",
    "Gonzalez",
    "Wilson",
    "Anderson",
    "Thomas",
    "Taylor",
    "Moore",
    "Jackson",
]
CITIES = [
    "New York",
    "Los Angeles",
    "Chicago",
    "Houston",
    "Phoenix",
    "Philadelphia",
    "San Antonio",
    "San Diego",
    "Dallas",
    "Austin",
]
STATES = [
    "NY",
    "CA",
    "IL",
    "TX",
    "AZ",
    "PA",
    "TX",
    "CA",
    "TX",
    "TX",
]
PRODUCT_NAMES = [
    "Ergonomic Chair",
    "Standing Desk",
    "Monitor Arm",
    "Keyboard Tray",
    "Desk Lamp",
    "Filing Cabinet",
    "Bookshelf",
    "Office Mat",
    "Headset",
    "Webcam",
    "Mouse Pad",
    "Laptop Stand",
    "Cable Organizer",
    "Whiteboard",
    "Plant Pot",
    "Water Bottle",
    "Notebook",
    "Pen Set",
    "Sticky Notes",
    "Paper Shredder",
    "Desk Fan",
    "USB Hub",
    "External Drive",
    "Mouse",
    "Keyboard",
    "Monitor",
    "Speaker",
    "Charger",
    "Backpack",
    "Lunch Box",
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
                    "available": self._rng.random() > 0.1,
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
            else:
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
        statuses = (
            ["pending"] * 30
            + ["delivered"] * 10
            + ["processing"] * 5
            + ["cancelled"] * 5
        )
        self._rng.shuffle(statuses)
        for i in range(50):
            oid = f"#W{1000 + i}"
            uid = self._rng.choice(user_ids)
            user = users[uid]
            item_count = self._rng.randint(1, 3)
            selected_products = self._rng.sample(
                product_ids, min(item_count, len(product_ids))
            )
            items = []
            amount = 0.0
            for pid in selected_products:
                variants = products[pid]["variants"]
                variant = self._rng.choice(list(variants.values()))
                items.append(
                    {
                        "item_id": variant["item_id"],
                        "product_id": pid,
                        "name": variant["name"],
                        "price": variant["price"],
                        "options": copy.deepcopy(variant["options"]),
                    }
                )
                amount += variant["price"]
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
