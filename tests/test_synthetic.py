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
        self.assertGreater(pending_count, 20)

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
