from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from app.config import resolve_config
from app.eval.runner import DEFAULT_EVAL_ARTIFACT_DIR, CuratedEvalRunner


def flywheel_main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    try:
        from app.eval.flywheel import build_flywheel, check, collect, generate, promote

        if args.command == "collect":
            return _run_collect(args, build_flywheel=build_flywheel, collect=collect)
        if args.command == "generate":
            return _run_generate(args, generate=generate)
        if args.command == "golden":
            return _run_golden_promote(
                args,
                build_flywheel=build_flywheel,
                promote=promote,
            )
        if args.command == "check":
            return _run_check(args, check=check)
        parser.error("a subcommand is required")
    except Exception as exc:
        print(f"flywheel failed: {exc}", file=sys.stderr)
        return 1
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Flywheel evaluation utilities.")
    subparsers = parser.add_subparsers(dest="command")

    collect_parser = subparsers.add_parser(
        "collect",
        help="Collect failing cases from an eval report.",
    )
    collect_parser.add_argument("--report", required=True, help="Path to eval report JSON.")
    collect_parser.add_argument("--subset", required=True, help="Subset name for case lookup.")
    collect_parser.add_argument("--date", help="Recorded date in YYYY-MM-DD format.")
    collect_parser.add_argument(
        "--golden-path",
        default="cases/golden.yaml",
        help="Path to the golden set YAML file.",
    )
    collect_parser.add_argument(
        "--bad-cases-path",
        default="cases/bad_cases",
        help="Path to the bad case store directory.",
    )

    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate golden candidate variants from a bad case YAML.",
    )
    generate_parser.add_argument(
        "--input",
        required=True,
        help="Path to a dated bad-case YAML file.",
    )

    golden_parser = subparsers.add_parser("golden", help="Golden set operations.")
    golden_subparsers = golden_parser.add_subparsers(dest="golden_command")
    promote_parser = golden_subparsers.add_parser(
        "promote",
        help="Promote a bad case into the golden set.",
    )
    promote_parser.add_argument(
        "--input",
        required=True,
        help="Path to a dated bad-case YAML file.",
    )
    promote_parser.add_argument("--case-id", required=True, help="Bad case id to promote.")
    promote_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm promotion.",
    )
    promote_parser.add_argument(
        "--golden-path",
        default="cases/golden.yaml",
        help="Path to the golden set YAML file.",
    )
    promote_parser.add_argument(
        "--bad-cases-path",
        default="cases/bad_cases",
        help="Path to the bad case store directory.",
    )

    check_parser = subparsers.add_parser("check", help="Run the golden flywheel check.")
    check_parser.add_argument(
        "--artifact-dir",
        default=os.getenv("EVAL_ARTIFACT_DIR", str(DEFAULT_EVAL_ARTIFACT_DIR)),
    )
    check_parser.add_argument("--tau3-retail-root", help="Override TAU3_RETAIL_ROOT.")
    check_parser.add_argument("--tau2-bench-root", help="Override TAU2_BENCH_ROOT.")
    check_parser.add_argument("--require-llm", action="store_true")
    check_parser.add_argument("--live", action="store_true", help="Use real LLM provider for eval.")
    check_parser.add_argument("--max-workers", type=int, default=50)
    check_parser.add_argument(
        "--seed", type=int, default=42, help="Seed for synthetic world generation."
    )
    check_parser.add_argument("--json", action="store_true")
    check_parser.add_argument("--no-progress", action="store_true")
    return parser


def _run_collect(args: argparse.Namespace, *, build_flywheel, collect) -> int:
    recorded_on = date.fromisoformat(args.date) if args.date else None
    flywheel = build_flywheel(
        golden_path=Path(args.golden_path).expanduser(),
        bad_cases_path=Path(args.bad_cases_path).expanduser(),
    )
    result = collect(
        flywheel=flywheel,
        report_path=Path(args.report).expanduser(),
        subset=args.subset,
        recorded_on=recorded_on,
    )
    print(f"subset: {result.subset}")
    print(f"failed_results: {result.failed_results}")
    print(f"collected_count: {result.collected_count}")
    print(f"deduped_count: {result.deduped_count}")
    print(f"output: {result.output_path}")
    if result.case_ids:
        print(json.dumps({"case_ids": result.case_ids}, indent=2, sort_keys=True))
    return 0


def _run_generate(args: argparse.Namespace, *, generate) -> int:
    result = generate(bad_cases_path=Path(args.input).expanduser())
    print(f"input_count: {result.input_count}")
    print(f"generated_count: {result.generated_count}")
    print(f"output: {result.output_path}")
    if result.skipped_case_ids:
        print(
            json.dumps(
                {"skipped_case_ids": result.skipped_case_ids},
                indent=2,
                sort_keys=True,
            )
        )
    return 0


def _run_golden_promote(args: argparse.Namespace, *, build_flywheel, promote) -> int:
    if args.golden_command != "promote":
        raise ValueError("golden subcommand is required")
    flywheel = build_flywheel(
        golden_path=Path(args.golden_path).expanduser(),
        bad_cases_path=Path(args.bad_cases_path).expanduser(),
    )
    result = promote(
        flywheel=flywheel,
        bad_cases_path=Path(args.input).expanduser(),
        case_id=args.case_id,
        confirmed=args.confirm,
    )
    print(f"case_id: {result.case_id}")
    print(f"added_to_golden: {result.added_to_golden}")
    print(f"already_in_golden: {result.already_in_golden}")
    print(f"record_marked_promoted: {result.record_marked_promoted}")
    return 0


def _run_check(args: argparse.Namespace, *, check) -> int:
    config = resolve_config(
        tau3_retail_root=args.tau3_retail_root,
        tau2_bench_root=args.tau2_bench_root,
        artifact_dir=args.artifact_dir,
    )
    runner = CuratedEvalRunner(
        config=config,
        artifact_dir=Path(args.artifact_dir).expanduser(),
        require_llm=args.require_llm,
        live=args.live,
        progress_callback=None if args.no_progress else _print_progress,
    )
    result = check(
        run_golden=lambda: runner.run(
            subset="golden",
            max_workers=args.max_workers,
            seed=args.seed,
        )
    )
    if args.json:
        print(
            json.dumps(
                {
                    "has_regressions": result.has_regressions,
                    "exit_code": result.exit_code,
                    "statuses": [status.__dict__ for status in result.statuses],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(f"has_regressions: {result.has_regressions}")
        for status in result.statuses:
            print(
                f"[{status.status}] {status.case_id}: "
                f"{status.failure_label or ('pass' if status.passed else 'n/a')}"
            )
    return result.exit_code


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
    raise SystemExit(flywheel_main())
