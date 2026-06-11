import json
import tempfile
import unittest
from pathlib import Path

from app.phase0.results import ResultParseError, summarize_result


class ResultSummaryTests(unittest.TestCase):
    def test_summarizes_synthetic_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.json"
            path.write_text(
                json.dumps(
                    {
                        "info": {"num_trials": 2},
                        "tasks": [{"id": "1"}, {"id": "2"}],
                        "simulations": [
                            {
                                "task_id": "1",
                                "trial": 0,
                                "reward_info": {
                                    "reward": 1.0,
                                    "reward_basis": ["DB"],
                                },
                                "agent_cost": 0.1,
                                "user_cost": 0.2,
                                "duration": 10,
                                "termination_reason": "user_stop",
                            },
                            {
                                "task_id": "1",
                                "trial": 1,
                                "reward_info": {
                                    "reward": 0.0,
                                    "reward_basis": ["DB"],
                                },
                                "agent_cost": 0.3,
                                "user_cost": 0.4,
                                "duration": 20,
                                "termination_reason": "agent_stop",
                            },
                            {
                                "task_id": "2",
                                "trial": 0,
                                "reward_info": {
                                    "reward": 1.0,
                                    "reward_basis": ["DB", "NL_ASSERTION"],
                                },
                                "agent_cost": 0.5,
                                "user_cost": 0.6,
                                "duration": 30,
                                "termination_reason": "user_stop",
                            },
                            {
                                "task_id": "2",
                                "trial": 1,
                                "reward_info": {
                                    "reward": 1.0,
                                    "reward_basis": ["DB", "NL_ASSERTION"],
                                },
                                "agent_cost": 0.7,
                                "user_cost": 0.8,
                                "duration": 40,
                                "termination_reason": "user_stop",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            summary = summarize_result(path)

        self.assertEqual(summary.task_count, 2)
        self.assertEqual(summary.simulation_count, 4)
        self.assertEqual(summary.trial_count, 2)
        self.assertAlmostEqual(summary.average_reward, 0.75)
        self.assertAlmostEqual(summary.pass_rate, 0.75)
        self.assertAlmostEqual(summary.pass_hat_ks["pass_hat_1"], 0.75)
        self.assertAlmostEqual(summary.pass_hat_ks["pass_hat_2"], 0.5)
        self.assertAlmostEqual(summary.average_agent_cost, 0.4)
        self.assertAlmostEqual(summary.average_user_cost, 0.5)
        self.assertAlmostEqual(summary.average_total_cost, 0.9)
        self.assertAlmostEqual(summary.average_duration_seconds, 25.0)
        self.assertEqual(summary.termination_counts["user_stop"], 3)
        self.assertEqual(summary.reward_basis_counts["DB"], 4)
        self.assertEqual(summary.reward_basis_counts["NL_ASSERTION"], 2)

    def test_missing_file_error(self):
        with self.assertRaisesRegex(ResultParseError, "result file not found"):
            summarize_result(Path("/tmp/does-not-exist-phase0-results.json"))

    def test_malformed_result_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ResultParseError, "not valid JSON"):
                summarize_result(path)


if __name__ == "__main__":
    unittest.main()
