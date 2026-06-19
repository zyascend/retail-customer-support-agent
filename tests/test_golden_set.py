import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.eval.cases import EvalCase, get_cases
from app.eval.golden_set import GoldenSet


class GoldenSetTests(unittest.TestCase):
    def test_golden_set_yaml_roundtrip(self):
        case = EvalCase(
            case_id="golden_lookup_case",
            category="lookup",
            messages=[
                {
                    "role": "user",
                    "content": "My email is sofia.rossi2645@example.com. What is the status of order #W5918442?",
                }
            ],
            expected_user_id="sofia_rossi_8776",
            expected_intent="lookup",
            order_id="#W5918442",
            expected_tool_names=["find_user_id_by_email", "get_order_details"],
            subset="golden",
            required_tools={"find_user_id_by_email"},
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "golden.yaml"
            golden_set = GoldenSet(path=path, cases=[case])

            golden_set.save()
            loaded = GoldenSet.load(path)

        self.assertEqual(loaded.path, path)
        self.assertEqual(loaded.cases, [case])

    def test_get_cases_golden_loads_yaml_backed_cases(self):
        case = EvalCase(
            case_id="golden_lookup_case",
            category="lookup",
            messages=[{"role": "user", "content": "status for #W5918442"}],
            expected_user_id="sofia_rossi_8776",
            expected_intent="lookup",
            order_id="#W5918442",
            expected_tool_names=["get_order_details"],
            subset="golden",
        )

        with patch("app.eval.golden_set.GoldenSet.load") as load:
            load.return_value = GoldenSet(path=Path("cases/golden.yaml"), cases=[case])
            cases = get_cases("golden")

        self.assertEqual(cases, [case])
        load.assert_called_once()

    def test_empty_golden_set_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "golden.yaml"
            path.write_text("cases: []\n", encoding="utf-8")

            loaded = GoldenSet.load(path)

        self.assertEqual(loaded.cases, [])

    def test_load_rejects_non_mapping_top_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "golden.yaml"
            path.write_text("- not-a-mapping\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "top level"):
                GoldenSet.load(path)

    def test_load_rejects_non_list_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "golden.yaml"
            path.write_text("cases: {}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "must be a list"):
                GoldenSet.load(path)

    def test_load_rejects_non_mapping_case_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "golden.yaml"
            path.write_text("cases:\n  - just-a-string\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "must be a mapping"):
                GoldenSet.load(path)

    def test_load_rejects_unknown_case_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "golden.yaml"
            path.write_text(
                "cases:\n"
                "  - case_id: golden_lookup_case\n"
                "    category: lookup\n"
                "    messages:\n"
                "      - role: user\n"
                "        content: status for #W5918442\n"
                "    expected_user_id: sofia_rossi_8776\n"
                "    expected_intent: lookup\n"
                "    unexpected_field: nope\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "unknown fields"):
                GoldenSet.load(path)


if __name__ == "__main__":
    unittest.main()
