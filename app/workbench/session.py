from __future__ import annotations

import uuid
from dataclasses import dataclass
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
        _validate_mode(self.mode, self.config)
        self.last_error: Optional[Dict[str, Any]] = None
        self.trace_artifact_path: Optional[str] = None
        self.initial_db_hash: Optional[str] = None
        self._create_runtime_and_state()
        self._write_trace()

    @property
    def llm_available(self) -> bool:
        return bool(self.config.deepseek_api_key)

    def reset(
        self, case_id: Optional[str] = None, mode: Optional[str] = None
    ) -> Dict[str, Any]:
        if mode is not None:
            _validate_mode(mode, self.config)
            self.mode = mode
        if case_id is not None:
            self.selected_case = get_case_by_id(case_id)
        self.script_cursor = 0
        self.last_error = None
        self._create_runtime_and_state()
        self._write_trace()
        return self.snapshot()

    def select_case(self, case_id: str) -> Dict[str, Any]:
        return self.reset(case_id=case_id)

    def step(self) -> Dict[str, Any]:
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
        self._send_user_content(message.get("content", ""))
        self.script_cursor += 1
        return self.snapshot()

    def run_all(self) -> Dict[str, Any]:
        selected_case = self._require_case()
        while self.script_cursor < len(selected_case.messages):
            message = selected_case.messages[self.script_cursor]
            self._send_user_content(message.get("content", ""))
            self.script_cursor += 1
        return self.snapshot()

    def send_message(self, content: str) -> Dict[str, Any]:
        if not content.strip():
            raise WorkbenchAPIError(
                code="empty_message",
                message="Message content is required.",
                recoverable=True,
            )
        self._send_user_content(content)
        return self.snapshot()

    def snapshot(self) -> Dict[str, Any]:
        return snapshot_from_state(
            session_id=self.session_id,
            mode=self.mode,
            llm_available=self.llm_available,
            state=self.state,
            initial_db_hash=self.initial_db_hash,
            current_db_hash=self.runtime.retail_runtime.db_hash(),
            trace_artifact_path=self.trace_artifact_path,
            selected_case_id=(
                self.selected_case.case_id if self.selected_case is not None else None
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
        provider = DisabledLLMProvider() if self.mode == "deterministic" else None
        self.runtime = AgentRuntime(
            self.config,
            provider=provider,
            require_llm=self.mode == "llm",
        )
        self.state = ConversationState(
            session_id=self.session_id,
            task_id=(
                self.selected_case.case_id if self.selected_case is not None else None
            ),
        )
        self.initial_db_hash = self.runtime.retail_runtime.db_hash()

    def _send_user_content(self, content: str) -> None:
        try:
            self.runtime.handle_user_message(self.state, content)
            self.last_error = None
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
        finally:
            self._write_trace()

    def _write_trace(self) -> None:
        trace_path = TraceWriter(self.config.run_artifact_dir).write(
            run_id=self.session_id,
            state=self.state,
            metadata={
                "runtime_source": self.runtime.retail_runtime.source,
                "model": self.config.default_agent_model,
                "mode": self.mode,
                "llm_available": self.llm_available,
                "llm_enabled": self.runtime.provider is not None,
                "llm_timeout_seconds": self.config.agent_llm_timeout_seconds,
                "llm_max_retries": self.config.agent_llm_max_retries,
                "initial_db_hash": self.initial_db_hash,
                "final_db_hash": self.runtime.retail_runtime.db_hash(),
                "tau2_bench_root": str(self.config.tau2_bench_root),
                "tau3_retail_root": str(self.config.tau3_retail_root),
                "retail_db_path": str(self.config.retail_db_path),
                "prompts": prompt_metadata(),
            },
        )
        self.trace_artifact_path = str(trace_path)

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
        selected_case = get_case_by_id(case_id) if case_id is not None else None
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
