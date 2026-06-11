from __future__ import annotations

import json
import re
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.agent.providers import DisabledLLMProvider
from app.agent.prompts import prompt_metadata
from app.agent.runtime import AgentRuntime
from app.config import AppConfig
from app.eval.cases import EvalCase, get_cases
from app.tools.retail_adapter import get_order_from_db


DEFAULT_EVAL_ARTIFACT_DIR = Path("artifacts/phase2")
ORDER_RE = re.compile(r"#W\d+")


@dataclass
class EvalCaseResult:
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
    duration_seconds: float = 0.0
    tool_protocol_violations: int = 0
    tool_errors: int = 0
    guard_blocks: int = 0


@dataclass
class EvalRunSummary:
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
    dataset_root: str
    dataset_db_path: str
    code_commit: str
    prompt_metadata: Dict[str, Dict[str, str]]
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

    def run(self, *, subset: str = "curated_mvp", trials: int = 1) -> EvalRunSummary:
        eval_run_id = "eval-" + uuid.uuid4().hex[:12]
        cases = get_cases(subset)
        results: List[EvalCaseResult] = []
        for trial in range(trials):
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
        passed_count = sum(1 for result in results if result.passed)
        result_path = self.artifact_dir / "eval_runs" / f"{eval_run_id}.json"
        created_at = datetime.now(timezone.utc).isoformat()
        code_commit = _git_commit()
        result_path = self._write_summary(
            eval_run_id=eval_run_id,
            subset=subset,
            trials=trials,
            created_at=created_at,
            results=results,
            passed_count=passed_count,
            result_path=result_path,
            code_commit=code_commit,
        )
        return EvalRunSummary(
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
            dataset_root=str(self.config.tau3_retail_root),
            dataset_db_path=str(self.config.retail_db_path),
            code_commit=code_commit,
            prompt_metadata=prompt_metadata(),
            results=results,
        )

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
        started_at = time.perf_counter()
        run_result = runtime.run_script(
            messages=case.messages,
            session_id=session_id,
            task_id=case.case_id,
            max_turns=case.max_turns,
        )
        duration_seconds = round(time.perf_counter() - started_at, 3)
        state = run_result.state
        actual_order_status = self._actual_order_status(runtime, case)
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
        )
        return EvalCaseResult(
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
            initial_db_hash=self._trace_metadata(run_result.trace_artifact_path).get(
                "initial_db_hash"
            ),
            final_db_hash=self._trace_metadata(run_result.trace_artifact_path).get(
                "final_db_hash"
            ),
            duration_seconds=duration_seconds,
            tool_errors=tool_errors,
            guard_blocks=guard_blocks,
        )

    def _progress_placeholder(self, *, case: EvalCase, trial: int) -> EvalCaseResult:
        return EvalCaseResult(
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

    def _actual_order_status(
        self, runtime: AgentRuntime, case: EvalCase
    ) -> Optional[str]:
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
        *,
        eval_run_id: str,
        subset: str,
        trials: int,
        created_at: str,
        results: List[EvalCaseResult],
        passed_count: int,
        result_path: Path,
        code_commit: str,
    ) -> Path:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "eval_run_id": eval_run_id,
            "subset": subset,
            "trials": trials,
            "created_at": created_at,
            "agent_strategy": "guarded_workflow_agent",
            "model": self.config.default_agent_model,
            "llm_required": self.require_llm,
            "llm_timeout_seconds": self.config.agent_llm_timeout_seconds,
            "llm_max_retries": self.config.agent_llm_max_retries,
            "dataset_root": str(self.config.tau3_retail_root),
            "dataset_db_path": str(self.config.retail_db_path),
            "code_commit": code_commit,
            "prompt_metadata": prompt_metadata(),
            "case_count": len(results),
            "passed_count": passed_count,
            "pass_rate": passed_count / len(results) if results else 0.0,
            "results": [asdict(result) for result in results],
        }
        with result_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, sort_keys=True)
            file.write("\n")
        return result_path


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
    if case.expected_assistant_contains:
        transcript = "\n".join(assistant_messages)
        if case.expected_assistant_contains not in transcript:
            return "response_mismatch"
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
