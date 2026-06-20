"""Skill data model.

A Skill is a versioned unit that bundles:
  - intent patterns for recognizing user requests
  - the tool call chain (required reads + entry write tools)
  - guard constraints summarised from action_specs
  - prompt guidance text injected into the system prompt
  - few-shot examples scoped to this skill

Skills are purely an *organisational* abstraction layered on top of
action_specs / registry / guard.  They do **not** change the Agent Loop
execution model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class SkillSpec:
    """Versioned behaviour-skill definition."""

    # ── Identity ──
    skill_id: str
    display_name: str
    version: str
    description: str

    # ── Behaviour constraints ──
    intent_patterns: Tuple[str, ...]
    entry_tools: Tuple[str, ...]
    required_reads: Tuple[str, ...]
    guard_constraints: Tuple[str, ...]

    # ── Prompt fragments (injected into system prompt) ──
    prompt_guidance: str
    few_shot_examples: str

    # ── Metadata ──
    risk: str  # "high" | "medium"
    related_action_specs: Tuple[str, ...]
    tags: Tuple[str, ...]
