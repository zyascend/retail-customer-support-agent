from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_TAU2_BENCH_ROOT = Path(
    "/Users/theyang/Documents/ai/AgentProject/data_sources/raw/tau2-bench"
)
DEFAULT_HISTORICAL_RESULT = (
    DEFAULT_TAU2_BENCH_ROOT
    / "data"
    / "tau2"
    / "results"
    / "final"
    / "gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json"
)
DEFAULT_ARTIFACT_DIR = Path("artifacts/phase0")


@dataclass(frozen=True)
class Phase0Config:
    tau2_bench_root: Path
    tau2_data_dir: Path
    artifact_dir: Path
    historical_result: Path

    @property
    def retail_domain_dir(self) -> Path:
        if (self.tau2_data_dir / "domains" / "retail").exists():
            return self.tau2_data_dir / "domains" / "retail"
        return self.tau2_data_dir / "tau2" / "domains" / "retail"

    @property
    def tau2_src_dir(self) -> Path:
        return self.tau2_bench_root / "src"

    @property
    def tau2_runtime_data_dir(self) -> Path:
        if (self.tau2_data_dir / "domains").exists():
            return self.tau2_data_dir.parent
        return self.tau2_data_dir


def resolve_config(
    tau2_bench_root: Optional[str] = None,
    tau2_data_dir: Optional[str] = None,
    artifact_dir: Optional[str] = None,
    historical_result: Optional[str] = None,
) -> Phase0Config:
    root = Path(
        tau2_bench_root
        or os.getenv("TAU2_BENCH_ROOT")
        or str(DEFAULT_TAU2_BENCH_ROOT)
    ).expanduser()
    data_dir = Path(
        tau2_data_dir or os.getenv("TAU2_DATA_DIR") or str(root / "data" / "tau2")
    ).expanduser()
    artifacts = Path(
        artifact_dir or os.getenv("PHASE0_ARTIFACT_DIR") or str(DEFAULT_ARTIFACT_DIR)
    ).expanduser()
    result = Path(
        historical_result
        or os.getenv("PHASE0_HISTORICAL_RESULT")
        or str(DEFAULT_HISTORICAL_RESULT)
    ).expanduser()
    return Phase0Config(
        tau2_bench_root=root,
        tau2_data_dir=data_dir,
        artifact_dir=artifacts,
        historical_result=result,
    )
