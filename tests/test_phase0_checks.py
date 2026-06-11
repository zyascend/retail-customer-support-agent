import json
import tempfile
import unittest
from pathlib import Path

from app.phase0.checks import run_environment_check
from app.phase0.config import Phase0Config


class EnvironmentCheckTests(unittest.TestCase):
    def test_reports_missing_retail_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tau2-bench"
            data = root / "data"
            retail = data / "tau2" / "domains" / "retail"
            retail.mkdir(parents=True)
            (root / "src" / "tau2").mkdir(parents=True)
            (root / "pyproject.toml").write_text("[project]\nname='tau2'\n")
            (root / "uv.lock").write_text("")
            (retail / "tasks.json").write_text(json.dumps([]))
            (retail / "split_tasks.json").write_text(json.dumps({"base": []}))
            (retail / "policy.md").write_text("policy")
            result = data / "tau2" / "results" / "final" / "result.json"
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps({"tasks": [], "simulations": []}))

            check = run_environment_check(
                Phase0Config(
                    tau2_bench_root=root,
                    tau2_data_dir=data,
                    artifact_dir=Path(tmp) / "artifacts",
                    historical_result=result,
                )
            )

        self.assertFalse(check.ok)
        messages = {message.name: message for message in check.messages}
        self.assertEqual(messages["retail_files"].status, "error")
        self.assertIn("db.json", messages["retail_files"].detail)


if __name__ == "__main__":
    unittest.main()
