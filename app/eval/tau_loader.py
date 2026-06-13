"""Tau3 retail task -> EvalCase converter for Phase 9 ingestion.

Reads tau3 tasks.json and converts supported tasks into EvalCase objects
that the existing CuratedEvalRunner can execute.

Phase 9.1 (smoke test): script-based single-turn user message.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.config import AppConfig
from app.eval.cases import EvalCase

# Map tool names to intents (matching existing eval conventions)
TOOL_TO_INTENT: dict[str, str] = {
    "cancel_pending_order": "cancel_order",
    "return_delivered_order_items": "return_items",
    "exchange_delivered_order_items": "exchange_items",
    "modify_pending_order_address": "modify_order_address",
    "modify_pending_order_items": "modify_order_items",
    "modify_pending_order_payment": "modify_order_payment",
    "modify_user_address": "modify_user_address",
    "transfer_to_human_agents": "transfer",
}

# Write tools that trigger DB assertions (excludes transfer_to_human_agents)
WRITE_TOOLS: set[str] = {
    "cancel_pending_order",
    "return_delivered_order_items",
    "exchange_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
}

# Smoke test task IDs: prioritize task_issues (4,5,7) + diverse capabilities
SMOKE_TASK_IDS: set[str] = {"3", "4", "5", "7", "16", "17", "22", "40"}


def load_tau_tasks_from_dir(retail_dir: Path) -> list[dict]:
    """Load all tau3 tasks from the retail domain directory."""
    tasks_path = retail_dir / "tasks.json"
    with open(tasks_path, encoding="utf-8") as f:
        return json.load(f)


def _build_user_message(task: dict) -> str:
    """Build a single user message from tau3 user_scenario instructions.

    Converts tau3's second-person directives ("You are...") into first-person
    messages the agent's identity resolver can parse ("My name is...").

    The agent expects:
      - Email auth: "My email is X"
      - Name+zip auth: "My name is First Last and I live in zip Z"
    """
    instructions = task.get("user_scenario", {}).get("instructions", {})
    reason = instructions.get("reason_for_call", "")
    known = instructions.get("known_info", "")
    unknown = instructions.get("unknown_info", "")

    # Convert to first-person
    reason = _to_first_person(reason)
    known = _to_first_person(known)
    unknown = _to_first_person(unknown)

    parts = []
    if reason:
        parts.append(reason.strip())
    if known:
        parts.append(known.strip())
    if unknown:
        parts.append(unknown.strip())
    return " ".join(parts)


def _to_first_person(text: Optional[str]) -> str:
    """Convert tau3 second-person instructions to first-person user message.

    Common patterns in tau3 instructions:
      "You are X in zip Y" → "My name is X and I live in zip Y"
      "Your email is X"    → "My email is X"
      "You do not remember X" → "I don't remember X"
      "You received..."    → "I received..."
      "You want to..."     → "I want to..."
    """
    import re

    if not text:
        return ""

    # "You are First Last in zip 12345." or "...in zip code 12345."
    # → "My name is First Last and my zip code is 12345."
    # (matches NAME_ZIP_RE: "my name is First Last ... zip code is 12345")
    text = re.sub(
        r"\bYou are ([\w\s]+?) in zip(?: code)? (\d{5})\b",
        r"My name is \1 and my zip code is \2",
        text,
    )
    # "Your email is X" → "My email is X"
    text = re.sub(r"\bYour email is\b", "My email is", text)
    # "You do not remember X" → "I don't remember X"
    text = re.sub(r"\bYou do not remember\b", "I don't remember", text)
    # "You received" → "I received"
    text = re.sub(r"\bYou received\b", "I received", text)
    # "You wish to" → "I want to"
    text = re.sub(r"\bYou wish to\b", "I want to", text)
    # "You want to" → "I want to"
    text = re.sub(r"\bYou want to\b", "I want to", text)
    # "your order" → "my order"
    text = re.sub(r"\byour order\b", "my order", text)
    # "you'd" → "I'd"
    text = re.sub(r"\byou'd\b", "I'd", text)
    # "you" at sentence start → "I" (catch-all)
    text = re.sub(r"\bYou\b", "I", text)
    # "your" → "my" (catch-all)
    text = re.sub(r"\byour\b", "my", text)

    return text


def _derive_db_assertions(task: dict) -> dict:
    """Derive expected DB assertions from tau3 evaluation criteria actions."""
    actions = task.get("evaluation_criteria", {}).get("actions", [])
    assertions: dict = {}

    for action in actions:
        name = action.get("name", "")
        args = action.get("arguments", {})

        if name == "cancel_pending_order":
            assertions["order_id"] = args.get("order_id", "")
        elif name == "return_delivered_order_items":
            assertions["order_id"] = args.get("order_id", "")
            if "item_ids" in args:
                assertions["returned_item_ids"] = args["item_ids"]
        elif name == "exchange_delivered_order_items":
            assertions["order_id"] = args.get("order_id", "")
            if "new_item_ids" in args:
                assertions["new_item_ids"] = args["new_item_ids"]
        elif name in ("modify_pending_order_address",):
            assertions["order_id"] = args.get("order_id", "")
        elif name in ("modify_pending_order_items",):
            assertions["order_id"] = args.get("order_id", "")
            if "new_item_ids" in args:
                assertions["new_item_ids"] = args["new_item_ids"]
        elif name in ("modify_pending_order_payment",):
            assertions["order_id"] = args.get("order_id", "")
        elif name in ("modify_user_address",):
            pass  # user address change, no order-level assertion

    return assertions


def _primary_capability_from_actions(actions: list[dict]) -> str:
    """Determine the primary capability from tau3 action names."""
    for action in actions:
        name = action.get("name", "")
        if name in TOOL_TO_INTENT:
            return TOOL_TO_INTENT[name]
    return "lookup"


def _has_write_action(actions: list[dict]) -> bool:
    """Check if any action is a write operation."""
    return any(a.get("name", "") in WRITE_TOOLS for a in actions)


def convert_task_to_eval_case(task: dict, subset: str) -> Optional[EvalCase]:
    """Convert a single tau3 task to an EvalCase.

    Args:
        task: Raw tau3 task dict from tasks.json.
        subset: Eval subset name (e.g., "tau_retail_smoke").

    Returns:
        EvalCase if conversion succeeds, None if task should be skipped.
    """
    task_id = str(task["id"])
    actions = task.get("evaluation_criteria", {}).get("actions", [])

    # No actions -> skip
    if not actions:
        return None

    action_names = [a.get("name", "") for a in actions]
    has_write = _has_write_action(actions)
    capability = _primary_capability_from_actions(actions)
    user_message = _build_user_message(task)
    db_assertions = _derive_db_assertions(task) if has_write else {}

    # Determine expected_intent: use the capability directly
    expected_intent = capability

    return EvalCase(
        case_id=f"tau_{task_id}",
        category=capability,
        messages=[{"role": "user", "content": user_message}],
        expected_user_id="",  # tau3 smoke: skip user_id check (loose eval)
        expected_intent=expected_intent,
        expected_tool_names=action_names,
        expected_tool_sequence=list(action_names),
        expected_no_write=not has_write,
        expected_db_assertions=db_assertions,
        max_turns=5,
        subset=subset,
        capability=capability,
        scenario_family="tau3",
    )


def get_tau_smoke_cases(config: AppConfig) -> list[EvalCase]:
    """Return 5-10 selected supported tau3 tasks as EvalCase list.

    Selection priority:
    1. Task 4, 5, 7 (known task_issues)
    2. Diverse write capabilities
    3. Mix of train and test splits
    """
    from app.analysis.tau_task_analyzer import (
        _resolve_tau3_retail_dir,
        classify_task,
        load_splits,
        load_tasks,
    )

    retail_dir = _resolve_tau3_retail_dir(config)
    tasks = load_tasks(retail_dir)
    splits = load_splits(retail_dir)

    cases: list[EvalCase] = []
    smoke_ids_used: set[str] = set()

    # First pass: include the designated smoke task IDs if they are supported
    for task in tasks:
        tid = str(task["id"])
        if tid in SMOKE_TASK_IDS:
            classification = classify_task(task, splits)
            if classification.status == "supported":
                case = convert_task_to_eval_case(task, "tau_retail_smoke")
                if case is not None:
                    cases.append(case)
                    smoke_ids_used.add(tid)

    # Second pass: if we have < 5 cases, fill from remaining supported tasks
    if len(cases) < 5:
        for task in tasks:
            tid = str(task["id"])
            if tid in smoke_ids_used:
                continue
            classification = classify_task(task, splits)
            if classification.status != "supported":
                continue
            case = convert_task_to_eval_case(task, "tau_retail_smoke")
            if case is not None:
                cases.append(case)
                smoke_ids_used.add(tid)
                if len(cases) >= 10:
                    break

    return cases
