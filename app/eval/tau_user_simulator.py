"""Template-based user simulator for tau3 multi-turn conversations.

Parses tau3 task user_scenario instructions and simulates the user role
by responding to agent questions with template-generated replies.
"""

from __future__ import annotations

import re
from typing import Optional

_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")

_EMAIL_KEYWORDS = ("email", "e-mail", "mail")
_NAME_KEYWORDS = ("name", "who are you", "identify", "zip", "tell me who")


def _extract_name(instructions: dict) -> Optional[str]:
    """Extract user's full name from tau3 instructions."""
    known = instructions.get("known_info", "") or ""
    m = re.search(r"You (?:are|name is) ([\w\s]+?)(?: in| with| \(| living| residing|\.|$)", known)
    if m:
        return m.group(1).strip().rstrip(".")
    m = re.search(r"Your name is ([\w\s]+?)(?:,| and|\.|$)", known)
    if m:
        return m.group(1).strip().rstrip(".")
    return None


def _extract_email(instructions: dict) -> Optional[str]:
    """Extract email from tau3 instructions (handles parenthesized format)."""
    known = instructions.get("known_info", "") or ""
    m = _EMAIL_PATTERN.search(known)
    if m:
        return m.group(0)
    unknown = instructions.get("unknown_info", "") or ""
    if "email" in unknown.lower() and "do not remember" in unknown.lower():
        return None
    return None


def _extract_zip(instructions: dict) -> Optional[str]:
    """Extract zip code from tau3 instructions."""
    known = instructions.get("known_info", "") or ""
    m = re.search(r"zip(?:[ -]?code)? (\d{5})", known)
    if m:
        return m.group(1)
    return None


def _to_first_person(text: str | None) -> str:
    """Convert tau3 second-person instructions to first-person user message."""
    if not text:
        return ""
    text = re.sub(
        r"\bYou are ([\w\s]+?) (?:living |residing )?in zip(?:[ -]?code)? (\d{5})\b",
        r"My name is \1 and my zip code is \2", text,
    )
    text = re.sub(
        r"\bYou are ([\w]+)\s*\(([\w.+-]+@[\w.-]+\.[A-Za-z]{2,})\)",
        r"My name is \1 and my email is \2", text,
    )
    text = re.sub(
        r"\bYou are ([\w]+) with email ([\w.+-]+@[\w.-]+\.[A-Za-z]{2,})",
        r"My name is \1 and my email is \2", text,
    )
    text = re.sub(r"\bYour email is\b", "My email is", text)
    text = re.sub(r"\bYou do not remember\b", "I don't remember", text)
    text = re.sub(r"\bYou received\b", "I received", text)
    text = re.sub(r"\bYou wish to\b", "I want to", text)
    text = re.sub(r"\bYou want to\b", "I want to", text)
    text = re.sub(r"\byour order\b", "my order", text)
    text = re.sub(r"\bYour name is\b", "My name is", text)
    text = re.sub(r"\byou'd\b", "I'd", text)
    text = re.sub(r"\bYou\b", "I", text)
    text = re.sub(r"\byour\b", "my", text)
    return text


class TauUserSimulator:
    """Template-based user simulator for tau3 multi-turn conversations."""

    def __init__(self, task: dict) -> None:
        instructions = task["user_scenario"]["instructions"]
        self.name = _extract_name(instructions)
        self.email = _extract_email(instructions)
        self.zip_code = _extract_zip(instructions)
        self._reason = _to_first_person(instructions.get("reason_for_call", ""))
        self._unknown_info = instructions.get("unknown_info", "") or ""
        self._email_asked_count = 0
        self._name_asked_count = 0
        self._max_asks = 2

    def initial_message(self) -> str:
        """Generate the initial user message with reason and auth info."""
        parts = []
        if self._reason:
            parts.append(self._reason.strip())
        if self.email:
            parts.append(f"My email is {self.email}.")
        elif self.name and self.zip_code:
            parts.append(f"My name is {self.name} and my zip code is {self.zip_code}.")
        elif self.name:
            parts.append(f"My name is {self.name}.")
        return " ".join(parts)

    def respond(self, agent_message: str) -> Optional[str]:
        """Generate user response to agent question. Returns None to end."""
        lower = agent_message.lower()
        question_type = self._detect_question_type(lower)

        if question_type == "email":
            if self._email_asked_count >= self._max_asks:
                return None
            self._email_asked_count += 1
            if self.email:
                return f"My email is {self.email}."
            else:
                return "I don't remember my email address."

        if question_type == "name":
            if self._name_asked_count >= self._max_asks:
                return None
            self._name_asked_count += 1
            if self.name and self.zip_code:
                return f"My name is {self.name} and my zip code is {self.zip_code}."
            elif self.name:
                return f"My name is {self.name}."
            else:
                return "I'm not sure what information you need."

        return None

    @staticmethod
    def _detect_question_type(agent_message_lower: str) -> Optional[str]:
        if any(w in agent_message_lower for w in _EMAIL_KEYWORDS):
            return "email"
        if any(w in agent_message_lower for w in _NAME_KEYWORDS):
            return "name"
        return None
