import unittest

from app.workbench.cases import DEMO_CASE_IDS, build_case_catalog, get_case_by_id


class WorkbenchCaseCatalogTests(unittest.TestCase):
    def test_catalog_contains_demo_shortlist_and_all_cases(self):
        catalog = build_case_catalog()
        all_ids = {case["case_id"] for case in catalog["all_cases"]}
        demo_ids = [case["case_id"] for case in catalog["demo_cases"]]

        self.assertEqual(demo_ids, DEMO_CASE_IDS)
        self.assertTrue(set(DEMO_CASE_IDS).issubset(all_ids))
        self.assertEqual(catalog["subset"], "curated_mvp")
        self.assertGreaterEqual(len(catalog["all_cases"]), 11)

    def test_case_serialization_has_script_metadata(self):
        catalog = build_case_catalog()
        case = next(
            item
            for item in catalog["all_cases"]
            if item["case_id"] == "cancel_pending_order"
        )

        self.assertEqual(case["category"], "cancel")
        self.assertEqual(case["message_count"], 2)
        self.assertEqual(case["expected_intent"], "cancel_order")
        self.assertEqual(case["expected_order_status"], "cancelled")
        self.assertIn("Cancel", case["title"])

    def test_get_case_by_id_returns_eval_case(self):
        case = get_case_by_id("transfer_to_human")

        self.assertEqual(case.case_id, "transfer_to_human")
        self.assertEqual(case.category, "transfer")

    def test_get_case_by_id_rejects_unknown_case(self):
        with self.assertRaisesRegex(ValueError, "unknown case"):
            get_case_by_id("missing-case")


if __name__ == "__main__":
    unittest.main()
