from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_TAU3_RETAIL_ROOT = Path(
    "/Users/theyang/Documents/ai/AgentProject/data_sources/"
    "retail_customer_support_transaction_agent/current_tau3_bench"
)
DEFAULT_TAU2_BENCH_ROOT = Path(
    "/Users/theyang/Documents/ai/AgentProject/data_sources/raw/tau2-bench"
)
DEFAULT_ARTIFACT_DIR = Path("artifacts/phase1")
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_AGENT_MODEL = "deepseek-v4-flash"
DEFAULT_AGENT_LLM_TIMEOUT_SECONDS = 30.0
DEFAULT_AGENT_LLM_MAX_RETRIES = 2


@dataclass(frozen=True)
class AppConfig:
    tau3_retail_root: Path
    tau2_bench_root: Path
    artifact_dir: Path
    deepseek_api_key: str
    deepseek_base_url: str
    default_agent_model: str
    agent_llm_timeout_seconds: float
    agent_llm_max_retries: int

    @property
    def retail_domain_dir(self) -> Path:
        return self.tau3_retail_root / "domains" / "retail"

    @property
    def retail_db_path(self) -> Path:
        return self.retail_domain_dir / "db.json"

    @property
    def retail_policy_path(self) -> Path:
        return self.retail_domain_dir / "policy.md"

    @property
    def retail_tasks_path(self) -> Path:
        return self.retail_domain_dir / "tasks.json"

    @property
    def tau2_src_dir(self) -> Path:
        return self.tau2_bench_root / "src"

    @property
    def run_artifact_dir(self) -> Path:
        return self.artifact_dir / "runs"


def resolve_config(
    tau3_retail_root: Optional[str] = None,
    tau2_bench_root: Optional[str] = None,
    artifact_dir: Optional[str] = None,
) -> AppConfig:
    _load_dotenv_candidates()
    root = Path(
        tau3_retail_root
        or os.getenv("TAU3_RETAIL_ROOT")
        or str(DEFAULT_TAU3_RETAIL_ROOT)
    ).expanduser()
    tau2_root = Path(
        tau2_bench_root
        or os.getenv("TAU2_BENCH_ROOT")
        or str(DEFAULT_TAU2_BENCH_ROOT)
    ).expanduser()
    artifacts = Path(
        artifact_dir
        or os.getenv("AGENT_ARTIFACT_DIR")
        or os.getenv("PHASE1_ARTIFACT_DIR")
        or str(DEFAULT_ARTIFACT_DIR)
    ).expanduser()
    return AppConfig(
        tau3_retail_root=root,
        tau2_bench_root=tau2_root,
        artifact_dir=artifacts,
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL),
        default_agent_model=os.getenv("DEFAULT_AGENT_MODEL", DEFAULT_AGENT_MODEL),
        agent_llm_timeout_seconds=_float_env(
            "AGENT_LLM_TIMEOUT_SECONDS", DEFAULT_AGENT_LLM_TIMEOUT_SECONDS
        ),
        agent_llm_max_retries=_int_env(
            "AGENT_LLM_MAX_RETRIES", DEFAULT_AGENT_LLM_MAX_RETRIES
        ),
    )


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _load_dotenv_candidates() -> None:
    seen: set[Path] = set()
    for path in _dotenv_candidate_paths():
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        _load_dotenv(path)


def _dotenv_candidate_paths() -> list[Path]:
    cwd = Path.cwd()
    candidates = [cwd / ".env"]
    candidates.extend(parent / ".env" for parent in cwd.parents)
    common_repo = _git_common_repo_root(cwd)
    if common_repo is not None:
        candidates.append(common_repo / ".env")
    return candidates


def _git_common_repo_root(cwd: Path) -> Optional[Path]:
    commondir = cwd / ".git" / "commondir"
    if not commondir.exists():
        return None
    raw_common_dir = commondir.read_text(encoding="utf-8").strip()
    if not raw_common_dir:
        return None
    common_dir = Path(raw_common_dir)
    if not common_dir.is_absolute():
        common_dir = commondir.parent / common_dir
    return common_dir.resolve().parent


def _float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be > 0")
    return value


def _int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value
