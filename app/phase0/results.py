from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class ResultParseError(RuntimeError):
    pass


@dataclass
class ResultSummary:
    result_path: str
    task_count: int
    simulation_count: int
    trial_count: Optional[int]
    average_reward: float
    pass_rate: float
    pass_hat_ks: Dict[str, float] = field(default_factory=dict)
    average_agent_cost: Optional[float] = None
    average_user_cost: Optional[float] = None
    average_total_cost: Optional[float] = None
    average_duration_seconds: Optional[float] = None
    infra_error_count: int = 0
    termination_counts: Dict[str, int] = field(default_factory=dict)
    reward_basis_counts: Dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "result_path": self.result_path,
            "task_count": self.task_count,
            "simulation_count": self.simulation_count,
            "trial_count": self.trial_count,
            "average_reward": self.average_reward,
            "pass_rate": self.pass_rate,
            "pass_hat_ks": self.pass_hat_ks,
            "average_agent_cost": self.average_agent_cost,
            "average_user_cost": self.average_user_cost,
            "average_total_cost": self.average_total_cost,
            "average_duration_seconds": self.average_duration_seconds,
            "infra_error_count": self.infra_error_count,
            "termination_counts": self.termination_counts,
            "reward_basis_counts": self.reward_basis_counts,
        }


def load_result_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError as exc:
        raise ResultParseError(f"result file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ResultParseError(f"result file is not valid JSON: {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ResultParseError(f"result file must contain a JSON object: {path}")
    if not isinstance(data.get("tasks"), list):
        raise ResultParseError("result file is missing list field: tasks")
    if not isinstance(data.get("simulations"), list):
        raise ResultParseError("result file is missing list field: simulations")
    return data


def summarize_result(path: Path) -> ResultSummary:
    data = load_result_json(path)
    tasks = data["tasks"]
    simulations = data["simulations"]
    rewards = [_get_reward(sim) for sim in simulations]
    successes = [reward is not None and _is_success(reward) for reward in rewards]
    agent_costs = [_optional_float(sim.get("agent_cost")) for sim in simulations]
    user_costs = [_optional_float(sim.get("user_cost")) for sim in simulations]
    durations = [_optional_float(sim.get("duration")) for sim in simulations]
    terminations = Counter(
        str(sim.get("termination_reason") or "unknown") for sim in simulations
    )
    infra_error_count = terminations.get("infrastructure_error", 0)
    reward_basis_counts = _reward_basis_counts(simulations)

    pass_hat_ks = _compute_pass_hat_ks(simulations)
    trial_count = _trial_count(data, simulations)
    avg_agent_cost = _mean(agent_costs)
    avg_user_cost = _mean(user_costs)
    return ResultSummary(
        result_path=str(path),
        task_count=len(tasks),
        simulation_count=len(simulations),
        trial_count=trial_count,
        average_reward=_mean(rewards) or 0.0,
        pass_rate=sum(successes) / len(successes) if successes else 0.0,
        pass_hat_ks=pass_hat_ks,
        average_agent_cost=avg_agent_cost,
        average_user_cost=avg_user_cost,
        average_total_cost=_sum_optional_means(avg_agent_cost, avg_user_cost),
        average_duration_seconds=_mean(durations),
        infra_error_count=infra_error_count,
        termination_counts=dict(sorted(terminations.items())),
        reward_basis_counts=reward_basis_counts,
    )


def write_summary(summary: ResultSummary, artifact_dir: Path) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    output_path = artifact_dir / "phase0_report.json"
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(summary.as_dict(), file, indent=2, sort_keys=True)
        file.write("\n")
    return output_path


def _get_reward(simulation: Dict[str, Any]) -> Optional[float]:
    reward_info = simulation.get("reward_info")
    if isinstance(reward_info, dict) and "reward" in reward_info:
        return _optional_float(reward_info.get("reward"))
    return _optional_float(simulation.get("reward"))


def _is_success(reward: float) -> bool:
    return (1.0 - 1e-6) <= reward <= (1.0 + 1e-6)


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _sum_optional_means(left: Optional[float], right: Optional[float]) -> Optional[float]:
    if left is None and right is None:
        return None
    return (left or 0.0) + (right or 0.0)


def _trial_count(data: Dict[str, Any], simulations: List[Dict[str, Any]]) -> Optional[int]:
    info = data.get("info")
    if isinstance(info, dict):
        value = info.get("num_trials")
        if isinstance(value, int):
            return value
    trials_by_task: Dict[str, set] = defaultdict(set)
    for sim in simulations:
        task_id = sim.get("task_id")
        trial = sim.get("trial")
        if task_id is not None and trial is not None:
            trials_by_task[str(task_id)].add(trial)
    if not trials_by_task:
        return None
    counts = {len(trials) for trials in trials_by_task.values()}
    if len(counts) == 1:
        return counts.pop()
    return min(counts)


def _compute_pass_hat_ks(simulations: List[Dict[str, Any]]) -> Dict[str, float]:
    by_task: Dict[str, List[bool]] = defaultdict(list)
    for sim in simulations:
        task_id = sim.get("task_id")
        if task_id is None:
            continue
        reward = _get_reward(sim)
        by_task[str(task_id)].append(reward is not None and _is_success(reward))
    if not by_task:
        return {}

    max_k = min(len(values) for values in by_task.values())
    result: Dict[str, float] = {}
    for k in range(1, max_k + 1):
        values = []
        for successes in by_task.values():
            success_count = sum(1 for success in successes if success)
            values.append(_pass_hat_k(len(successes), success_count, k))
        result[f"pass_hat_{k}"] = sum(values) / len(values) if values else 0.0
    return result


def _pass_hat_k(num_trials: int, success_count: int, k: int) -> float:
    if num_trials < k:
        return 0.0
    return math.comb(success_count, k) / math.comb(num_trials, k)


def _reward_basis_counts(simulations: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Counter = Counter()
    for sim in simulations:
        reward_info = sim.get("reward_info")
        if not isinstance(reward_info, dict):
            continue
        basis = reward_info.get("reward_basis") or []
        for item in basis:
            counts[str(item)] += 1
    return dict(sorted(counts.items()))
