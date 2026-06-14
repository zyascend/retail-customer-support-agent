import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.cli.eval import eval_main


def _summary_stub(**overrides):
    base = {
        "eval_run_id": "eval-test",
        "subset": None,
        "trials": 1,
        "passed_count": 1,
        "case_count": 1,
        "pass_rate": 1.0,
        "metrics": {
            "pass_1": 1.0,
            "pass_k": 1.0,
            "db_accuracy": 1.0,
            "tool_call_success_rate": 1.0,
            "mutation_error_rate": 0.0,
        },
        "failure_analysis": {"failure_label_counts": {}},
        "results": [],
        "result_artifact_path": "result.json",
        "report_artifact_path": "report.json",
    }
    base.update(overrides)
    summary = SimpleNamespace(**base)
    summary.as_dict = lambda: dict(base)
    return summary


class EvalCLITests(unittest.TestCase):
    def test_compare_prints_case_sections_and_writes_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_root = Path(tmp) / "artifacts" / "phase2"
            reports_dir = artifact_root / "reports"
            reports_dir.mkdir(parents=True)
            baseline_path = reports_dir / "baseline.json"
            candidate_path = reports_dir / "candidate.json"
            baseline_path.write_text(
                json.dumps(
                    {
                        "eval_run_id": "baseline-run",
                        "model": "model-a",
                        "code_commit": "abc",
                        "metrics": {"pass_1": 0.5},
                        "failure_analysis": {"failure_label_counts": {"wrong_tool": 1}},
                        "report_artifact_path": str(baseline_path),
                        "results": [
                            {
                                "case_id": "fixed_case",
                                "passed": False,
                                "failure_label": "wrong_tool",
                                "trace_artifact_path": "baseline-fixed.trace.json",
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            candidate_path.write_text(
                json.dumps(
                    {
                        "eval_run_id": "candidate-run",
                        "model": "model-b",
                        "code_commit": "def",
                        "metrics": {"pass_1": 1.0},
                        "failure_analysis": {"failure_label_counts": {"passed": 1}},
                        "report_artifact_path": str(candidate_path),
                        "results": [
                            {
                                "case_id": "fixed_case",
                                "passed": True,
                                "failure_label": None,
                                "trace_artifact_path": "candidate-fixed.trace.json",
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = eval_main(
                    ["--compare", str(baseline_path), str(candidate_path)]
                )

            comparison_path = (
                artifact_root
                / "comparisons"
                / "baseline-run__vs__candidate-run.json"
            )
            comparison_exists = comparison_path.exists()
            comparison_payload = json.loads(
                comparison_path.read_text(encoding="utf-8")
            )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Phase 2 eval comparison", output)
        self.assertIn("overlap cases: 1", output)
        self.assertIn("fixed:", output)
        self.assertIn("fixed_case", output)
        self.assertTrue(comparison_exists)
        self.assertEqual(comparison_payload["baseline_eval_run_id"], "baseline-run")
        self.assertEqual(comparison_payload["candidate_eval_run_id"], "candidate-run")

    def test_compare_fails_cleanly_without_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = Path(tmp) / "baseline.json"
            candidate_path = Path(tmp) / "candidate.json"
            baseline_path.write_text(
                json.dumps(
                    {
                        "eval_run_id": "baseline-run",
                        "results": [{"case_id": "baseline_only", "passed": True}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            candidate_path.write_text(
                json.dumps(
                    {
                        "eval_run_id": "candidate-run",
                        "results": [{"case_id": "candidate_only", "passed": True}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = eval_main(
                    ["--compare", str(baseline_path), str(candidate_path)]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("no overlapping case ids", stderr.getvalue().lower())

    def test_compare_json_prints_json_and_writes_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_root = Path(tmp) / "artifacts" / "phase2"
            reports_dir = artifact_root / "reports"
            reports_dir.mkdir(parents=True)
            baseline_path = reports_dir / "baseline.json"
            candidate_path = reports_dir / "candidate.json"
            baseline_path.write_text(
                json.dumps(
                    {
                        "eval_run_id": "baseline-run",
                        "results": [{"case_id": "shared", "passed": True}],
                        "report_artifact_path": str(baseline_path),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            candidate_path.write_text(
                json.dumps(
                    {
                        "eval_run_id": "candidate-run",
                        "results": [{"case_id": "shared", "passed": True}],
                        "report_artifact_path": str(candidate_path),
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = eval_main(
                    ["--compare", str(baseline_path), str(candidate_path), "--json"]
                )

            comparison_path = (
                artifact_root
                / "comparisons"
                / "baseline-run__vs__candidate-run.json"
            )
            comparison_exists = comparison_path.exists()

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["baseline_eval_run_id"], "baseline-run")
        self.assertTrue(comparison_exists)

    def test_compare_falls_back_to_cli_artifact_dir_when_unrooted(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "cli-artifacts"
            artifact_dir.mkdir(parents=True)
            baseline_path = Path(tmp) / "baseline.json"
            candidate_path = Path(tmp) / "candidate.json"
            baseline_path.write_text(
                json.dumps(
                    {
                        "eval_run_id": "baseline-run",
                        "results": [{"case_id": "shared", "passed": True}],
                        "report_artifact_path": str(
                            Path(tmp) / "exports" / "baseline.json"
                        ),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            candidate_path.write_text(
                json.dumps(
                    {
                        "eval_run_id": "candidate-run",
                        "results": [{"case_id": "shared", "passed": True}],
                        "report_artifact_path": str(
                            Path(tmp) / "exports" / "candidate.json"
                        ),
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = eval_main(
                    [
                        "--compare",
                        str(baseline_path),
                        str(candidate_path),
                        "--artifact-dir",
                        str(artifact_dir),
                    ]
                )

            comparison_path = (
                artifact_dir / "comparisons" / "baseline-run__vs__candidate-run.json"
            )
            comparison_exists = comparison_path.exists()

        self.assertEqual(exit_code, 0)
        self.assertTrue(comparison_exists)
        self.assertIn("comparison artifact:", stdout.getvalue())

    def test_replay_requires_explicit_subset(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as ctx:
                eval_main(["--replay", "~/traces"])

        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--replay requires --subset", stderr.getvalue())

    def test_live_and_replay_are_rejected_together(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as ctx:
                eval_main(["--live", "--replay", "~/traces", "--subset", "curated_mvp"])

        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("replay mode cannot be combined with --live", stderr.getvalue())

    def test_replay_and_replay_case_are_mutually_exclusive(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as ctx:
                eval_main(
                    [
                        "--replay",
                        "~/traces",
                        "--replay-case",
                        "~/trace.json",
                        "--subset",
                        "curated_mvp",
                    ]
                )

        self.assertEqual(ctx.exception.code, 2)
        self.assertIn(
            "--replay and --replay-case are mutually exclusive",
            stderr.getvalue(),
        )

    def test_trials_must_be_positive(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as ctx:
                eval_main(["--trials", "0"])

        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--trials must be >= 1", stderr.getvalue())

    def test_normal_eval_defaults_to_curated_subset(self):
        summary = _summary_stub(subset="curated_mvp")
        with (
            patch("app.cli.eval.resolve_config") as resolve_config,
            patch("app.cli.eval.CuratedEvalRunner") as runner_cls,
        ):
            resolve_config.return_value = SimpleNamespace()
            runner = runner_cls.return_value
            runner.run.return_value = summary

            exit_code = eval_main([])

        self.assertEqual(exit_code, 0)
        runner.run.assert_called_once_with(
            subset="curated_mvp",
            trials=1,
            max_workers=50,
            seed=42,
        )

    def test_replay_case_json_runs_without_subset(self):
        stdout = io.StringIO()
        summary = _summary_stub(subset=None)
        with (
            patch("app.cli.eval.resolve_config") as resolve_config,
            patch("app.cli.eval.CuratedEvalRunner") as runner_cls,
            redirect_stdout(stdout),
        ):
            resolve_config.return_value = SimpleNamespace()
            runner = runner_cls.return_value
            runner.run.return_value = summary

            exit_code = eval_main(["--replay-case", "~/trace.json", "--json"])

        self.assertEqual(exit_code, 0)
        runner_cls.assert_called_once()
        kwargs = runner_cls.call_args.kwargs
        self.assertIsNone(kwargs["replay_trace_dir"])
        self.assertEqual(kwargs["replay_case_path"], Path("~/trace.json").expanduser())
        runner.run.assert_called_once_with(
            subset=None,
            trials=1,
            max_workers=50,
            seed=42,
        )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["eval_run_id"], "eval-test")

    def test_replay_wires_trace_dir_and_explicit_subset(self):
        summary = _summary_stub(subset="generalized_mvp")
        with (
            patch("app.cli.eval.resolve_config") as resolve_config,
            patch("app.cli.eval.CuratedEvalRunner") as runner_cls,
        ):
            resolve_config.return_value = SimpleNamespace()
            runner = runner_cls.return_value
            runner.run.return_value = summary

            exit_code = eval_main(
                ["--replay", "~/traces", "--subset", "generalized_mvp"]
            )

        self.assertEqual(exit_code, 0)
        kwargs = runner_cls.call_args.kwargs
        self.assertEqual(kwargs["replay_trace_dir"], Path("~/traces").expanduser())
        self.assertIsNone(kwargs["replay_case_path"])
        runner.run.assert_called_once_with(
            subset="generalized_mvp",
            trials=1,
            max_workers=50,
            seed=42,
        )


if __name__ == "__main__":
    unittest.main()
