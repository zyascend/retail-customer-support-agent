import unittest

from app.workbench.cases import (
    DEMO_CASE_IDS,
    GENERATED_DEMO_CASE_IDS,
    build_case_catalog,
    get_case_by_id,
)


class WorkbenchCaseCatalogTests(unittest.TestCase):
    def test_catalog_contains_demo_shortlist_and_all_cases(self):
        catalog = build_case_catalog()
        all_ids = {case["case_id"] for case in catalog["all_cases"]}
        demo_ids = [case["case_id"] for case in catalog["demo_cases"]]

        expected_demo_ids = [
            cid for cid in [*DEMO_CASE_IDS, *GENERATED_DEMO_CASE_IDS] if cid in all_ids
        ]
        self.assertEqual(demo_ids, expected_demo_ids)
        self.assertTrue(set(demo_ids).issubset(all_ids))
        self.assertEqual(catalog["subset"], "generalized_mvp")
        self.assertGreaterEqual(len(catalog["all_cases"]), 45)

    def test_case_serialization_has_script_metadata(self):
        catalog = build_case_catalog()
        case = next(
            item
            for item in catalog["all_cases"]
            if item["case_id"] == "cancel_pending_order"
        )
        source_case = get_case_by_id("cancel_pending_order")

        self.assertEqual(case["category"], "cancel")
        self.assertEqual(case["message_count"], 2)
        self.assertEqual(case["expected_intent"], "cancel_order")
        self.assertEqual(case["expected_order_status"], "cancelled")
        self.assertEqual(case["title"], "取消待处理订单")
        self.assertEqual(case["messages"], source_case.messages)
        self.assertIsNot(case["messages"], source_case.messages)
        for serialized_message, source_message in zip(
            case["messages"], source_case.messages, strict=True
        ):
            self.assertIsNot(serialized_message, source_message)
        self.assertEqual(case["expected_tool_names"], source_case.expected_tool_names)
        self.assertIsNot(case["expected_tool_names"], source_case.expected_tool_names)

    def test_get_case_by_id_returns_eval_case(self):
        case = get_case_by_id("transfer_to_human")

        self.assertEqual(case.case_id, "transfer_to_human")
        self.assertEqual(case.category, "transfer")

    def test_get_case_by_id_rejects_unknown_case(self):
        with self.assertRaisesRegex(ValueError, "unknown case"):
            get_case_by_id("missing-case")

    def test_generalized_catalog_can_be_serialized(self):
        catalog = build_case_catalog("generalized_mvp")

        self.assertEqual(catalog["subset"], "generalized_mvp")
        self.assertGreaterEqual(len(catalog["all_cases"]), 30)
        case_ids = {case["case_id"] for case in catalog["all_cases"]}
        self.assertIn("modify_pending_order_items_success", case_ids)
        self.assertIn("modify_pending_order_payment_success", case_ids)
        self.assertIn("auth_name_zip_lookup_order", case_ids)

    def test_demo_shortlist_includes_phase5_cases_when_available(self):
        catalog = build_case_catalog("generalized_mvp")
        demo_ids = [case["case_id"] for case in catalog["demo_cases"]]

        self.assertIn("auth_name_zip_lookup_order", demo_ids)
        self.assertIn("modify_pending_order_items_success", demo_ids)
        self.assertIn("modify_pending_order_payment_success", demo_ids)


if __name__ == "__main__":
    unittest.main()
