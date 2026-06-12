from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from app.agent.models import ConversationState
from app.agent.prompts import prompt_metadata
from app.agent.runtime import AgentRuntime
from app.config import resolve_config
from app.ops.tracing import TraceWriter


def chat_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Phase 1 guarded agent.")
    parser.add_argument("--script", help="Path to a scripted conversation JSON file.")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run an interactive CLI session.",
    )
    parser.add_argument("--artifact-dir", help="Override AGENT_ARTIFACT_DIR.")
    parser.add_argument("--tau3-retail-root", help="Override TAU3_RETAIL_ROOT.")
    parser.add_argument("--tau2-bench-root", help="Override TAU2_BENCH_ROOT.")
    parser.add_argument("--json", action="store_true", help="Print JSON run output.")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument(
        "--require-llm",
        action="store_true",
        help="Fail if DEEPSEEK_API_KEY or OpenAI-compatible dependencies are missing.",
    )
    args = parser.parse_args(argv)

    if not args.script and not args.interactive:
        parser.error("provide --script or --interactive")
    if args.script and args.interactive:
        parser.error("--script and --interactive are mutually exclusive")

    config = resolve_config(
        tau3_retail_root=args.tau3_retail_root,
        tau2_bench_root=args.tau2_bench_root,
        artifact_dir=args.artifact_dir,
    )
    try:
        runtime = AgentRuntime(config, require_llm=args.require_llm)
    except ValueError as exc:
        print(f"phase1-chat failed: {exc}", file=sys.stderr)
        return 1

    if args.script:
        payload = _read_script(Path(args.script).expanduser())
        result = runtime.run_script(
            messages=payload["messages"],
            session_id=payload.get("session_id"),
            task_id=payload.get("task_id"),
            max_turns=int(payload.get("max_turns", args.max_turns)),
        )
        if args.json:
            print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        else:
            _print_transcript(result.state.messages)
            print(f"trace: {result.trace_artifact_path}")
        return 0

    return _interactive(runtime, args.max_turns, args.json)


def _read_script(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except FileNotFoundError as exc:
        raise SystemExit(f"script not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"script is not valid JSON: {path}: {exc}") from exc
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise SystemExit("script must contain a messages list")
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            raise SystemExit("Phase 1 scripts must contain user messages only")
    return payload


def _interactive(runtime: AgentRuntime, max_turns: int, json_output: bool) -> int:
    session_id = "interactive"
    state = ConversationState(session_id=session_id)
    initial_db_hash = runtime.retail_runtime.db_hash()
    print("Phase 1 interactive session. Type 'exit' to finish.", file=sys.stderr)
    for _ in range(max_turns):
        try:
            content = input("user> ").strip()
        except EOFError:
            break
        if content.lower() in {"exit", "quit"}:
            break
        if content:
            reply = runtime.handle_user_message(state, content)
            print(f"assistant> {reply}")
    state.termination_reason = "interactive_completed"
    trace_path = TraceWriter(runtime.config.run_artifact_dir).write(
        run_id=session_id,
        state=state,
        metadata={
            "runtime_source": runtime.retail_runtime.source,
            "model": runtime.config.default_agent_model,
            "llm_enabled": runtime.provider is not None,
            "initial_db_hash": initial_db_hash,
            "final_db_hash": runtime.retail_runtime.db_hash(),
            "tau2_bench_root": str(runtime.config.tau2_bench_root),
            "tau3_retail_root": str(runtime.config.tau3_retail_root),
            "retail_db_path": str(runtime.config.retail_db_path),
            "prompts": prompt_metadata(),
        },
    )
    output = {
        "run_id": session_id,
        "termination_reason": state.termination_reason,
        "final_state": state.model_dump(),
        "trace_artifact_path": str(trace_path),
    }
    if json_output:
        print(json.dumps(output, indent=2, sort_keys=True, default=str))
    else:
        print(f"trace: {trace_path}")
    return 0


def _print_transcript(messages: Any) -> None:
    for message in messages:
        if message.role in {"user", "assistant"}:
            print(f"{message.role}: {message.content}")


if __name__ == "__main__":
    raise SystemExit(chat_main())
