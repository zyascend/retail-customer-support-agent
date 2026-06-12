from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from app.config import resolve_config
from app.eval.metrics import build_comparison_artifact
from app.eval.runner import DEFAULT_EVAL_ARTIFACT_DIR, CuratedEvalRunner


def eval_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run curated MVP eval cases.")
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("BASELINE_JSON", "CANDIDATE_JSON"),
        help="Compare two Phase 2 summary or report JSON artifacts.",
    )
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

    if args.compare:
        return _compare(args.compare, json_output=args.json)

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


def _compare(paths: list[str], *, json_output: bool) -> int:
    baseline = _read_json_artifact(Path(paths[0]).expanduser())
    candidate = _read_json_artifact(Path(paths[1]).expanduser())
    comparison = build_comparison_artifact(
        baseline=baseline,
        candidate=candidate,
    )
    if json_output:
        print(json.dumps(comparison, indent=2, sort_keys=True))
        return 0
    _print_comparison(comparison)
    return 0


def _read_json_artifact(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _print_comparison(comparison: dict) -> None:
    print("Phase 2 eval comparison")
    print(f"baseline: {comparison['baseline_eval_run_id']}")
    print(f"candidate: {comparison['candidate_eval_run_id']}")
    for name in (
        "pass_1",
        "pass_k",
        "db_accuracy",
        "tool_call_success_rate",
        "mutation_error_rate",
        "average_latency_seconds",
    ):
        metric = comparison["metric_deltas"].get(name)
        if not metric:
            continue
        print(
            f"{name}: baseline={metric['baseline']} "
            f"candidate={metric['candidate']} delta={metric['delta']}"
        )


def _print_summary(summary: object) -> None:
    print("Phase 2 curated eval")
    print(f"eval_run_id: {summary.eval_run_id}")
    print(f"subset: {summary.subset}")
    print(f"trials: {summary.trials}")
    print(f"passed: {summary.passed_count}/{summary.case_count}")
    print(f"pass_rate: {summary.pass_rate:.4f}")
    print(f"pass^1: {summary.metrics['pass_1']:.4f}")
    print(f"pass^k: {summary.metrics['pass_k']:.4f}")
    print(f"db_accuracy: {summary.metrics['db_accuracy']:.4f}")
    print(
        f"tool_call_success_rate: "
        f"{summary.metrics['tool_call_success_rate']:.4f}"
    )
    print(f"mutation_error_rate: {summary.metrics['mutation_error_rate']:.4f}")
    labels = summary.failure_analysis["failure_label_counts"]
    if labels:
        print("failure_labels:")
        for label, count in labels.items():
            print(f"  {label}: {count}")
    for result in summary.results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.case_id}: {result.failure_label or 'ok'}")
    print(f"artifact: {summary.result_artifact_path}")
    print(f"report: {summary.report_artifact_path}")


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
