from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from app.dashboard.builder import DashboardBuilder

DEFAULT_DASHBOARD_DIR = Path("artifacts/phase3/dashboard")


def dashboard_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a static Phase 3 eval dashboard and trace viewer."
    )
    parser.add_argument(
        "report",
        help="Phase 2 eval report JSON, usually artifacts/phase2/reports/<eval_run_id>.json.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("PHASE3_DASHBOARD_DIR"),
        help="Directory to write index.html and dashboard-data.json.",
    )
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help="Include raw trace payloads instead of redacting common PII fields.",
    )
    args = parser.parse_args(argv)

    report_path = Path(args.report).expanduser()
    try:
        report = _read_json(report_path)
    except Exception as exc:
        print(f"phase3-dashboard failed to read report: {exc}", file=sys.stderr)
        return 1

    output_dir = _resolve_output_dir(args.output_dir, report)
    try:
        output = generate_dashboard(
            report=report,
            report_path=report_path,
            output_dir=output_dir,
            redact=not args.no_redact,
        )
    except Exception as exc:
        print(f"phase3-dashboard failed: {exc}", file=sys.stderr)
        return 1

    print("Phase 3 dashboard generated")
    print(f"eval_run_id: {report.get('eval_run_id', 'unknown')}")
    print(f"index: {output['index_path']}")
    print(f"data: {output['data_path']}")
    return 0


def generate_dashboard(
    *,
    report: dict,
    report_path: Path,
    output_dir: Path,
    redact: bool = True,
) -> dict:
    builder = DashboardBuilder(redact=redact)
    data = builder.build(report, report_path)
    html = builder.render_html(data)
    output_dir.mkdir(parents=True, exist_ok=True)
    data_path = output_dir / "dashboard-data.json"
    index_path = output_dir / "index.html"
    data_path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    index_path.write_text(html, encoding="utf-8")
    return {"index_path": index_path, "data_path": data_path, "data": data}


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("report JSON must be an object")
    return payload


def _resolve_output_dir(raw_output_dir: Optional[str], report: dict) -> Path:
    if raw_output_dir:
        return Path(raw_output_dir).expanduser()
    eval_run_id = str(report.get("eval_run_id") or "unknown-eval-run")
    return DEFAULT_DASHBOARD_DIR / eval_run_id


if __name__ == "__main__":
    raise SystemExit(dashboard_main())
