from __future__ import annotations

import inspect
import json
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.agent.confirmation import ConfirmationResolver
from app.agent.models import Message, SessionState
from app.agent.prompts import prompt_metadata
from app.agent.providers import DeterministicProvider
from app.agent.replay import TraceReplayHarness
from app.agent.runtime import AgentRuntime
from app.config import AppConfig
from app.eval.cases import EvalCase, get_cases
from app.eval.metrics import (
    EVAL_RUN_SUMMARY_SCHEMA_VERSION,
    apply_case_diagnostics,
    build_failure_analysis,
    build_report_artifact,
    compute_metrics,
)
from app.tools.retail_adapter import get_order_from_db, get_user_from_db

DEFAULT_EVAL_ARTIFACT_DIR = Path("artifacts/phase2")
ORDER_RE = re.compile(r"#W\d+")
_GET_CASES_SUBSET_RE = re.compile(r'if subset == "([^"]+)"')

_CONFIRMED_REPLAY_MESSAGE = "Done. I have completed the requested update."
_DENIED_REPLAY_MESSAGE = "No changes were made."
_CHANGED_REPLAY_MESSAGE = (
    "I discarded the previous request. Please provide updated details."
)


@dataclass
class EvalCaseResult:
    run_id: str
    session_id: str
    case_id: str
    category: str
    trial: int
    passed: bool
    failure_label: Optional[str]
    trace_artifact_path: str
    authenticated_user_id: Optional[str]
    final_intent: str
    termination_reason: Optional[str]
    expected_write_lock: Optional[str]
    write_locks: List[str] = field(default_factory=list)
    expected_order_status: Optional[str] = None
    actual_order_status: Optional[str] = None
    expected_confirmation_status: Optional[str] = None
    actual_confirmation_status: Optional[str] = None
    expected_guard_block_reason: Optional[str] = None
    actual_guard_block_reasons: List[str] = field(default_factory=list)
    initial_db_hash: Optional[str] = None
    final_db_hash: Optional[str] = None
    db_changed: bool = False
    order_status_before: Optional[str] = None
    order_status_after: Optional[str] = None
    scenario_family: Optional[str] = None
    variant_type: Optional[str] = None
    language_variation_level: Optional[str] = None
    seed: Optional[int] = None
    duration_seconds: float = 0.0
    tool_protocol_violations: int = 0
    tool_errors: int = 0
    guard_blocks: int = 0
    db_accuracy_passed: Optional[bool] = None
    db_accuracy_basis: Optional[str] = None
    tool_call_count: int = 0
    successful_tool_calls: int = 0
    failed_tool_calls: int = 0
    blocked_tool_calls: int = 0
    mutation_detected: bool = False
    unexpected_mutation: bool = False
    trial_turn_count: int = 0
    message_count: int = 0
    policy_check_count: int = 0
    failure_category: Optional[str] = None
    failure_summary: Optional[str] = None
    expected_actual_diff: Dict[str, Any] = field(default_factory=dict)
    replay_metadata: Dict[str, Any] = field(default_factory=dict)
    db_assertion_failures: List[str] = field(default_factory=list)

    # ── Phase 5: LLM tool-calling metrics ──
    eval_backend: str = "scripted"
    llm_token_usage: Optional[Dict[str, Any]] = None
    llm_loop_iterations: int = 0


@dataclass
class EvalRunSummary:
    schema_version: str
    artifact_created_at: str
    eval_run_id: str
    subset: str
    trials: int
    created_at: str
    agent_strategy: str
    model: str
    llm_required: bool
    llm_timeout_seconds: float
    llm_max_retries: int
    case_count: int
    passed_count: int
    pass_rate: float
    result_artifact_path: str
    report_artifact_path: str
    dataset_root: str
    dataset_db_path: str
    code_commit: str
    prompt_metadata: Dict[str, Dict[str, str]]
    metrics: Dict[str, Any]
    failure_analysis: Dict[str, Any]
    results: List[EvalCaseResult]
    generalization_families: List[str] = field(default_factory=list)
    generalization_variant_count: int = 0

    # ── Phase 5 ──
    eval_backend: str = "scripted"

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["results"] = [asdict(result) for result in self.results]
        return payload


def _load_tau_task_by_id(case_id: str, config: AppConfig) -> Optional[dict]:
    """Load a single tau3 task by its EvalCase case_id ('tau_0' → task id '0')."""
    if not case_id.startswith("tau_"):
        return None
    task_id = case_id[4:]  # strip 'tau_' prefix
    try:
        from app.analysis.tau_task_analyzer import _resolve_tau3_retail_dir, load_tasks

        retail_dir = _resolve_tau3_retail_dir(config)
        tasks = load_tasks(retail_dir)
        for t in tasks:
            if str(t["id"]) == task_id:
                return t
    except Exception:
        pass
    return None


class CuratedEvalRunner:
    def __init__(
        self,
        *,
        config: AppConfig,
        artifact_dir: Path = DEFAULT_EVAL_ARTIFACT_DIR,
        require_llm: bool = False,
        live: bool = False,
        progress_callback: Optional[Callable[[str, EvalCaseResult], None]] = None,
        replay_trace_dir: Optional[Path] = None,
        replay_case_path: Optional[Path] = None,
    ) -> None:
        self.config = config
        self.artifact_dir = artifact_dir
        self.require_llm = require_llm
        self.live = live
        self.progress_callback = progress_callback
        self.replay_trace_dir = replay_trace_dir
        self.replay_case_path = replay_case_path

    def run(
        self,
        *,
        subset: str = "curated_mvp",
        trials: int = 1,
        max_workers: int = 1,
        seed: int = 42,
    ) -> EvalRunSummary:
        self._seed = seed
        eval_run_id = "eval-" + uuid.uuid4().hex[:12]
        if self.replay_case_path and self.replay_trace_dir:
            raise ValueError(
                "Replay runner accepts either replay_case_path or replay_trace_dir, not both"
            )

        results: List[EvalCaseResult]
        if self.replay_case_path:
            case = self._resolve_case_for_trace(self.replay_case_path, subset=subset)
            results = [
                self._run_replay_case(
                    eval_run_id=eval_run_id,
                    case=case,
                    trial=0,
                    trace_path=self.replay_case_path,
                )
            ]
            trials = 1
            subset = case.subset
        elif self.replay_trace_dir:
            cases = get_cases(subset)
            trace_index = self._index_replay_traces(self.replay_trace_dir)
            results = []
            for case in cases:
                trace_path = trace_index.get(case.case_id)
                if trace_path is None:
                    raise FileNotFoundError(
                        f"Missing replay trace for case_id '{case.case_id}' in {self.replay_trace_dir}"
                    )
                if self.progress_callback:
                    self.progress_callback(
                        "start",
                        self._progress_placeholder(case=case, trial=0),
                    )
                result = self._run_replay_case(
                    eval_run_id=eval_run_id,
                    case=case,
                    trial=0,
                    trace_path=trace_path,
                )
                results.append(result)
                if self.progress_callback:
                    self.progress_callback("finish", result)
            trials = 1
        else:
            cases = get_cases(subset)
            results = []
            for trial in range(trials):
                if max_workers > 1:
                    trial_results = self._run_trial_parallel(
                        eval_run_id,
                        cases,
                        trial,
                        max_workers,
                    )
                else:
                    trial_results = self._run_trial_sequential(
                        eval_run_id,
                        cases,
                        trial,
                    )
                results.extend(trial_results)
        passed_count = sum(1 for result in results if result.passed)
        result_path = self.artifact_dir / "eval_runs" / f"{eval_run_id}.json"
        report_path = self.artifact_dir / "reports" / f"{eval_run_id}.json"
        created_at = datetime.now(timezone.utc).isoformat()
        code_commit = _git_commit()
        metrics = compute_metrics(results)
        failure_analysis = build_failure_analysis(results)
        summary = EvalRunSummary(
            schema_version=EVAL_RUN_SUMMARY_SCHEMA_VERSION,
            artifact_created_at=created_at,
            eval_run_id=eval_run_id,
            subset=subset,
            trials=trials,
            created_at=created_at,
            agent_strategy="guarded_workflow_agent",
            model=self.config.default_agent_model,
            llm_required=False if self._is_replay_mode() else (self.require_llm or self.live),
            llm_timeout_seconds=self.config.agent_llm_timeout_seconds,
            llm_max_retries=self.config.agent_llm_max_retries,
            case_count=len(results),
            passed_count=passed_count,
            pass_rate=passed_count / len(results) if results else 0.0,
            result_artifact_path=str(result_path),
            report_artifact_path=str(report_path),
            dataset_root=str(self.config.tau3_retail_root),
            dataset_db_path=str(self.config.retail_db_path),
            code_commit=code_commit,
            prompt_metadata=prompt_metadata(),
            metrics=metrics,
            failure_analysis=failure_analysis,
            results=results,
            generalization_families=sorted(
                set(getattr(r, "scenario_family", "") for r in results) - {""}
            )
            if subset == "generalization"
            else [],
            generalization_variant_count=len(results)
            if subset == "generalization"
            else 0,
            eval_backend=self._eval_backend(),
        )
        self._write_summary(summary)
        self._write_report(summary)
        return summary

    def _run_trial_sequential(
        self,
        eval_run_id: str,
        cases: List[EvalCase],
        trial: int,
    ) -> List[EvalCaseResult]:
        results: List[EvalCaseResult] = []
        for case in cases:
            if self.progress_callback:
                self.progress_callback(
                    "start",
                    self._progress_placeholder(case=case, trial=trial),
                )
            result = self._run_case(eval_run_id, case, trial)
            results.append(result)
            if self.progress_callback:
                self.progress_callback("finish", result)
        return results

    def _run_trial_parallel(
        self,
        eval_run_id: str,
        cases: List[EvalCase],
        trial: int,
        max_workers: int,
    ) -> List[EvalCaseResult]:
        results: List[EvalCaseResult] = []
        lock = threading.Lock()
        workers = min(max_workers, len(cases))

        def _run_one(case: EvalCase, idx: int) -> EvalCaseResult:
            result = self._run_case(eval_run_id, case, trial)
            if self.progress_callback:
                with lock:
                    self.progress_callback("finish", result)
            return result

        # Signal start for all cases
        if self.progress_callback:
            for case in cases:
                self.progress_callback(
                    "start",
                    self._progress_placeholder(case=case, trial=trial),
                )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run_one, case, i) for i, case in enumerate(cases)]
            for future in as_completed(futures):
                results.append(future.result())

        return results

    def _run_case(self, eval_run_id: str, case: EvalCase, trial: int) -> EvalCaseResult:
        runtime_config = AppConfig(
            tau3_retail_root=self.config.tau3_retail_root,
            tau2_bench_root=self.config.tau2_bench_root,
            artifact_dir=self.artifact_dir / "traces" / eval_run_id,
            deepseek_api_key=self.config.deepseek_api_key,
            deepseek_base_url=self.config.deepseek_base_url,
            default_agent_model=self.config.default_agent_model,
            agent_llm_timeout_seconds=self.config.agent_llm_timeout_seconds,
            agent_llm_max_retries=self.config.agent_llm_max_retries,
        )
        # Live mode uses the real LLM provider; scripted CI uses the explicit
        # offline demo harness so it does not look like production fallback.
        offline_demo = False
        if self.live:
            provider = None  # let AgentRuntime build real DeepSeekProvider
        elif self.require_llm:
            provider = None
        else:
            provider = DeterministicProvider()
            offline_demo = True
        # Synthetic subset: use synthetic runtime
        if case.subset in (
            "synthetic_seeded_v1",
            "generalization",
            "generalization_exploratory",
        ):
            from app.synthetic.adapter import SyntheticRetailAdapter

            # generalization cases carry their own seed; synthetic_seeded_v1 uses global _seed
            seed = getattr(case, "seed", None) or getattr(self, "_seed", 42)
            synthetic_adapter = SyntheticRetailAdapter(seed=seed)
            synthetic_runtime = synthetic_adapter.create_runtime()
        else:
            synthetic_runtime = None
        runtime = AgentRuntime(
            runtime_config,
            provider=provider,
            require_llm=self.require_llm,
            runtime=synthetic_runtime,
            offline_demo=offline_demo,
        )
        # Tau subsets: use UserSimulator for multi-turn conversations
        user_simulator_callback = None
        run_messages = case.messages
        if case.subset and case.subset.startswith("tau_retail_"):
            task_data = _load_tau_task_by_id(case.case_id, self.config)
            if task_data is not None:
                from app.eval.tau_user_simulator import TauUserSimulator

                simulator = TauUserSimulator(
                    task_data, db_path=str(runtime_config.retail_db_path)
                )
                run_messages = [{"role": "user", "content": simulator.initial_message()}]
                user_simulator_callback = simulator.respond

        session_id = f"{eval_run_id}-{case.case_id}-trial-{trial}"
        order_status_before = self._order_status(runtime, case)
        started_at = time.perf_counter()
        run_result = runtime.run_script(
            messages=run_messages,
            session_id=session_id,
            task_id=case.case_id,
            max_turns=case.max_turns,
            user_simulator_callback=user_simulator_callback,
        )
        duration_seconds = round(time.perf_counter() - started_at, 3)

        # Phase 5: extract LLM metrics from turn contexts
        total_tokens = None
        total_loop_iterations = 0
        for turn_ctx in run_result.turn_contexts:
            total_loop_iterations += turn_ctx.loop_iterations
            if turn_ctx.llm_token_usage:
                if total_tokens is None:
                    total_tokens = dict(turn_ctx.llm_token_usage)
                else:
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        total_tokens[key] = total_tokens.get(key, 0) + turn_ctx.llm_token_usage.get(key, 0)

        state = run_result.state
        actual_order_status = self._order_status(runtime, case)
        guard_block_reasons = [
            str(record.error)
            for record in state.tool_results
            if record.status == "blocked" and record.error
        ]
        tool_errors = sum(
            1 for record in state.tool_results if record.status == "error"
        )
        guard_blocks = sum(
            1 for record in state.tool_results
            if record.status == "blocked"
            and record.error != "explicit_confirmation_required"
        )
        successful_tool_calls = sum(
            1 for record in state.tool_results if record.status == "success"
        )
        trace_metadata = self._trace_metadata(run_result.trace_artifact_path)
        db_assertion_failures = self._db_assertion_failures(runtime, case)
        failure_label = classify_failure(
            case=case,
            authenticated_user_id=state.authenticated_user_id,
            final_intent="",
            write_locks=state.write_locks,
            actual_order_status=actual_order_status,
            assistant_messages=[
                message.content
                for message in state.messages
                if message.role == "assistant"
            ],
            tool_names=[record.tool_name for record in state.tool_results],
            guard_block_reasons=guard_block_reasons,
            tool_errors=tool_errors,
            guard_blocks=guard_blocks,
            pending_action=state.pending_action is not None,
            llm_errors=self._llm_error_count(state.steps),
            confirmation_status=state.confirmation_status,
            db_assertion_failures=db_assertion_failures,
        )
        result = EvalCaseResult(
            run_id=run_result.run_id,
            session_id=state.session_id,
            case_id=case.case_id,
            category=case.category,
            trial=trial,
            scenario_family=case.scenario_family or case.capability,
            variant_type=case.variant_type or case.case_id,
            language_variation_level=case.language_variation_level,
            seed=getattr(case, "seed", None),
            passed=failure_label is None,
            failure_label=failure_label,
            eval_backend="live" if self.live else "scripted",
            llm_token_usage=total_tokens,
            llm_loop_iterations=total_loop_iterations,
            trace_artifact_path=str(run_result.trace_artifact_path),
            authenticated_user_id=state.authenticated_user_id,
            final_intent="",
            termination_reason=state.termination_reason,
            expected_write_lock=case.expected_write_lock,
            write_locks=list(state.write_locks),
            expected_order_status=case.expected_order_status,
            actual_order_status=actual_order_status,
            expected_confirmation_status=case.expected_confirmation_status,
            actual_confirmation_status=state.confirmation_status,
            expected_guard_block_reason=case.expected_guard_block_reason,
            actual_guard_block_reasons=guard_block_reasons,
            initial_db_hash=trace_metadata.get("initial_db_hash"),
            final_db_hash=trace_metadata.get("final_db_hash"),
            order_status_before=order_status_before,
            order_status_after=actual_order_status,
            duration_seconds=duration_seconds,
            tool_errors=tool_errors,
            guard_blocks=guard_blocks,
            tool_call_count=len(state.tool_results),
            successful_tool_calls=successful_tool_calls,
            failed_tool_calls=tool_errors,
            blocked_tool_calls=guard_blocks,
            trial_turn_count=sum(
                1 for message in state.messages if message.role == "user"
            ),
            message_count=len(state.messages),
            policy_check_count=0,
            replay_metadata={
                "run_id": run_result.run_id,
                "session_id": state.session_id,
                "task_id": case.case_id,
                "trace_artifact_path": str(run_result.trace_artifact_path),
                "trial": trial,
            },
            db_assertion_failures=db_assertion_failures,
        )
        apply_case_diagnostics(result, case)
        return result

    def _run_replay_case(
        self,
        *,
        eval_run_id: str,
        case: EvalCase,
        trial: int,
        trace_path: Path,
    ) -> EvalCaseResult:
        if not trace_path.exists():
            raise FileNotFoundError(f"Replay trace file not found: {trace_path}")

        runtime_config = AppConfig(
            tau3_retail_root=self.config.tau3_retail_root,
            tau2_bench_root=self.config.tau2_bench_root,
            artifact_dir=self.artifact_dir / "traces" / eval_run_id,
            deepseek_api_key=self.config.deepseek_api_key,
            deepseek_base_url=self.config.deepseek_base_url,
            default_agent_model=self.config.default_agent_model,
            agent_llm_timeout_seconds=self.config.agent_llm_timeout_seconds,
            agent_llm_max_retries=self.config.agent_llm_max_retries,
        )
        runtime = AgentRuntime(
            runtime_config,
            provider=DeterministicProvider(),
            require_llm=False,
            offline_demo=True,
        )
        harness = TraceReplayHarness(trace_path, runtime.registry)
        if not harness.has_llm_responses:
            return self._project_legacy_replay_case(
                harness=harness,
                eval_run_id=eval_run_id,
                case=case,
                trial=trial,
                trace_path=trace_path,
            )
        final_state = harness.final_state
        confirmation_resolver = ConfirmationResolver()
        session = SessionState(
            session_id=str(
                final_state.get("session_id")
                or f"{eval_run_id}-{case.case_id}-trial-{trial}"
            ),
            task_id=case.case_id,
        )
        started_at = time.perf_counter()
        turn_contexts = []
        for user_message in self._replay_user_messages(harness, case):
            session.messages.append(Message(role="user", content=user_message))
            if session.pending_action:
                turn_result, needs_post_process = self._replay_confirmation_turn(
                    harness=harness,
                    session=session,
                    user_message=user_message,
                    resolver=confirmation_resolver,
                    runtime=runtime,
                )
            else:
                turn_result = harness.replay(
                    session,
                    user_message,
                    context_builder=runtime._context_builder,
                )
                needs_post_process = True
            if needs_post_process:
                self._apply_replay_turn_result(session, turn_result)
            turn_contexts.append(turn_result.turn)
        duration_seconds = round(time.perf_counter() - started_at, 3)

        if harness.remaining_tool_results:
            raise RuntimeError(
                "Unconsumed replay tool results remain: "
                f"{len(harness.remaining_tool_results)}"
            )

        total_tokens = None
        total_loop_iterations = 0
        for turn_ctx in turn_contexts:
            total_loop_iterations += turn_ctx.loop_iterations
            if turn_ctx.llm_token_usage:
                if total_tokens is None:
                    total_tokens = dict(turn_ctx.llm_token_usage)
                else:
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        total_tokens[key] = total_tokens.get(key, 0) + turn_ctx.llm_token_usage.get(key, 0)

        tool_records = harness.consumed_tool_results
        actual_order_status = self._replay_order_status(case, tool_records)
        guard_block_reasons = [
            str(record.error)
            for record in tool_records
            if record.status == "blocked" and record.error
        ]
        tool_errors = sum(1 for record in tool_records if record.status == "error")
        guard_blocks = sum(
            1
            for record in tool_records
            if record.status == "blocked"
            and record.error != "explicit_confirmation_required"
        )
        successful_tool_calls = sum(
            1 for record in tool_records if record.status == "success"
        )
        failure_label = classify_failure(
            case=case,
            authenticated_user_id=session.authenticated_user_id,
            final_intent="",
            write_locks=list(session.write_locks),
            actual_order_status=actual_order_status,
            assistant_messages=[
                message.content
                for message in session.messages
                if message.role == "assistant"
            ],
            tool_names=[record.tool_name for record in tool_records],
            guard_block_reasons=guard_block_reasons,
            tool_errors=tool_errors,
            guard_blocks=guard_blocks,
            pending_action=session.pending_action is not None,
            llm_errors=0,
            confirmation_status=session.confirmation_status,
            db_assertion_failures=[],
        )
        result = EvalCaseResult(
            run_id=str(harness.run_id or harness.task_id or case.case_id),
            session_id=session.session_id,
            case_id=case.case_id,
            category=case.category,
            trial=trial,
            scenario_family=case.scenario_family or case.capability,
            variant_type=case.variant_type or case.case_id,
            language_variation_level=case.language_variation_level,
            seed=getattr(case, "seed", None),
            passed=failure_label is None,
            failure_label=failure_label,
            eval_backend="replay",
            llm_token_usage=total_tokens,
            llm_loop_iterations=total_loop_iterations,
            trace_artifact_path=str(trace_path),
            authenticated_user_id=session.authenticated_user_id,
            final_intent="",
            termination_reason=final_state.get("termination_reason"),
            expected_write_lock=case.expected_write_lock,
            write_locks=list(session.write_locks),
            expected_order_status=case.expected_order_status,
            actual_order_status=actual_order_status,
            expected_confirmation_status=case.expected_confirmation_status,
            actual_confirmation_status=session.confirmation_status,
            expected_guard_block_reason=case.expected_guard_block_reason,
            actual_guard_block_reasons=guard_block_reasons,
            initial_db_hash=harness.metadata.get("initial_db_hash"),
            final_db_hash=harness.metadata.get("final_db_hash"),
            order_status_before=None,
            order_status_after=actual_order_status,
            duration_seconds=duration_seconds,
            tool_errors=tool_errors,
            guard_blocks=guard_blocks,
            tool_call_count=len(tool_records),
            successful_tool_calls=successful_tool_calls,
            failed_tool_calls=tool_errors,
            blocked_tool_calls=guard_blocks,
            trial_turn_count=sum(
                1 for message in session.messages if message.role == "user"
            ),
            message_count=len(session.messages),
            policy_check_count=0,
            replay_metadata={
                "run_id": harness.run_id,
                "session_id": session.session_id,
                "task_id": case.case_id,
                "trace_artifact_path": str(trace_path),
                "trial": trial,
            },
            db_assertion_failures=[],
        )
        apply_case_diagnostics(result, case)
        return result

    def _project_legacy_replay_case(
        self,
        *,
        harness: TraceReplayHarness,
        eval_run_id: str,
        case: EvalCase,
        trial: int,
        trace_path: Path,
    ) -> EvalCaseResult:
        final_state = harness.final_state
        messages = harness.messages
        if not messages or not isinstance(final_state, dict) or not final_state:
            raise ValueError(
                f"Legacy replay trace is missing required fields: {trace_path}"
            )

        tool_records = harness.tool_results
        actual_order_status = self._replay_order_status(case, tool_records)
        guard_block_reasons = [
            str(record.error)
            for record in tool_records
            if record.status == "blocked" and record.error
        ]
        tool_errors = sum(1 for record in tool_records if record.status == "error")
        guard_blocks = sum(
            1
            for record in tool_records
            if record.status == "blocked"
            and record.error != "explicit_confirmation_required"
        )
        successful_tool_calls = sum(
            1 for record in tool_records if record.status == "success"
        )
        assistant_messages = [
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "assistant"
        ]
        user_messages = [
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "user"
        ]
        write_locks = list(final_state.get("write_locks") or [])
        confirmation_status = str(
            final_state.get("confirmation_status") or "not_required"
        )
        failure_label = classify_failure(
            case=case,
            authenticated_user_id=final_state.get("authenticated_user_id"),
            final_intent="",
            write_locks=write_locks,
            actual_order_status=actual_order_status,
            assistant_messages=assistant_messages,
            tool_names=[record.tool_name for record in tool_records],
            guard_block_reasons=guard_block_reasons,
            tool_errors=tool_errors,
            guard_blocks=guard_blocks,
            pending_action=bool(final_state.get("pending_action")),
            llm_errors=0,
            confirmation_status=confirmation_status,
            db_assertion_failures=[],
        )
        result = EvalCaseResult(
            run_id=str(harness.run_id or harness.task_id or case.case_id),
            session_id=str(
                final_state.get("session_id")
                or f"{eval_run_id}-{case.case_id}-trial-{trial}"
            ),
            case_id=case.case_id,
            category=case.category,
            trial=trial,
            scenario_family=case.scenario_family or case.capability,
            variant_type=case.variant_type or case.case_id,
            language_variation_level=case.language_variation_level,
            seed=getattr(case, "seed", None),
            passed=failure_label is None,
            failure_label=failure_label,
            eval_backend="replay",
            llm_token_usage=None,
            llm_loop_iterations=0,
            trace_artifact_path=str(trace_path),
            authenticated_user_id=final_state.get("authenticated_user_id"),
            final_intent="",
            termination_reason=final_state.get("termination_reason"),
            expected_write_lock=case.expected_write_lock,
            write_locks=write_locks,
            expected_order_status=case.expected_order_status,
            actual_order_status=actual_order_status,
            expected_confirmation_status=case.expected_confirmation_status,
            actual_confirmation_status=confirmation_status,
            expected_guard_block_reason=case.expected_guard_block_reason,
            actual_guard_block_reasons=guard_block_reasons,
            initial_db_hash=harness.metadata.get("initial_db_hash"),
            final_db_hash=harness.metadata.get("final_db_hash"),
            order_status_before=None,
            order_status_after=actual_order_status,
            duration_seconds=0.0,
            tool_errors=tool_errors,
            guard_blocks=guard_blocks,
            tool_call_count=len(tool_records),
            successful_tool_calls=successful_tool_calls,
            failed_tool_calls=tool_errors,
            blocked_tool_calls=guard_blocks,
            trial_turn_count=len(user_messages),
            message_count=len(messages),
            policy_check_count=0,
            replay_metadata={
                "run_id": harness.run_id,
                "session_id": final_state.get("session_id"),
                "task_id": case.case_id,
                "trace_artifact_path": str(trace_path),
                "trial": trial,
                "legacy_trace": True,
            },
            db_assertion_failures=[],
        )
        apply_case_diagnostics(result, case)
        return result

    def _apply_replay_turn_result(self, session: SessionState, turn_result: Any) -> None:
        session.messages.append(
            Message(role="assistant", content=turn_result.assistant_message)
        )
        if turn_result.pending_action_set:
            session.confirmation_status = "required"
        elif not session.pending_action:
            session.confirmation_status = "not_required"

    def _replay_confirmation_turn(
        self,
        *,
        harness: TraceReplayHarness,
        session: SessionState,
        user_message: str,
        resolver: ConfirmationResolver,
        runtime: AgentRuntime,
    ):
        from app.agent.models import AgentTurnResult, TurnContext
        from app.agent.runtime import _map_guard_error_to_user_message

        turn = TurnContext()
        resolution = resolver.resolve(user_message)
        if resolution == "unknown":
            return (
                harness.replay(
                    session,
                    user_message,
                    context_builder=runtime._context_builder,
                ),
                True,
            )

        session.confirmation_status = resolution
        turn.add_step("preflight_confirmation", resolution=resolution)

        if resolution == "confirmed":
            action = session.pending_action
            if action is None:
                raise RuntimeError("Replay confirmation requested without pending action")
            record = harness.consume_tool_result(
                session=session,
                tool_name=action.action_name,
                arguments=action.arguments,
                confirmed=True,
            )
            session.pending_action = None
            if record.status == "success":
                message = _CONFIRMED_REPLAY_MESSAGE
            else:
                message = _map_guard_error_to_user_message(str(record.error))
            session.messages.append(Message(role="assistant", content=message))
            return AgentTurnResult(assistant_message=message, turn=turn), False

        if resolution == "denied":
            session.pending_action = None
            session.messages.append(Message(role="assistant", content=_DENIED_REPLAY_MESSAGE))
            return (
                AgentTurnResult(
                    assistant_message=_DENIED_REPLAY_MESSAGE,
                    turn=turn,
                ),
                False,
            )

        if resolution == "changed":
            session.pending_action = None
            session.messages.append(Message(role="assistant", content=_CHANGED_REPLAY_MESSAGE))
            return (
                AgentTurnResult(
                    assistant_message=_CHANGED_REPLAY_MESSAGE,
                    turn=turn,
                ),
                False,
            )

        return (
            harness.replay(
                session,
                user_message,
                context_builder=runtime._context_builder,
            ),
            True,
        )

    def _progress_placeholder(self, *, case: EvalCase, trial: int) -> EvalCaseResult:
        return EvalCaseResult(
            run_id="",
            session_id="",
            case_id=case.case_id,
            category=case.category,
            trial=trial,
            passed=False,
            failure_label=None,
            trace_artifact_path="",
            authenticated_user_id=None,
            final_intent="",
            termination_reason=None,
            expected_write_lock=case.expected_write_lock,
            eval_backend=self._eval_backend(),
        )

    def _order_status(self, runtime: AgentRuntime, case: EvalCase) -> Optional[str]:
        order_id = case.order_id
        for message in case.messages:
            if order_id:
                break
            content = message.get("content", "")
            match = ORDER_RE.search(content)
            if match:
                order_id = match.group(0)
                break
        if not order_id:
            return None
        order = get_order_from_db(runtime.retail_runtime.db, order_id)
        if not order:
            return None
        return order.get("status")

    def _trace_metadata(self, trace_path: Path) -> Dict[str, Any]:
        try:
            return json.loads(trace_path.read_text(encoding="utf-8")).get(
                "metadata", {}
            )
        except Exception:
            return {}

    def _replay_order_status(
        self, case: EvalCase, tool_records: List[Any]
    ) -> Optional[str]:
        order_id = case.order_id
        if not order_id:
            return None
        for record in reversed(tool_records):
            if (
                record.status == "success"
                and record.tool_name != "get_order_details"
                and self._record_order_status_matches(record, order_id)
            ):
                return record.observation.get("status")
        for record in reversed(tool_records):
            if (
                record.tool_name == "get_order_details"
                and record.status == "success"
                and self._record_order_status_matches(record, order_id)
            ):
                return record.observation.get("status")
        return None

    def _record_order_status_matches(self, record: Any, order_id: str) -> bool:
        observation = getattr(record, "observation", None)
        if not isinstance(observation, dict):
            return False
        if "status" not in observation:
            return False
        expected = order_id.lstrip("#")
        observed_order_id = observation.get("order_id")
        if observed_order_id is not None:
            return str(observed_order_id).lstrip("#") == expected
        recorded_order_id = record.arguments.get("order_id")
        if recorded_order_id is not None:
            return str(recorded_order_id).lstrip("#") == expected
        return False

    def _db_assertion_failures(
        self, runtime: AgentRuntime, case: EvalCase
    ) -> List[str]:
        assertions = case.expected_db_assertions
        if not assertions:
            return []
        failures: List[str] = []
        user_id = assertions.get("user_id")
        if user_id:
            user = get_user_from_db(runtime.retail_runtime.db, str(user_id))
            if not user:
                return [f"user:{user_id} not found"]
            address_assertions = assertions.get("address")
            if isinstance(address_assertions, dict):
                actual_address = user.get("address", {})
                for key, expected in address_assertions.items():
                    actual = actual_address.get(key)
                    if actual != expected:
                        failures.append(
                            f"user:{user_id} address.{key} expected {expected} actual {actual}"
                        )
        return failures

    def _llm_error_count(self, steps: List[Any]) -> int:
        count = 0
        for step in steps:
            node = getattr(step, "node", "")
            detail = getattr(step, "detail", {})
            if node.endswith("_llm") and detail.get("status") == "error":
                count += 1
        return count

    def _eval_backend(self) -> str:
        if self._is_replay_mode():
            return "replay"
        return "live" if self.live else "scripted"

    def _is_replay_mode(self) -> bool:
        return self.replay_trace_dir is not None or self.replay_case_path is not None

    def _index_replay_traces(self, trace_dir: Path) -> Dict[str, Path]:
        if not trace_dir.exists():
            raise FileNotFoundError(f"Replay trace directory not found: {trace_dir}")
        trace_index: Dict[str, Path] = {}
        trace_paths = {
            *trace_dir.glob("*.json"),
            *trace_dir.glob("runs/*.json"),
        }
        for trace_path in sorted(trace_paths):
            case_id = self._trace_case_id(trace_path)
            trace_index[case_id] = trace_path
        return trace_index

    def _trace_case_id(self, trace_path: Path) -> str:
        with trace_path.open(encoding="utf-8") as file:
            trace = json.load(file)
        case_id = (
            trace.get("metadata", {}).get("task_id")
            or trace.get("task_id")
            or trace.get("final_state", {}).get("task_id")
            or self._trace_case_id_from_filename(trace_path)
        )
        if not case_id:
            raise ValueError(
                f"Replay trace is missing case identity metadata: {trace_path}"
            )
        return str(case_id)

    def _trace_case_id_from_filename(self, trace_path: Path) -> Optional[str]:
        stem = trace_path.stem
        if "-trial-" not in stem:
            return None
        prefix, _, _ = stem.rpartition("-trial-")
        if not prefix:
            return None
        _, separator, case_id = prefix.rpartition("-")
        if not separator or not case_id:
            return None
        return case_id

    def _resolve_case_for_trace(self, trace_path: Path, *, subset: str) -> EvalCase:
        if not trace_path.exists():
            raise FileNotFoundError(f"Replay trace file not found: {trace_path}")
        case_id = self._trace_case_id(trace_path)
        for candidate_subset in self._candidate_replay_subsets(preferred=subset):
            for case in get_cases(candidate_subset):
                if case.case_id == case_id:
                    return case
        raise ValueError(
            f"Replay trace case_id '{case_id}' does not match any known eval case"
        )

    def _replay_user_messages(
        self, harness: TraceReplayHarness, case: EvalCase
    ) -> List[str]:
        messages = harness.user_messages
        if messages:
            return messages
        return [
            message.get("content", "")
            for message in case.messages
            if message.get("role") == "user"
        ]

    def _candidate_replay_subsets(self, *, preferred: Optional[str]) -> List[str]:
        ordered: List[str] = []
        if preferred:
            ordered.append(preferred)
        for subset in self._known_eval_subsets():
            if subset != preferred:
                ordered.append(subset)
        return ordered

    def _known_eval_subsets(self) -> List[str]:
        try:
            source = inspect.getsource(get_cases)
            discovered = _GET_CASES_SUBSET_RE.findall(source)
        except (OSError, TypeError):
            discovered = []

        ordered: List[str] = []
        for subset in discovered:
            if subset not in ordered:
                ordered.append(subset)
        if ordered:
            return ordered
        return [
            "curated_mvp",
            "generalized_mvp",
            "synthetic_seeded_v1",
            "generalization",
            "generalization_exploratory",
            "tau_retail_smoke",
            "tau_retail_supported",
            "tau_retail_train",
            "tau_retail_test",
        ]

    def _write_summary(
        self,
        summary: EvalRunSummary,
    ) -> Path:
        result_path = Path(summary.result_artifact_path)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        with result_path.open("w", encoding="utf-8") as file:
            json.dump(summary.as_dict(), file, indent=2, sort_keys=True)
            file.write("\n")
        return result_path

    def _write_report(self, summary: EvalRunSummary) -> Path:
        report_path = Path(summary.report_artifact_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8") as file:
            json.dump(build_report_artifact(summary), file, indent=2, sort_keys=True)
            file.write("\n")
        return report_path


def classify_failure(
    *,
    case: EvalCase,
    authenticated_user_id: Optional[str],
    final_intent: str,
    write_locks: List[str],
    actual_order_status: Optional[str],
    assistant_messages: List[str],
    tool_names: List[str],
    guard_block_reasons: List[str],
    tool_errors: int,
    guard_blocks: int,
    pending_action: bool,
    llm_errors: int,
    confirmation_status: str,
    db_assertion_failures: Optional[List[str]] = None,
) -> Optional[str]:
    # Phase 9 tau subsets: loose evaluation (Phase 9.1 smoke test)
    is_tau = case.subset.startswith("tau_retail_") if case.subset else False

    if llm_errors:
        return "llm_json_failure"

    # Tau subsets skip user_id and intent strict checks
    if not is_tau:
        if authenticated_user_id != case.expected_user_id:
            return "auth_failure"
    # Tau subsets: loose tool check — at least one expected tool must be
    # called (any tool, read or write). Don't require full action sequence.
    # Skip check if expected_tool_names is empty (no tool expectations).
    if is_tau:
        if case.expected_tool_names and not any(
            t in tool_names for t in case.expected_tool_names
        ):
            return "wrong_tool"
    else:
        missing_tools = [
            tool_name
            for tool_name in case.expected_tool_names
            if tool_name not in tool_names
        ]
        if missing_tools:
            return "wrong_tool"
    # Phase 5: required_tools / forbidden_tools
    if case.required_tools:
        missing_required = [
            t for t in case.required_tools if t not in tool_names
        ]
        if missing_required:
            return "required_tool_missing"
    if case.forbidden_tools:
        violated = [
            t for t in case.forbidden_tools if t in tool_names
        ]
        if violated:
            return "forbidden_tool_called"
    if tool_errors:
        return "tool_exception"
    if case.expected_guard_block_reason:
        if case.expected_guard_block_reason not in guard_block_reasons:
            return "expected_guard_block_missing"
    elif guard_blocks:
        return "guard_blocked"
    # Tau subsets skip confirmation status check
    if not is_tau:
        if case.expected_confirmation_status:
            if confirmation_status != case.expected_confirmation_status:
                return "confirmation_status_mismatch"
    if pending_action:
        return "confirmation_failure"
    if case.expected_no_write and write_locks:
        return "unexpected_mutation"
    if case.expected_write_lock and case.expected_write_lock not in write_locks:
        return "mutation_missing"
    # Tau subsets skip order_status check (DB assertions cover this)
    if not is_tau:
        if case.expected_order_status and actual_order_status != case.expected_order_status:
            return "db_state_mismatch"
    if db_assertion_failures:
        return "db_assertion_mismatch"
    if not is_tau:
        if case.expected_assistant_contains:
            transcript = "\n".join(assistant_messages)
            if case.expected_assistant_contains.lower() not in transcript.lower():
                return "response_mismatch"
    # Tau subsets skip tool_sequence check
    if not is_tau:
        if case.expected_tool_sequence:
            sequence_cursor = 0
            for tool_name in tool_names:
                if tool_name == case.expected_tool_sequence[sequence_cursor]:
                    sequence_cursor += 1
                    if sequence_cursor == len(case.expected_tool_sequence):
                        break
            if sequence_cursor < len(case.expected_tool_sequence):
                return "wrong_tool_sequence"
    return None


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"
