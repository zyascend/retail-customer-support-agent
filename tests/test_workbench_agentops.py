from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.workbench.agentops import AgentOpsService
from app.workbench.errors import WorkbenchAPIError


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class AgentOpsServiceTests(unittest.TestCase):
    def test_list_reports_returns_latest_report_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_json(
                artifact_dir / "reports" / "eval-run-a.json",
                {
                    "eval_run_id": "eval-run-a",
                    "created_at": "2026-06-15T01:00:00+00:00",
                    "eval_backend": "live",
                    "model": "deepseek-v4-flash",
                    "baseline_metadata": {
                        "provider": "deepseek",
                        "subset": "live_smoke_core",
                    },
                    "results": [
                        {"case_id": "case-a-1", "passed": True},
                        {"case_id": "case-a-2", "passed": False},
                    ],
                },
            )
            _write_json(
                artifact_dir / "reports" / "eval-run-b.json",
                {
                    "eval_run_id": "eval-run-b",
                    "created_at": "2026-06-15T02:00:00+00:00",
                    "eval_backend": "scripted_offline_demo",
                    "model": "deepseek-v4-flash",
                    "baseline_metadata": {
                        "provider": "deepseek",
                        "subset": "curated_mvp",
                    },
                    "results": [{"case_id": "case-b-1", "passed": False}],
                },
            )

            service = AgentOpsService(artifact_dir=artifact_dir)
            reports = service.list_reports()

        self.assertEqual([report.run_id for report in reports], ["eval-run-b", "eval-run-a"])
        self.assertEqual(reports[0].failure_case_count, 1)
        self.assertEqual(reports[0].fail_count, 1)
        self.assertEqual(reports[0].subset, "curated_mvp")

    def test_get_report_detail_raises_structured_error_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = AgentOpsService(artifact_dir=Path(tmp))

            with self.assertRaises(WorkbenchAPIError) as context:
                service.get_report("missing-run")

        self.assertEqual(context.exception.code, "report_not_found")
        self.assertEqual(context.exception.status_code, 404)
