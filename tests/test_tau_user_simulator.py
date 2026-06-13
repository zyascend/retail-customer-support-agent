"""Tests for TauUserSimulator."""

from app.eval.tau_user_simulator import (
    TauUserSimulator,
    _extract_email,
    _extract_name,
    _extract_zip,
)

NAME_ZIP_TASK = {
    "id": "0",
    "user_scenario": {
        "instructions": {
            "reason_for_call": "You want to exchange items in your order.",
            "known_info": "You are Yusuf Rossi in zip code 19122.",
            "unknown_info": "You do not remember your email address.",
        }
    },
}

NAME_EMAIL_TASK = {
    "id": "10",
    "user_scenario": {
        "instructions": {
            "reason_for_call": "You want to return items.",
            "known_info": "You are mia_garcia_4516 (mia.garcia2723@example.com).",
            "unknown_info": None,
        }
    },
}

EMAIL_TASK = {
    "id": "13",
    "user_scenario": {
        "instructions": {
            "reason_for_call": "You want to cancel an order.",
            "known_info": "You are mia_garcia_4516 with email mia.garcia2723@example.com",
            "unknown_info": None,
        }
    },
}


class TestExtractors:
    def test_extract_name_from_name_zip(self):
        assert _extract_name(NAME_ZIP_TASK["user_scenario"]["instructions"]) == "Yusuf Rossi"

    def test_extract_name_from_name_email_parens(self):
        assert _extract_name(NAME_EMAIL_TASK["user_scenario"]["instructions"]) == "mia_garcia_4516"

    def test_extract_email_from_email_format(self):
        assert _extract_email(EMAIL_TASK["user_scenario"]["instructions"]) == "mia.garcia2723@example.com"

    def test_extract_zip(self):
        assert _extract_zip(NAME_ZIP_TASK["user_scenario"]["instructions"]) == "19122"

    def test_extract_email_from_parens(self):
        assert _extract_email(NAME_EMAIL_TASK["user_scenario"]["instructions"]) == "mia.garcia2723@example.com"

    def test_extract_email_none_when_missing(self):
        assert _extract_email(NAME_ZIP_TASK["user_scenario"]["instructions"]) is None


class TestTauUserSimulator:
    def test_initial_message_for_name_zip(self):
        sim = TauUserSimulator(NAME_ZIP_TASK)
        msg = sim.initial_message()
        assert "exchange" in msg.lower()
        assert "Yusuf Rossi" in msg
        assert "19122" in msg
        assert "my name" in msg.lower()

    def test_initial_message_for_email_task(self):
        sim = TauUserSimulator(NAME_EMAIL_TASK)
        msg = sim.initial_message()
        assert "return" in msg.lower()
        assert "mia.garcia2723@example.com" in msg

    def test_respond_to_email_question_with_email(self):
        sim = TauUserSimulator(EMAIL_TASK)
        response = sim.respond("What is your email address?")
        assert response is not None
        assert "mia.garcia2723@example.com" in response

    def test_respond_to_email_question_without_email(self):
        sim = TauUserSimulator(NAME_ZIP_TASK)
        response = sim.respond("Can you provide your email?")
        assert response is not None
        assert "don't remember" in response.lower() or "do not remember" in response.lower()

    def test_respond_to_name_question(self):
        sim = TauUserSimulator(NAME_ZIP_TASK)
        response = sim.respond("What is your name?")
        assert response is not None
        assert "Yusuf Rossi" in response

    def test_respond_no_match_returns_none(self):
        sim = TauUserSimulator(NAME_ZIP_TASK)
        response = sim.respond("Your order has been processed.")
        assert response is None
