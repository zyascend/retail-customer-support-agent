from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class WorkbenchAPIError(Exception):
    code: str
    message: str
    recoverable: bool = True
    details: Dict[str, Any] = field(default_factory=dict)
    status_code: int = 400


def error_payload(error: WorkbenchAPIError) -> Dict[str, Any]:
    return {
        "error": {
            "code": error.code,
            "message": error.message,
            "recoverable": error.recoverable,
            "details": error.details,
        }
    }
