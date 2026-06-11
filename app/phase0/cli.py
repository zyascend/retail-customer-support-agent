from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from app.phase0.checks import Phase0CheckError, run_environment_check
from app.phase0.config import resolve_config
from app.phase0.results import ResultParseError, summarize_result, write_summary


def check_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 0 local inputs.")
    _add_common_args(parser)
    parser.add_argument("--expected-task-count", type=int, default=114)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args(argv)

    config = resolve_config(args.tau2_bench_root, args.tau2_data_dir, args.artifact_dir)
    try:
        result = run_environment_check(config, args.expected_task_count)
    except Phase0CheckError as exc:
        print(f"phase0-check failed: {exc}", file=sys.stderr)
        return 1

    output = result.as_dict()
    _write_json_artifact(output, config.artifact_dir / "phase0_check.json")
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        _print_check(output)
    return 0 if result.ok else 1


def report_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize a tau2 results.json file.")
    _add_common_args(parser)
    parser.add_argument("--result", required=True, help="Path to tau2 results JSON.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args(argv)

    config = resolve_config(args.tau2_bench_root, args.tau2_data_dir, args.artifact_dir)
    try:
        summary = summarize_result(Path(args.result).expanduser())
    except ResultParseError as exc:
        print(f"phase0-report failed: {exc}", file=sys.stderr)
        return 1

    artifact_path = write_summary(summary, config.artifact_dir)
    output = summary.as_dict()
    output["artifact_path"] = str(artifact_path)
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        _print_report(output)
    return 0


def smoke_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run an optional tau2 live smoke test.")
    _add_common_args(parser)
    parser.add_argument("--domain", default="retail")
    parser.add_argument("--num-tasks", type=int, default=1)
    parser.add_argument("--num-trials", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--require-run",
        action="store_true",
        help="Exit non-zero instead of skipping when live requirements are missing.",
    )
    args = parser.parse_args(argv)

    config = resolve_config(args.tau2_bench_root, args.tau2_data_dir, args.artifact_dir)
    skip_reason = _live_skip_reason(config)
    if skip_reason:
        print(f"phase0-smoke skipped: {skip_reason}")
        return 1 if args.require_run else 0

    sys.path.insert(0, str(config.tau2_src_dir))
    os.environ.setdefault("TAU2_DATA_DIR", str(config.tau2_runtime_data_dir))
    agent_model = os.getenv("AGENT_LLM_MODEL", "deepseek/deepseek-chat")
    user_model = os.getenv("USER_LLM_MODEL", agent_model)

    try:
        from tau2 import TextRunConfig
        from tau2.metrics.agent_metrics import compute_metrics
        from tau2.runner import run_domain
    except Exception as exc:
        print(f"phase0-smoke skipped: could not import tau2 dependencies: {exc}")
        return 1 if args.require_run else 0

    try:
        results = run_domain(
            TextRunConfig(
                domain=args.domain,
                agent="llm_agent",
                llm_agent=agent_model,
                llm_user=user_model,
                num_tasks=args.num_tasks,
                num_trials=args.num_trials,
                max_concurrency=1,
                seed=args.seed,
            )
        )
        metrics = compute_metrics(results)
    except Exception as exc:
        print(f"phase0-smoke failed: {exc}", file=sys.stderr)
        return 1

    print("phase0-smoke completed")
    print(f"domain: {args.domain}")
    print(f"num_tasks: {args.num_tasks}")
    print(f"num_trials: {args.num_trials}")
    print(f"avg_reward: {metrics.avg_reward:.4f}")
    print(f"avg_agent_cost: {metrics.avg_agent_cost:.6f}")
    for k, value in sorted(metrics.pass_hat_ks.items()):
        print(f"pass_hat_{k}: {value:.4f}")
    return 0


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tau2-bench-root", help="Override TAU2_BENCH_ROOT.")
    parser.add_argument("--tau2-data-dir", help="Override TAU2_DATA_DIR.")
    parser.add_argument("--artifact-dir", help="Override artifact output directory.")


def _write_json_artifact(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, sort_keys=True)
        file.write("\n")


def _print_check(output: Dict[str, Any]) -> None:
    print(f"Phase 0 environment: {'OK' if output['ok'] else 'FAILED'}")
    for message in output["messages"]:
        status = message["status"].upper()
        print(f"[{status}] {message['name']}: {message['detail']}")
    print("artifact: artifacts/phase0/phase0_check.json")


def _print_report(output: Dict[str, Any]) -> None:
    print("Phase 0 result summary")
    print(f"result: {output['result_path']}")
    print(f"tasks: {output['task_count']}")
    print(f"simulations: {output['simulation_count']}")
    print(f"trials: {output['trial_count']}")
    print(f"avg_reward: {output['average_reward']:.4f}")
    print(f"pass_rate: {output['pass_rate']:.4f}")
    for name, value in sorted(output["pass_hat_ks"].items()):
        print(f"{name}: {value:.4f}")
    print(f"avg_agent_cost: {_format_optional(output['average_agent_cost'])}")
    print(f"avg_user_cost: {_format_optional(output['average_user_cost'])}")
    print(f"avg_total_cost: {_format_optional(output['average_total_cost'])}")
    print(f"avg_duration_seconds: {_format_optional(output['average_duration_seconds'])}")
    print(f"infra_errors: {output['infra_error_count']}")
    print(f"termination_counts: {output['termination_counts']}")
    print(f"reward_basis_counts: {output['reward_basis_counts']}")
    print(f"artifact: {output['artifact_path']}")


def _format_optional(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6f}"


def _live_skip_reason(config: Any) -> Optional[str]:
    if not config.tau2_src_dir.exists():
        return f"tau2 source directory not found: {config.tau2_src_dir}"
    if not config.retail_domain_dir.exists():
        return f"retail data directory not found: {config.retail_domain_dir}"
    api_keys = (
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
    )
    if not any(os.getenv(key) for key in api_keys):
        return "no provider API key is configured"
    return None


if __name__ == "__main__":
    raise SystemExit(check_main())
