from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.agent.prompts import prompt_metadata
from app.agent.providers import DisabledLLMProvider
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

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["results"] = [asdict(result) for result in self.results]
        return payload


class CuratedEvalRunner:
    def __init__(
        self,
        *,
        config: AppConfig,
        artifact_dir: Path = DEFAULT_EVAL_ARTIFACT_DIR,
        require_llm: bool = False,
        progress_callback: Optional[Callable[[str, EvalCaseResult], None]] = None,
    ) -> None:
        self.config = config
        self.artifact_dir = artifact_dir
        self.require_llm = require_llm
        self.progress_callback = progress_callback

    def run(
        self,
        *,
        subset: str = "curated_mvp",
        trials: int = 1,
        max_workers: int = 1,
    ) -> EvalRunSummary:
        eval_run_id = "eval-" + uuid.uuid4().hex[:12]
        cases = get_cases(subset)
        results: List[EvalCaseResult] = []
        for trial in range(trials):
            if max_workers > 1:
                trial_results = self._run_trial_parallel(
                    eval_run_id, cases, trial, max_workers,
                )
            else:
                trial_results = self._run_trial_sequential(
                    eval_run_id, cases, trial,
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
            llm_required=self.require_llm,
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
            futures = [
                pool.submit(_run_one, case, i)
                for i, case in enumerate(cases)
            ]
            for future in as_completed(futures):
                results.append(future.result())

        return results

    def _run_case(
        self, eval_run_id: str, case: EvalCase, trial: int
    ) -> EvalCaseResult:
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
        provider = None if self.require_llm else DisabledLLMProvider()
        runtime = AgentRuntime(
            runtime_config,
            provider=provider,
            require_llm=self.require_llm,
        )
        session_id = f"{eval_run_id}-{case.case_id}-trial-{trial}"
        order_status_before = self._order_status(runtime, case)
        started_at = time.perf_counter()
        run_result = runtime.run_script(
            messages=case.messages,
            session_id=session_id,
            task_id=case.case_id,
            max_turns=case.max_turns,
        )
        duration_seconds = round(time.perf_counter() - started_at, 3)
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
            1 for record in state.tool_results if record.status == "blocked"
        )
        successful_tool_calls = sum(
            1 for record in state.tool_results if record.status == "success"
        )
        trace_metadata = self._trace_metadata(run_result.trace_artifact_path)
        db_assertion_failures = self._db_assertion_failures(runtime, case)
        failure_label = classify_failure(
            case=case,
            authenticated_user_id=state.authenticated_user_id,
            final_intent=state.current_intent,
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
            passed=failure_label is None,
            failure_label=failure_label,
            trace_artifact_path=str(run_result.trace_artifact_path),
            authenticated_user_id=state.authenticated_user_id,
            final_intent=state.current_intent,
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
            trial_turn_count=sum(1 for message in state.messages if message.role == "user"),
            message_count=len(state.messages),
            policy_check_count=1 if state.policy_decision else 0,
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
    if llm_errors:
        return "llm_json_failure"
    if authenticated_user_id != case.expected_user_id:
        return "auth_failure"
    if final_intent != case.expected_intent:
        return "wrong_intent"
    missing_tools = [
        tool_name
        for tool_name in case.expected_tool_names
        if tool_name not in tool_names
    ]
    if missing_tools:
        return "wrong_tool"
    if tool_errors:
        return "tool_exception"
    if case.expected_guard_block_reason:
        if case.expected_guard_block_reason not in guard_block_reasons:
            return "expected_guard_block_missing"
    elif guard_blocks:
        return "guard_blocked"
    if case.expected_confirmation_status:
        if confirmation_status != case.expected_confirmation_status:
            return "confirmation_status_mismatch"
    if pending_action:
        return "confirmation_failure"
    if case.expected_no_write and write_locks:
        return "unexpected_mutation"
    if case.expected_write_lock and case.expected_write_lock not in write_locks:
        return "mutation_missing"
    if case.expected_order_status and actual_order_status != case.expected_order_status:
        return "db_state_mismatch"
    if db_assertion_failures:
        return "db_assertion_mismatch"
    if case.expected_assistant_contains:
        transcript = "\n".join(assistant_messages)
        if case.expected_assistant_contains not in transcript:
            return "response_mismatch"
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
