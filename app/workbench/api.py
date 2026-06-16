from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import AppConfig, resolve_config
from app.workbench.agentops import AgentOpsService
from app.workbench.cases import build_case_catalog
from app.workbench.errors import WorkbenchAPIError, error_payload
from app.workbench.session import WorkbenchSessionManager

DEFAULT_AGENTOPS_ARTIFACT_DIR = Path("artifacts/phase2")
DEFAULT_WORKBENCH_ARTIFACT_DIR = Path("artifacts/workbench")


class CreateSessionRequest(BaseModel):
    mode: str = "llm"
    case_id: Optional[str] = None


class SelectCaseRequest(BaseModel):
    case_id: str


class MessageRequest(BaseModel):
    content: str


class ResetRequest(BaseModel):
    case_id: Optional[str] = None
    mode: Optional[str] = None


def create_app(
    config: Optional[AppConfig] = None,
    *,
    agentops_artifact_dir: str | Path | None = None,
) -> FastAPI:
    resolved_config = config or resolve_config(
        artifact_dir=str(DEFAULT_WORKBENCH_ARTIFACT_DIR)
    )
    manager = WorkbenchSessionManager(resolved_config)
    agentops = AgentOpsService(
        artifact_dir=_agentops_artifact_dir(agentops_artifact_dir=agentops_artifact_dir)
    )
    app = FastAPI(title="Retail Agent Workbench API")
    app.state.config = resolved_config
    app.state.manager = manager
    app.state.agentops = agentops

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
            "default_mode": "llm",
            "llm_available": bool(resolved_config.deepseek_api_key),
            "model": resolved_config.default_agent_model,
            "case_catalog": build_case_catalog(),
        }

    @app.get("/api/agentops/reports")
    def list_agentops_reports() -> list[dict[str, Any]]:
        return [report.model_dump() for report in agentops.list_reports()]

    @app.get("/api/agentops/reports/{run_id}")
    def get_agentops_report(run_id: str) -> dict[str, Any]:
        return agentops.get_report(run_id).model_dump()

    @app.get("/api/agentops/reports/{run_id}/cases/{case_id}")
    def get_agentops_case(run_id: str, case_id: str) -> dict[str, Any]:
        return agentops.get_case(run_id, case_id).model_dump()

    @app.get("/api/agentops/traces/by-path")
    def get_agentops_trace_by_path(
        trace_path: str = Query(..., alias="path"),
    ) -> dict[str, Any]:
        return agentops.get_trace_by_path(trace_path).model_dump()

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


def _agentops_artifact_dir(*, agentops_artifact_dir: str | Path | None) -> Path:
    path = agentops_artifact_dir or DEFAULT_AGENTOPS_ARTIFACT_DIR
    return Path(path).expanduser().resolve()
