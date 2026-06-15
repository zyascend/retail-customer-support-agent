from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict


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


PROMPT_DIR = Path("prompts")


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


# ── Active prompts ──
# Only the prompts actually used by the runtime are loaded here.
# See llm_agent.py:_load_system_prompt_template() for assembly.

AGENT_SYSTEM_PROMPT = _load_prompt(
    "llm_agent_system_v001", "llm_agent_system_v001.md"
)


def prompt_metadata() -> Dict[str, Dict[str, str]]:
    """SHA-256 fingerprint of the active system prompt.

    Recorded in trace artifacts and eval report metadata for version tracking.
    """
    return {
        "llm_agent_system": AGENT_SYSTEM_PROMPT.as_metadata(),
    }
