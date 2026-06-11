from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from app.config import resolve_config
from app.eval.runner import DEFAULT_EVAL_ARTIFACT_DIR, CuratedEvalRunner


def eval_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run curated MVP eval cases.")
    parser.add_argument("--subset", default="curated_mvp")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument(
        "--artifact-dir",
        default=os.getenv("EVAL_ARTIFACT_DIR", str(DEFAULT_EVAL_ARTIFACT_DIR)),
    )
    parser.add_argument("--tau3-retail-root", help="Override TAU3_RETAIL_ROOT.")
    parser.add_argument("--tau2-bench-root", help="Override TAU2_BENCH_ROOT.")
    parser.add_argument("--require-llm", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args(argv)

    if args.trials < 1:
        parser.error("--trials must be >= 1")

    config = resolve_config(
        tau3_retail_root=args.tau3_retail_root,
        tau2_bench_root=args.tau2_bench_root,
        artifact_dir=args.artifact_dir,
    )
    try:
        summary = CuratedEvalRunner(
            config=config,
            artifact_dir=Path(args.artifact_dir).expanduser(),
            require_llm=args.require_llm,
            progress_callback=None if args.no_progress else _print_progress,
        ).run(subset=args.subset, trials=args.trials)
    except Exception as exc:
        print(f"phase2-eval failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary.as_dict(), indent=2, sort_keys=True))
    else:
        _print_summary(summary)
    return 0 if summary.passed_count == summary.case_count else 1


def _print_summary(summary: object) -> None:
    print("Phase 2 curated eval")
    print(f"eval_run_id: {summary.eval_run_id}")
    print(f"subset: {summary.subset}")
    print(f"trials: {summary.trials}")
    print(f"passed: {summary.passed_count}/{summary.case_count}")
    print(f"pass_rate: {summary.pass_rate:.4f}")
    for result in summary.results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.case_id}: {result.failure_label or 'ok'}")
    print(f"artifact: {summary.result_artifact_path}")


def _print_progress(event: str, result: object) -> None:
    if event == "start":
        print(
            f"[RUN] trial={result.trial} case={result.case_id}",
            file=sys.stderr,
            flush=True,
        )
        return
    status = "PASS" if result.passed else "FAIL"
    print(
        f"[{status}] trial={result.trial} case={result.case_id} "
        f"duration={result.duration_seconds:.3f}s "
        f"label={result.failure_label or 'ok'}",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(eval_main())
