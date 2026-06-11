from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict

from app.ops.serialization import stable_json


PROMPT_DIR = Path("prompts")


@dataclass(frozen=True)
class PromptSpec:
    prompt_id: str
    path: Path
    content: str
    sha256: str

    def as_metadata(self) -> Dict[str, str]:
        return {
            "prompt_id": self.prompt_id,
            "path": str(self.path),
            "sha256": self.sha256,
        }


def _load_prompt(prompt_id: str, filename: str) -> PromptSpec:
    path = PROMPT_DIR / filename
    content = path.read_text(encoding="utf-8").strip()
    digest = sha256(content.encode("utf-8")).hexdigest()
    return PromptSpec(
        prompt_id=prompt_id,
        path=path,
        content=content,
        sha256=digest,
    )


INTENT_SLOT_PROMPT = _load_prompt("intent_slot_v001", "intent_slot_v001.md")
POLICY_PROMPT = _load_prompt("policy_reasoner_v001", "policy_reasoner_v001.md")
ACTION_PLANNER_PROMPT = _load_prompt("action_planner_v001", "action_planner_v001.md")
RESPONSE_PROMPT = _load_prompt("response_generator_v001", "response_generator_v001.md")

INTENT_SLOT_SYSTEM = INTENT_SLOT_PROMPT.content
POLICY_SYSTEM = POLICY_PROMPT.content
ACTION_PLANNER_SYSTEM = ACTION_PLANNER_PROMPT.content
RESPONSE_SYSTEM = RESPONSE_PROMPT.content


def prompt_metadata() -> Dict[str, Dict[str, str]]:
    return {
        "intent_slot": INTENT_SLOT_PROMPT.as_metadata(),
        "policy_reasoner": POLICY_PROMPT.as_metadata(),
        "action_planner": ACTION_PLANNER_PROMPT.as_metadata(),
        "response_generator": RESPONSE_PROMPT.as_metadata(),
    }


def user_json_prompt(label: str, payload: Dict[str, Any]) -> str:
    return f"{label} JSON input:\n{stable_json(payload)}"
