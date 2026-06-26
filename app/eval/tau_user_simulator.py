"""Template-based user simulator for tau3 multi-turn conversations.

Parses tau3 task user_scenario instructions and simulates the user role
by responding to agent questions with template-generated replies.
"""

from __future__ import annotations

import json
import re
from typing import Optional

_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PAYMENT_METHOD_PATTERN = re.compile(
    r"\b(?:paypal|gift_card|credit_card)_\d+\b",
    re.IGNORECASE,
)

_EMAIL_KEYWORDS = ("email", "e-mail", "mail")
_NAME_KEYWORDS = ("name", "who are you", "identify", "zip", "tell me who")
_CONFIRMATION_KEYWORDS = (
    "confirm",
    "proceed",
    "go ahead",
    "authorize",
    "would you like me",
)
_ORDER_ID_KEYWORDS = ("order id", "order number", "order #")
_ORDER_ID_RETRY_KEYWORDS = (
    "double-check",
    "double check",
    "doesn't work",
    "does not work",
    "not work",
    "still",
)
_VACUUM_KEYWORDS = ("which vacuum", "vacuum cleaner")
_PAYMENT_METHOD_KEYWORDS = ("payment method", "refund sent", "refund to")
_REPLACEMENT_CHOICE_KEYWORDS = ("which one", "exchange", "replace", "swap")
_GENERIC_HELP_KEYWORDS = ("how can i help", "what can i help", "how may i help")
_POEM_PROMPT_KEYWORDS = (
    "what poem",
    "which poem",
    "first line",
    "famous poem",
    "guess what",
)
_ORDER_ID_REQUEST_KEYWORDS = (
    "provide",
    "need",
    "do you have",
    "what is",
    "what's",
    "could you",
    "please",
)

# Cache for tau3 user DB
_user_db_cache: dict | None = None
_user_db_path: str | None = None


def _extract_name(instructions: dict) -> Optional[str]:
    """Extract user's full name from tau3 instructions."""
    known = instructions.get("known_info", "") or ""

    # Pattern 1: "You are [X] in/from/with/living..." with optional
    # "an interesting guy called" prefix
    m = re.search(
        r"You(?:'re| are| name is)\s+"
        r"(?:an?\s+\w+\s+\w+\s+(?:called|named)\s+)?"  # optional prefix
        r"([\w\s]+?)"
        r"(?:\s+in\s|\s+from\s|\s+with\s|\s+living\s|"
        r",\s*(?:and|residing|but|you|living|\s)|"
        r"\s+\(|\.|$)",
        known,
        re.IGNORECASE,
    )
    if m:
        name = m.group(1).strip()
        if len(name) > 2 and name.lower() not in ("an", "the", "a"):
            return name

    # Pattern 2: "Your name is [X]..."
    m = re.search(
        r"Your name is\s+([\w\s]+?)(?:,| and|\.|$)",
        known,
        re.IGNORECASE,
    )
    if m:
        name = m.group(1).strip()
        if len(name) > 2 and name.lower() not in ("an", "the", "a"):
            return name

    return None


def _resolve_name_to_user_id(name: str) -> str | None:
    """Extract a DB user ID from various name formats.

    Handles:
    - "Lucas (lucas_santos_6600)" → "lucas_santos_6600"
    - "user noah_ito_3850" → "noah_ito_3850"
    - "aarav_santos_2259" → "aarav_santos_2259"
    """
    # Strip "user " prefix
    if name.lower().startswith("user "):
        name = name[5:]
    # Extract parenthesized user ID
    m = re.search(r"\((\w+)\)", name)
    if m:
        return m.group(1).lower()
    # Extract underscore-containing user ID
    m = re.search(r"([a-z]+_[a-z]+_\d+)", name, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    # Fallback: replace spaces with underscores
    if " " in name:
        return name.replace(" ", "_").lower()
    return None


def _extract_email(instructions: dict) -> Optional[str]:
    """Extract email from tau3 instructions.

    Returns the last email found — for multi-email tasks where the first
    email is deliberately incorrect, the last one is usually the right one.
    """
    known = instructions.get("known_info", "") or ""
    emails = _EMAIL_PATTERN.findall(known)
    if emails:
        # Return the last email (often the correct one)
        return emails[-1]
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
    # Fallback: any 5-digit number at end of known_info or near city
    m = re.search(r"\b(\d{5})\b", known)
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
    # "Your name is X, and you live in Y, 12345." → "My name is X and I live in Y, 12345."
    text = re.sub(
        r"\bYour name is ([\w\s]+?), and you live in ([\w\s]+?, \d{5})\b",
        r"My name is \1 and I live in \2", text,
    )
    text = re.sub(r"\bYour name is\b", "My name is", text)
    text = re.sub(r"\byou'd\b", "I'd", text)
    text = re.sub(r"\bYou\b", "I", text)
    text = re.sub(r"\byour\b", "my", text)
    return text


def _extract_order_id_sequence(reason: str) -> list[str]:
    """Extract scripted order-id corrections from tau3 reason text."""
    values = []
    first = re.search(r"provide ([A-Za-z#]?\d+) first", reason, re.IGNORECASE)
    if first:
        values.append(first.group(1))

    corrected = re.search(
        r"made a mistake and provide ([A-Za-z#]?\d+)",
        reason,
        re.IGNORECASE,
    )
    if corrected:
        values.append(corrected.group(1))

    if "forgot the 'w'" in reason.lower() and values:
        corrected_value = values[-1].lstrip("#")
        if not corrected_value.upper().startswith("W"):
            values.append(f"#W{corrected_value}")

    return values


def _extract_vacuum_choice(reason: str) -> str | None:
    """Extract which vacuum variant the simulated user should mention."""
    lower = reason.lower()
    m = re.search(r"mention the ([\w -]+?) one", lower)
    if m and "vacuum" in lower:
        return m.group(1).strip()
    return None


def _resolve_user_from_db(user_id: str, db_path: str) -> dict | None:
    """Resolve a tau3 user_id to real first/last name and email from DB."""
    global _user_db_cache, _user_db_path
    if _user_db_cache is None or _user_db_path != db_path:
        with open(db_path, encoding="utf-8") as f:
            _user_db_cache = json.load(f)
        _user_db_path = db_path
    users = _user_db_cache.get("users", {}) if _user_db_cache else {}
    return users.get(user_id)


class TauUserSimulator:
    """Template-based user simulator for tau3 multi-turn conversations."""

    def __init__(self, task: dict, db_path: str | None = None) -> None:
        instructions = task["user_scenario"]["instructions"]
        self.name = _extract_name(instructions)
        self.email = _extract_email(instructions)
        self.zip_code = _extract_zip(instructions)

        # Resolve synthetic usernames (with underscores) to real DB names.
        # Also handles names like "Lucas (lucas_santos_6600)" and
        # "user noah_ito_3850" via _resolve_name_to_user_id.
        if db_path and self.name:
            resolved_id = (
                _resolve_name_to_user_id(self.name)
                or (self.name.replace(" ", "_").lower() if " " in self.name else None)
            )
            lookup_id = resolved_id or self.name
            user_record = _resolve_user_from_db(lookup_id, db_path)
            if user_record:
                real_name = user_record.get("name", {})
                first = real_name.get("first_name", "")
                last = real_name.get("last_name", "")
                if first and last:
                    self.name = f"{first} {last}"
                # Also resolve email if available
                if not self.email:
                    self.email = user_record.get("email")

        self._reason = _to_first_person(instructions.get("reason_for_call", ""))
        raw_reason = instructions.get("reason_for_call", "") or ""
        self._unknown_info = instructions.get("unknown_info", "") or ""
        self._email_asked_count = 0
        self._name_asked_count = 0
        self._order_id_sequence = _extract_order_id_sequence(raw_reason)
        self._order_id_response_count = 0
        self._vacuum_choice = _extract_vacuum_choice(raw_reason)
        self._wants_canister_replacement = "canister" in raw_reason.lower()
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

        if question_type == "confirmation":
            return "Yes, I confirm. Please proceed."

        if question_type == "order_id" and self._order_id_sequence:
            idx = min(self._order_id_response_count, len(self._order_id_sequence) - 1)
            order_id = self._order_id_sequence[idx]
            self._order_id_response_count += 1
            if idx == 0:
                return f"The order ID is {order_id}."
            if idx == 1:
                return f"I made a mistake. The order ID is {order_id}."
            return f"I forgot the W at the beginning. The order ID is {order_id}."

        if question_type == "vacuum" and self._vacuum_choice:
            return f"The {self._vacuum_choice} one."

        if question_type == "payment_method":
            method = self._select_payment_method(agent_message)
            if method:
                return f"Please send it to {method}."
            if any(w in lower for w in _CONFIRMATION_KEYWORDS):
                return "Yes, I confirm. Please proceed."

        if question_type == "replacement_choice" and self._wants_canister_replacement:
            item_id = self._select_item_for_option(agent_message, "canister")
            if item_id:
                return f"The canister one, item {item_id}."
            return "The canister one."

        if question_type == "generic_help":
            return self._carry_on_response()

        return None

    def _detect_question_type(self, agent_message_lower: str) -> Optional[str]:
        if self._is_vacuum_question(agent_message_lower):
            return "vacuum"
        if self._is_payment_method_question(agent_message_lower):
            return "payment_method"
        if self._is_order_id_request(agent_message_lower):
            return "order_id"
        if self._is_poem_prompt(agent_message_lower):
            return "generic_help"
        if any(w in agent_message_lower for w in _NAME_KEYWORDS):
            return "name"
        if any(w in agent_message_lower for w in _CONFIRMATION_KEYWORDS):
            return "confirmation"
        if self._wants_canister_replacement and any(
            w in agent_message_lower for w in _REPLACEMENT_CHOICE_KEYWORDS
        ):
            return "replacement_choice"
        if any(w in agent_message_lower for w in _EMAIL_KEYWORDS):
            return "email"
        if any(w in agent_message_lower for w in _GENERIC_HELP_KEYWORDS):
            return "generic_help"
        return None

    def _is_order_id_request(self, agent_message_lower: str) -> bool:
        if any(w in agent_message_lower for w in _ORDER_ID_RETRY_KEYWORDS):
            return True
        if not any(w in agent_message_lower for w in _ORDER_ID_KEYWORDS):
            return False
        return any(w in agent_message_lower for w in _ORDER_ID_REQUEST_KEYWORDS)

    def _is_poem_prompt(self, agent_message_lower: str) -> bool:
        if "intended task" not in self._reason.lower():
            return False
        return any(w in agent_message_lower for w in _POEM_PROMPT_KEYWORDS)

    @staticmethod
    def _is_payment_method_question(agent_message_lower: str) -> bool:
        if any(w in agent_message_lower for w in _PAYMENT_METHOD_KEYWORDS):
            return True
        asks_refund_destination = (
            "refund" in agent_message_lower
            and any(
                method in agent_message_lower
                for method in ("paypal", "gift card", "gift_card", "credit card")
            )
        )
        return asks_refund_destination and any(
            w in agent_message_lower
            for w in ("which", "would you like", "where", "go to", "send")
        )

    @staticmethod
    def _is_vacuum_question(agent_message_lower: str) -> bool:
        if not any(w in agent_message_lower for w in _VACUUM_KEYWORDS):
            return False
        return any(
            w in agent_message_lower
            for w in (
                "which vacuum",
                "which one",
                "which item",
                "what vacuum",
                "would you like to return",
                "do you mean",
            )
        )

    def _carry_on_response(self) -> str:
        match = re.search(
            r"intended task,? which is to (.+)",
            self._reason,
            re.IGNORECASE,
        )
        if match:
            return "I want to " + match.group(1).strip()
        return self._reason

    @staticmethod
    def _select_payment_method(agent_message: str) -> str | None:
        methods = _PAYMENT_METHOD_PATTERN.findall(agent_message)
        if not methods:
            return None
        for method in methods:
            if method.lower().startswith("paypal_"):
                return method
        return methods[0]

    @staticmethod
    def _select_item_for_option(agent_message: str, option_keyword: str) -> str | None:
        pattern = re.compile(
            rf"(?:item\s+)?(\d{{8,}})[^.。\n]*\b{re.escape(option_keyword)}\b",
            re.IGNORECASE,
        )
        match = pattern.search(agent_message)
        if match:
            return match.group(1)
        return None
