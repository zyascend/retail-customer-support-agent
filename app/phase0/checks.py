from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from app.phase0.config import Phase0Config


RETAIL_REQUIRED_FILES = ("db.json", "policy.md", "tasks.json", "split_tasks.json")


@dataclass
class CheckMessage:
    name: str
    status: str
    detail: str

    def as_dict(self) -> Dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class EnvironmentCheck:
    ok: bool
    messages: List[CheckMessage] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "messages": [message.as_dict() for message in self.messages],
            "metadata": self.metadata,
        }


class Phase0CheckError(RuntimeError):
    pass


def _read_json(path: Path, label: str) -> Any:
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError as exc:
        raise Phase0CheckError(f"{label} not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise Phase0CheckError(f"{label} is not valid JSON: {path}: {exc}") from exc


def run_environment_check(
    config: Phase0Config,
    expected_task_count: int = 114,
) -> EnvironmentCheck:
    messages: List[CheckMessage] = []
    metadata: Dict[str, Any] = {
        "tau2_bench_root": str(config.tau2_bench_root),
        "tau2_data_dir": str(config.tau2_data_dir),
        "tau2_runtime_data_dir": str(config.tau2_runtime_data_dir),
        "retail_domain_dir": str(config.retail_domain_dir),
        "historical_result": str(config.historical_result),
    }
    errors = 0

    uv_path = shutil.which("uv")
    if uv_path:
        messages.append(CheckMessage("uv", "ok", uv_path))
        metadata["uv_path"] = uv_path
    else:
        messages.append(
            CheckMessage(
                "uv",
                "warning",
                "uv is not installed or not on PATH; install it before using uv run.",
            )
        )

    expected_root_files = ("pyproject.toml", "uv.lock", "src/tau2")
    if config.tau2_bench_root.exists():
        messages.append(CheckMessage("tau2_bench_root", "ok", str(config.tau2_bench_root)))
        missing_root_files = [
            item for item in expected_root_files if not (config.tau2_bench_root / item).exists()
        ]
        if missing_root_files:
            errors += 1
            messages.append(
                CheckMessage(
                    "tau2_source_shape",
                    "error",
                    "missing " + ", ".join(missing_root_files),
                )
            )
        else:
            messages.append(CheckMessage("tau2_source_shape", "ok", "source files found"))
    else:
        errors += 1
        messages.append(
            CheckMessage("tau2_bench_root", "error", str(config.tau2_bench_root))
        )

    missing_retail_files = [
        name for name in RETAIL_REQUIRED_FILES if not (config.retail_domain_dir / name).exists()
    ]
    if missing_retail_files:
        errors += 1
        messages.append(
            CheckMessage(
                "retail_files",
                "error",
                "missing " + ", ".join(missing_retail_files),
            )
        )
    else:
        messages.append(CheckMessage("retail_files", "ok", "required files found"))

    tasks_path = config.retail_domain_dir / "tasks.json"
    split_path = config.retail_domain_dir / "split_tasks.json"
    if tasks_path.exists():
        tasks = _read_json(tasks_path, "retail tasks")
        task_count = len(tasks) if isinstance(tasks, list) else -1
        metadata["retail_task_count"] = task_count
        if task_count != expected_task_count:
            errors += 1
            messages.append(
                CheckMessage(
                    "retail_task_count",
                    "error",
                    f"expected {expected_task_count}, found {task_count}",
                )
            )
        else:
            messages.append(
                CheckMessage("retail_task_count", "ok", f"{task_count} tasks")
            )

    if split_path.exists():
        splits = _read_json(split_path, "retail split tasks")
        if not isinstance(splits, dict) or not splits:
            errors += 1
            messages.append(
                CheckMessage("retail_splits", "error", "split metadata is empty")
            )
        else:
            split_counts = {
                str(name): len(task_ids) if isinstance(task_ids, list) else None
                for name, task_ids in splits.items()
            }
            metadata["retail_split_counts"] = split_counts
            messages.append(
                CheckMessage(
                    "retail_splits",
                    "ok",
                    ", ".join(f"{name}={count}" for name, count in split_counts.items()),
                )
            )

    if config.historical_result.exists():
        messages.append(
            CheckMessage("historical_result", "ok", str(config.historical_result))
        )
    else:
        errors += 1
        messages.append(
            CheckMessage("historical_result", "error", str(config.historical_result))
        )

    return EnvironmentCheck(ok=errors == 0, messages=messages, metadata=metadata)
