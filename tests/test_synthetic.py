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
