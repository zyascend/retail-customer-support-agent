from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional

from app.agent.models import AgentStep, ConversationState
from app.agent.prompts import prompt_metadata
from app.agent.providers import DisabledLLMProvider
from app.agent.runtime import AgentRuntime
from app.config import AppConfig
from app.eval.cases import EvalCase
from app.ops.tracing import TraceWriter
from app.workbench.cases import get_case_by_id
from app.workbench.errors import WorkbenchAPIError
from app.workbench.snapshot import snapshot_from_state


@dataclass
class WorkbenchSession:
    config: AppConfig
    session_id: str
    mode: str = "deterministic"
    selected_case: Optional[EvalCase] = None
    script_cursor: int = 0

    def __post_init__(self) -> None:
        self._lock = RLock()
        _validate_mode(self.mode, self.config)
        self.last_error: Optional[Dict[str, Any]] = None
        self.trace_artifact_path: Optional[str] = None
        self.initial_db_hash: Optional[str] = None
        self.runtime, self.state, self.initial_db_hash = (
            self._create_runtime_and_state_for(
                mode=self.mode,
                selected_case=self.selected_case,
            )
        )
        self.trace_artifact_path = self._write_trace_for(
            runtime=self.runtime,
            state=self.state,
            mode=self.mode,
            initial_db_hash=self.initial_db_hash,
        )

    @property
    def llm_available(self) -> bool:
        return bool(self.config.deepseek_api_key)

    def reset(
        self, case_id: Optional[str] = None, mode: Optional[str] = None
    ) -> Dict[str, Any]:
        with self._lock:
            next_mode = mode if mode is not None else self.mode
            _validate_mode(next_mode, self.config)
            next_selected_case = (
                _get_case_or_raise(case_id)
                if case_id is not None
                else self.selected_case
            )
            next_runtime, next_state, next_initial_db_hash = (
                self._create_runtime_and_state_for(
                    mode=next_mode,
                    selected_case=next_selected_case,
                )
            )
            next_trace_artifact_path = self._stage_reset_trace_for(
                runtime=next_runtime,
                state=next_state,
                mode=next_mode,
                initial_db_hash=next_initial_db_hash,
            )

            self.mode = next_mode
            self.selected_case = next_selected_case
            self.script_cursor = 0
            self.last_error = None
            self.runtime = next_runtime
            self.state = next_state
            self.initial_db_hash = next_initial_db_hash
            self.trace_artifact_path = next_trace_artifact_path
            return self.snapshot()

    def select_case(self, case_id: str) -> Dict[str, Any]:
        return self.reset(case_id=case_id)

    def step(self) -> Dict[str, Any]:
        with self._lock:
            selected_case = self._require_case()
            if self.script_cursor >= len(selected_case.messages):
                raise WorkbenchAPIError(
                    code="script_complete",
                    message="No scripted messages remain.",
                    recoverable=True,
                    details={
                        "case_id": selected_case.case_id,
                        "script_cursor": self.script_cursor,
                        "script_message_count": len(selected_case.messages),
                    },
                )
            message = selected_case.messages[self.script_cursor]
            if self._send_user_content(message.get("content", "")):
                self.script_cursor += 1
            return self.snapshot()

    def run_all(self) -> Dict[str, Any]:
        with self._lock:
            selected_case = self._require_case()
            while self.script_cursor < len(selected_case.messages):
                message = selected_case.messages[self.script_cursor]
                if not self._send_user_content(message.get("content", "")):
                    break
                self.script_cursor += 1
            return self.snapshot()

    def send_message(self, content: str) -> Dict[str, Any]:
        with self._lock:
            if not content.strip():
                raise WorkbenchAPIError(
                    code="empty_message",
                    message="Message content is required.",
                    recoverable=True,
                )
            self._send_user_content(content)
            return self.snapshot()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return snapshot_from_state(
                session_id=self.session_id,
                mode=self.mode,
                llm_available=self.llm_available,
                state=self.state,
                initial_db_hash=self.initial_db_hash,
                current_db_hash=self.runtime.retail_runtime.db_hash(),
                trace_artifact_path=self.trace_artifact_path,
                selected_case_id=(
                    self.selected_case.case_id
                    if self.selected_case is not None
                    else None
                ),
                script_cursor=self.script_cursor,
                script_message_count=(
                    len(self.selected_case.messages)
                    if self.selected_case is not None
                    else 0
                ),
                last_error=self.last_error,
            )

    def _create_runtime_and_state(self) -> None:
        self.runtime, self.state, self.initial_db_hash = (
            self._create_runtime_and_state_for(
                mode=self.mode,
                selected_case=self.selected_case,
            )
        )

    def _create_runtime_and_state_for(
        self,
        *,
        mode: str,
        selected_case: Optional[EvalCase],
    ) -> tuple[AgentRuntime, ConversationState, str]:
        provider = DisabledLLMProvider() if mode == "deterministic" else None

        # If this is a synthetic case, use SyntheticRetailAdapter
        runtime_kwargs = {}
        if selected_case is not None and selected_case.subset == "synthetic_seeded_v1":
            from app.synthetic.adapter import SyntheticRetailAdapter
            synthetic_adapter = SyntheticRetailAdapter(seed=42)
            runtime_kwargs["runtime"] = synthetic_adapter.create_runtime()

        runtime = AgentRuntime(
            self.config,
            provider=provider,
            require_llm=mode == "llm",
            **runtime_kwargs,
        )
        state = ConversationState(
            session_id=self.session_id,
            task_id=(selected_case.case_id if selected_case is not None else None),
        )
        return runtime, state, runtime.retail_runtime.db_hash()

    def _send_user_content(self, content: str) -> bool:
        try:
            self.runtime.handle_user_message(self.state, content)
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = {
                "code": "runtime_error",
                "message": str(exc),
                "recoverable": True,
                "details": {"exception_type": type(exc).__name__},
            }
            self.state.steps.append(
                AgentStep(
                    node="runtime_error",
                    status="error",
                    detail={"error": str(exc)},
                )
            )
            return False
        finally:
            self._write_trace()

    def _write_trace(self) -> None:
        self.trace_artifact_path = self._write_trace_for(
            runtime=self.runtime,
            state=self.state,
            mode=self.mode,
            initial_db_hash=self.initial_db_hash,
        )

    def _write_trace_for(
        self,
        *,
        runtime: AgentRuntime,
        state: ConversationState,
        mode: str,
        initial_db_hash: Optional[str],
        trace_path: Optional[Path] = None,
    ) -> str:
        if trace_path is not None:
            self._write_trace_payload_for(
                trace_path=trace_path,
                runtime=runtime,
                state=state,
                mode=mode,
                initial_db_hash=initial_db_hash,
            )
            return str(trace_path)
        trace_path = TraceWriter(self.config.run_artifact_dir).write(
            run_id=self.session_id,
            state=state,
            metadata=self._trace_metadata_for(
                runtime=runtime,
                mode=mode,
                initial_db_hash=initial_db_hash,
            ),
        )
        return str(trace_path)

    def _stage_reset_trace_for(
        self,
        *,
        runtime: AgentRuntime,
        state: ConversationState,
        mode: str,
        initial_db_hash: Optional[str],
    ) -> str:
        artifact_dir = self.config.run_artifact_dir
        artifact_dir.mkdir(parents=True, exist_ok=True)
        final_path = artifact_dir / f"{self.session_id}.json"
        temp_path = artifact_dir / f".{self.session_id}.{uuid.uuid4().hex}.tmp"
        try:
            self._write_trace_for(
                runtime=runtime,
                state=state,
                mode=mode,
                initial_db_hash=initial_db_hash,
                trace_path=temp_path,
            )
            temp_path.replace(final_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return str(final_path)

    def _write_trace_payload_for(
        self,
        *,
        trace_path: Path,
        runtime: AgentRuntime,
        state: ConversationState,
        mode: str,
        initial_db_hash: Optional[str],
    ) -> None:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        TraceWriter(self.config.run_artifact_dir).write_path(
            path=trace_path,
            run_id=self.session_id,
            state=state,
            metadata=self._trace_metadata_for(
                runtime=runtime,
                mode=mode,
                initial_db_hash=initial_db_hash,
            ),
        )

    def _trace_metadata_for(
        self,
        *,
        runtime: AgentRuntime,
        mode: str,
        initial_db_hash: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "runtime_source": runtime.retail_runtime.source,
            "model": self.config.default_agent_model,
            "mode": mode,
            "llm_available": self.llm_available,
            "llm_enabled": runtime.provider is not None,
            "llm_timeout_seconds": self.config.agent_llm_timeout_seconds,
            "llm_max_retries": self.config.agent_llm_max_retries,
            "initial_db_hash": initial_db_hash,
            "final_db_hash": runtime.retail_runtime.db_hash(),
            "tau2_bench_root": str(self.config.tau2_bench_root),
            "tau3_retail_root": str(self.config.tau3_retail_root),
            "retail_db_path": str(self.config.retail_db_path),
            "prompts": prompt_metadata(),
        }

    def _require_case(self) -> EvalCase:
        if self.selected_case is None:
            raise WorkbenchAPIError(
                code="case_required",
                message="Select a scripted case before using Step or Run all.",
                recoverable=True,
            )
        return self.selected_case


class WorkbenchSessionManager:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._sessions: Dict[str, WorkbenchSession] = {}

    def create_session(
        self, mode: str = "deterministic", case_id: Optional[str] = None
    ) -> WorkbenchSession:
        _validate_mode(mode, self.config)
        selected_case = _get_case_or_raise(case_id) if case_id is not None else None
        session_id = f"workbench-{uuid.uuid4().hex[:12]}"
        session = WorkbenchSession(
            config=self.config,
            session_id=session_id,
            mode=mode,
            selected_case=selected_case,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> WorkbenchSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise WorkbenchAPIError(
                code="session_not_found",
                message="Session was not found.",
                recoverable=True,
                details={"session_id": session_id},
                status_code=404,
            )
        return session


def _get_case_or_raise(case_id: str) -> EvalCase:
    try:
        return get_case_by_id(case_id)
    except ValueError as exc:
        raise WorkbenchAPIError(
            code="case_not_found",
            message="Case was not found.",
            recoverable=True,
            details={"case_id": case_id},
            status_code=404,
        ) from exc


def _validate_mode(mode: str, config: AppConfig) -> None:
    if mode == "deterministic":
        return
    if mode == "llm":
        if config.deepseek_api_key:
            return
        raise WorkbenchAPIError(
            code="llm_unavailable",
            message="LLM mode requires DEEPSEEK_API_KEY.",
            recoverable=True,
            status_code=400,
        )
    raise WorkbenchAPIError(
        code="invalid_mode",
        message="Unsupported workbench session mode.",
        recoverable=True,
        details={"mode": mode, "supported_modes": ["deterministic", "llm"]},
        status_code=400,
    )
