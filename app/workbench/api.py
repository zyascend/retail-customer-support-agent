from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import AppConfig, resolve_config
from app.workbench.cases import build_case_catalog
from app.workbench.errors import WorkbenchAPIError, error_payload
from app.workbench.session import WorkbenchSessionManager


class CreateSessionRequest(BaseModel):
    mode: str = "deterministic"
    case_id: Optional[str] = None


class SelectCaseRequest(BaseModel):
    case_id: str


class MessageRequest(BaseModel):
    content: str


class ResetRequest(BaseModel):
    case_id: Optional[str] = None
    mode: Optional[str] = None


def create_app(config: Optional[AppConfig] = None) -> FastAPI:
    resolved_config = config or resolve_config(artifact_dir="artifacts/phase4")
    manager = WorkbenchSessionManager(resolved_config)
    app = FastAPI(title="Retail Agent Workbench API")
    app.state.config = resolved_config
    app.state.manager = manager

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(WorkbenchAPIError)
    async def workbench_api_error_handler(
        _request: Any, error: WorkbenchAPIError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=error_payload(error),
        )

    @app.get("/api/workbench/config")
    def get_workbench_config() -> dict[str, Any]:
        return {
            "default_mode": "deterministic",
            "llm_available": bool(resolved_config.deepseek_api_key),
            "model": resolved_config.default_agent_model,
            "case_catalog": build_case_catalog(),
        }

    @app.post("/api/sessions")
    def create_session(
        request: Optional[CreateSessionRequest] = None,
    ) -> dict[str, Any]:
        request = request or CreateSessionRequest()
        session = manager.create_session(
            mode=request.mode,
            case_id=request.case_id,
        )
        return session.snapshot()

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        return manager.get(session_id).snapshot()

    @app.post("/api/sessions/{session_id}/select-case")
    def select_case(session_id: str, request: SelectCaseRequest) -> dict[str, Any]:
        return manager.get(session_id).select_case(request.case_id)

    @app.post("/api/sessions/{session_id}/step")
    def step_session(session_id: str) -> dict[str, Any]:
        return manager.get(session_id).step()

    @app.post("/api/sessions/{session_id}/run-all")
    def run_all_session(session_id: str) -> dict[str, Any]:
        return manager.get(session_id).run_all()

    @app.post("/api/sessions/{session_id}/messages")
    def send_message(session_id: str, request: MessageRequest) -> dict[str, Any]:
        return manager.get(session_id).send_message(request.content)

    @app.post("/api/sessions/{session_id}/reset")
    def reset_session(
        session_id: str,
        request: Optional[ResetRequest] = None,
    ) -> dict[str, Any]:
        request = request or ResetRequest()
        return manager.get(session_id).reset(
            case_id=request.case_id,
            mode=request.mode,
        )

    return app
