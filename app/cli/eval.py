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
    argv = list(argv) if argv is not None else sys.argv[1:]
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("BASELINE_JSON", "CANDIDATE_JSON"),
        help="Compare two Phase 2 summary or report JSON artifacts.",
    )
    parser.add_argument("--subset")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument(
        "--artifact-dir",
        default=os.getenv("EVAL_ARTIFACT_DIR", str(DEFAULT_EVAL_ARTIFACT_DIR)),
    )
    parser.add_argument("--tau3-retail-root", help="Override TAU3_RETAIL_ROOT.")
    parser.add_argument("--tau2-bench-root", help="Override TAU2_BENCH_ROOT.")
    parser.add_argument("--require-llm", action="store_true")
    parser.add_argument("--live", action="store_true", help="Use real LLM provider for eval.")
    parser.add_argument("--replay", help="Replay a whole trace directory.")
    parser.add_argument("--replay-case", help="Replay a single trace JSON file.")
    parser.add_argument("--max-workers", type=int, default=50)
    parser.add_argument(
        "--seed", type=int, default=42, help="Seed for synthetic world generation."
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args(argv)
    subset_provided = any(
        token == "--subset" or token.startswith("--subset=") for token in argv
    )

    if args.compare:
        return _compare(
            args.compare,
            json_output=args.json,
            artifact_dir=Path(args.artifact_dir).expanduser(),
        )

    if args.trials < 1:
        parser.error("--trials must be >= 1")
    if args.replay and args.replay_case:
        parser.error("--replay and --replay-case are mutually exclusive")
    if args.live and (args.replay or args.replay_case):
        parser.error("replay mode cannot be combined with --live")
    if args.replay and not subset_provided:
        parser.error("--replay requires --subset")

    subset = args.subset if args.subset is not None else "curated_mvp"

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
            live=args.live,
            progress_callback=None if args.no_progress else _print_progress,
            replay_trace_dir=Path(args.replay).expanduser() if args.replay else None,
            replay_case_path=(
                Path(args.replay_case).expanduser() if args.replay_case else None
            ),
        ).run(
            subset=None if args.replay_case else subset,
            trials=args.trials,
            max_workers=args.max_workers,
            seed=args.seed,
        )
    except Exception as exc:
        print(f"phase2-eval failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary.as_dict(), indent=2, sort_keys=True))
    else:
        _print_summary(summary)
    return 0 if summary.passed_count == summary.case_count else 1


def _compare(paths: list[str], *, json_output: bool, artifact_dir: Path) -> int:
    try:
        baseline_path = Path(paths[0]).expanduser()
        candidate_path = Path(paths[1]).expanduser()
        baseline = _read_json_artifact(baseline_path)
        candidate = _read_json_artifact(candidate_path)
        comparison = build_comparison_artifact(
            baseline=baseline,
            candidate=candidate,
        )
        if comparison.get("case_deltas", {}).get("overlap_case_count", 0) == 0:
            raise ValueError("No overlapping case ids found between comparison artifacts")
        comparison_path = _write_comparison_artifact(
            baseline_path=baseline_path,
            candidate_path=candidate_path,
            baseline=baseline,
            candidate=candidate,
            comparison=comparison,
            artifact_dir=artifact_dir,
        )
    except Exception as exc:
        print(f"phase2-eval failed: {exc}", file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps(comparison, indent=2, sort_keys=True))
        return 0
    _print_comparison(comparison, comparison_path=comparison_path)
    return 0


def _read_json_artifact(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _print_comparison(comparison: dict, *, comparison_path: Path) -> None:
    print("Phase 2 eval comparison")
    print(f"baseline: {comparison['baseline_eval_run_id']}")
    print(f"candidate: {comparison['candidate_eval_run_id']}")
    case_deltas = comparison.get("case_deltas", {})
    print(f"overlap cases: {case_deltas.get('overlap_case_count', 0)}")
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
    for section_name in (
        "new_failures",
        "fixed",
        "still_failing",
        "failure_label_changed",
    ):
        entries = case_deltas.get(section_name, [])
        if not entries:
            continue
        print(f"{section_name}:")
        for entry in entries:
            print(
                f"  - {entry['case_id']}: "
                f"baseline={entry.get('baseline_failure_label')!r} "
                f"candidate={entry.get('candidate_failure_label')!r}"
            )
            if entry.get("baseline_trace_artifact_path"):
                print(f"    baseline_trace: {entry['baseline_trace_artifact_path']}")
            if entry.get("candidate_trace_artifact_path"):
                print(
                    f"    candidate_trace: {entry['candidate_trace_artifact_path']}"
                )
            if entry.get("baseline_report_artifact_path"):
                print(
                    f"    baseline_report: {entry['baseline_report_artifact_path']}"
                )
            if entry.get("candidate_report_artifact_path"):
                print(
                    f"    candidate_report: {entry['candidate_report_artifact_path']}"
                )
    print(f"comparison artifact: {comparison_path}")


def _write_comparison_artifact(
    *,
    baseline_path: Path,
    candidate_path: Path,
    baseline: dict,
    candidate: dict,
    comparison: dict,
    artifact_dir: Path,
) -> Path:
    comparison_dir = _comparison_artifact_dir(
        baseline_path=baseline_path,
        candidate_path=candidate_path,
        baseline=baseline,
        candidate=candidate,
        artifact_dir=artifact_dir,
    )
    comparison_dir.mkdir(parents=True, exist_ok=True)
    baseline_run_id = comparison.get("baseline_eval_run_id") or "baseline"
    candidate_run_id = comparison.get("candidate_eval_run_id") or "candidate"
    comparison_path = comparison_dir / f"{baseline_run_id}__vs__{candidate_run_id}.json"
    comparison_path.write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return comparison_path


def _comparison_artifact_dir(
    *,
    baseline_path: Path,
    candidate_path: Path,
    baseline: dict,
    candidate: dict,
    artifact_dir: Path,
) -> Path:
    for source_path in (
        Path(baseline.get("report_artifact_path")).expanduser()
        if baseline.get("report_artifact_path")
        else baseline_path,
        Path(candidate.get("report_artifact_path")).expanduser()
        if candidate.get("report_artifact_path")
        else candidate_path,
    ):
        if source_path.parent.name == "reports":
            return source_path.parent.parent / "comparisons"
    return artifact_dir / "comparisons"


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
    print(f"tool_call_success_rate: {summary.metrics['tool_call_success_rate']:.4f}")
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
