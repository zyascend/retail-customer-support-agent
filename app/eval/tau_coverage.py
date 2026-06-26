"""Tau task coverage reporting utility.

Usage:
    python -m app.eval.tau_coverage              # print summary
    python -m app.eval.tau_coverage --json        # JSON output
    python -m app.eval.tau_coverage --remaining   # list only remaining tasks
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Optional

from app.config import resolve_config


@dataclass
class CoverageReport:
    total_tasks: int
    supported_count: int
    partial_count: int
    unsupported_count: int

    covered_by_supported_subset: list[str] = field(default_factory=list)
    covered_by_candidates_subset: list[str] = field(default_factory=list)
    covered_by_nl_evidence_subset: list[str] = field(default_factory=list)

    remaining_task_ids: list[str] = field(default_factory=list)
    remaining_by_status: dict[str, int] = field(default_factory=dict)

    all_task_ids: list[str] = field(default_factory=list)
    task_details: dict[str, dict] = field(default_factory=dict)

    def coverage_pct(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        unique_covered = len(
            set(self.covered_by_supported_subset)
            | set(self.covered_by_candidates_subset)
            | set(self.covered_by_nl_evidence_subset)
        )
        return unique_covered / self.total_tasks

    def remaining_count(self) -> int:
        return len(self.remaining_task_ids)


def build_coverage_report(config=None) -> CoverageReport:
    """Compute exact tau task coverage from classify_task results."""
    if config is None:
        config = resolve_config()

    from app.analysis.tau_task_analyzer import (
        _resolve_tau3_retail_dir,
        classify_task,
        load_splits,
        load_tasks,
    )

    retail_dir = _resolve_tau3_retail_dir(config)
    tasks = load_tasks(retail_dir)
    splits = load_splits(retail_dir)

    task_classifications: dict[str, dict] = {}
    for task in tasks:
        tid = str(task["id"])
        c = classify_task(task, splits)
        task_classifications[tid] = {
            "status": c.status,
            "subcategory": c.subcategory,
            "has_nl_assertion": c.has_nl_assertion,
            "missing_tools": list(c.missing_tools),
            "split": c.split,
            "action_count": c.action_count,
        }

    supported_task_ids = sorted(
        [tid for tid, d in task_classifications.items() if d["status"] == "supported"],
        key=int,
    )
    partial_task_ids = sorted(
        [tid for tid, d in task_classifications.items() if d["status"] == "partial"],
        key=int,
    )
    unsupported_task_ids = sorted(
        [tid for tid, d in task_classifications.items() if d["status"] == "unsupported"],
        key=int,
    )

    from app.analysis.tau_task_analyzer import select_phase12_next_candidates

    classifications = [classify_task(t, splits) for t in tasks]
    candidates = select_phase12_next_candidates(classifications, limit=10)
    candidate_ids = sorted({str(c.task_id) for c in candidates}, key=int)

    all_covered = set(supported_task_ids) | set(candidate_ids)
    all_task_ids_set = set(task_classifications.keys())
    remaining = sorted(all_task_ids_set - all_covered, key=int)

    remaining_by_status: dict[str, int] = {}
    for tid in remaining:
        st = task_classifications[tid]["status"]
        remaining_by_status[st] = remaining_by_status.get(st, 0) + 1

    return CoverageReport(
        total_tasks=len(tasks),
        supported_count=len(supported_task_ids),
        partial_count=len(partial_task_ids),
        unsupported_count=len(unsupported_task_ids),
        covered_by_supported_subset=supported_task_ids,
        covered_by_candidates_subset=candidate_ids,
        covered_by_nl_evidence_subset=[],
        remaining_task_ids=remaining,
        remaining_by_status=remaining_by_status,
        all_task_ids=sorted(all_task_ids_set, key=int),
        task_details={tid: dict(task_classifications[tid]) for tid in task_classifications},
    )


def print_report(report: CoverageReport, remaining_only: bool = False) -> None:
    """Print a human-readable coverage report."""
    if not remaining_only:
        print("=== Tau Task Coverage Report ===\n")
        print(f"Total tasks:       {report.total_tasks}")
        print(f"Supported:         {report.supported_count}")
        print(f"Partial:           {report.partial_count}")
        print(f"Unsupported:       {report.unsupported_count}")
        print()
        print(f"Covered by supported subset:   {len(report.covered_by_supported_subset)}")
        print(f"Covered by candidates subset:  {len(report.covered_by_candidates_subset)}")
        print(f"Covered by nl_evidence subset: {len(report.covered_by_nl_evidence_subset)}")
        unique = len(
            set(report.covered_by_supported_subset)
            | set(report.covered_by_candidates_subset)
            | set(report.covered_by_nl_evidence_subset)
        )
        print(f"Unique covered:    {unique}")
        print(f"Coverage:          {report.coverage_pct():.1%}")
        print(f"Remaining:         {report.remaining_count()}")
        print()

    if report.remaining_task_ids:
        print(f"--- Remaining ({report.remaining_count()} tasks) ---")
        for tid in report.remaining_task_ids:
            detail = report.task_details.get(tid, {})
            status = detail.get("status", "?")
            sub = detail.get("subcategory") or "-"
            nl = "NL" if detail.get("has_nl_assertion") else ""
            missing = ", ".join(detail.get("missing_tools", []))
            extra = f" [{sub}]" if sub else ""
            if nl:
                extra += f" {nl}"
            if missing:
                extra += f" missing: {missing}"
            print(f"  tau_{tid}: {status}{extra}")

    if not remaining_only:
        print(f"\n--- Remaining by status ---")
        for st, count in sorted(report.remaining_by_status.items()):
            print(f"  {st}: {count}")

    print(f"\nRun: uv run phase2-eval --subset tau_retail_all --live --max-workers 50")
    print("To run ALL 114 tasks in one shot.")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Tau task coverage report.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--remaining", action="store_true")
    args = parser.parse_args(argv or sys.argv[1:])

    try:
        config = resolve_config()
        report = build_coverage_report(config)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({
            "total_tasks": report.total_tasks,
            "supported_count": report.supported_count,
            "partial_count": report.partial_count,
            "unsupported_count": report.unsupported_count,
            "coverage_pct": report.coverage_pct(),
            "unique_covered": len(
                set(report.covered_by_supported_subset)
                | set(report.covered_by_candidates_subset)
            ),
            "remaining_count": report.remaining_count(),
            "remaining_task_ids": report.remaining_task_ids,
            "remaining_by_status": report.remaining_by_status,
        }, indent=2))
    else:
        print_report(report, remaining_only=args.remaining)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
