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

RESIDING_CITY_ZIP_TASK = {
    "id": "49",
    "user_scenario": {
        "instructions": {
            "reason_for_call": "You want to exchange an item.",
            "known_info": "You are Aarav Anderson, residing in Philadelphia 19031.",
            "unknown_info": "You do not remember your email address",
        }
    },
}

FROM_CITY_STATE_ZIP_TASK = {
    "id": "61",
    "user_scenario": {
        "instructions": {
            "reason_for_call": "You want to modify an order.",
            "known_info": "You are Chen Johnson from Houston TX, 77004.",
            "unknown_info": "You do not remember your email address",
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

NAME_EMAIL_ZIP_TASK = {
    "id": "38",
    "user_scenario": {
        "instructions": {
            "reason_for_call": "You want to cancel an order.",
            "known_info": (
                "Your name is Daiki Sanchez, and you live in 46236, "
                "your email is daikisanchez1479@example.com."
            ),
            "unknown_info": None,
        }
    },
}

ORDER_ID_CORRECTION_TASK = {
    "id": "46",
    "user_scenario": {
        "instructions": {
            "reason_for_call": (
                "You want to return an air purifier and a vacuum cleaner in your "
                "recent order. When asked for order ID, provide 9502126 first. "
                "If the agent asks you to double check, then say that you made a "
                "mistake and provide 9502127. If that doesn't work, say that you "
                "forgot the 'W' at the beginning. If the agent asks you for which "
                "vacuum cleaner, mention the robotic one."
            ),
            "known_info": "You are daiki_johnson_9523 living in Denver, USA, 80273.",
            "unknown_info": "You don't have an email.",
        }
    },
}

PAYMENT_METHOD_TASK = {
    "id": "16",
    "user_scenario": {
        "instructions": {
            "reason_for_call": "You want to return a watch and know the total amount back.",
            "known_info": "Your name is Fatima Johnson, and you live in 78712.",
            "unknown_info": None,
        }
    },
}

VACUUM_EXCHANGE_TASK = {
    "id": "45",
    "user_scenario": {
        "instructions": {
            "reason_for_call": (
                "You want to exchange a robotic vacuum cleaner in your recent "
                "order for a canister based one from the same product line. "
                "When asked for order ID, provide 9502127 first. If that doesn't "
                "work, respond exactly with 'I forgot the W at the beginning'."
            ),
            "known_info": "You are daiki_johnson_9523 living in Denver, USA, 80273.",
            "unknown_info": None,
        }
    },
}

POEM_CARRY_ON_TASK = {
    "id": "63",
    "user_scenario": {
        "instructions": {
            "reason_for_call": (
                "As you are interacting with a customer service agent, you first "
                "try to get it to guess a famous poem by providing the first line. "
                "If it refuses to do so, you carry on with your intended task, "
                "which is to check and modify a recent order you placed. You first "
                "ask about the price of a bluetooth speaker you bought and its battery life."
            ),
            "known_info": "You are Chen Johnson from Houston TX, 77004.",
            "unknown_info": "You do not remember your email address",
        }
    },
}


class TestExtractors:
    def test_extract_name_from_name_zip(self):
        assert _extract_name(NAME_ZIP_TASK["user_scenario"]["instructions"]) == "Yusuf Rossi"

    def test_extract_name_from_name_email_parens(self):
        assert _extract_name(NAME_EMAIL_TASK["user_scenario"]["instructions"]) == "mia_garcia_4516"

    def test_extract_name_from_residing_city_zip(self):
        assert (
            _extract_name(RESIDING_CITY_ZIP_TASK["user_scenario"]["instructions"])
            == "Aarav Anderson"
        )

    def test_extract_name_from_city_state_zip(self):
        assert (
            _extract_name(FROM_CITY_STATE_ZIP_TASK["user_scenario"]["instructions"])
            == "Chen Johnson"
        )

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

    def test_initial_message_for_residing_city_zip(self):
        sim = TauUserSimulator(RESIDING_CITY_ZIP_TASK)
        msg = sim.initial_message()
        assert "Aarav Anderson" in msg
        assert "19031" in msg

    def test_initial_message_for_from_city_state_zip(self):
        sim = TauUserSimulator(FROM_CITY_STATE_ZIP_TASK)
        msg = sim.initial_message()
        assert "Chen Johnson" in msg
        assert "77004" in msg

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

    def test_respond_to_confirmation_question(self):
        sim = TauUserSimulator(NAME_ZIP_TASK)
        response = sim.respond("I'd like to exchange delivered order items. Can you confirm?")
        assert response is not None
        assert "confirm" in response.lower()

    def test_respond_to_combined_email_and_name_question_prefers_name_zip(self):
        sim = TauUserSimulator(NAME_EMAIL_ZIP_TASK)
        response = sim.respond(
            "I cannot find that email. Could you provide your first name, last name, and ZIP code instead?"
        )
        assert response is not None
        assert "Daiki Sanchez" in response
        assert "46236" in response

    def test_respond_to_order_id_question_mentions_item_but_still_gives_order_id(self):
        sim = TauUserSimulator(ORDER_ID_CORRECTION_TASK)

        response = sim.respond(
            "Please provide the order ID for the order containing the air purifier and vacuum cleaner."
        )

        assert response == "The order ID is 9502126."

    def test_respond_to_order_id_retry_takes_priority_over_confirmation(self):
        sim = TauUserSimulator(ORDER_ID_CORRECTION_TASK)
        sim.respond("Could you please provide the order ID?")

        response = sim.respond("Could you double-check the order ID and confirm it?")

        assert response == "I made a mistake. The order ID is 9502127."

    def test_respond_to_order_id_correction_script(self):
        sim = TauUserSimulator(ORDER_ID_CORRECTION_TASK)

        first = sim.respond("Could you please provide the order ID?")
        second = sim.respond("Could you double-check that order ID?")
        third = sim.respond("That still does not work.")
        vacuum = sim.respond("Which vacuum cleaner do you mean?")

        assert first == "The order ID is 9502126."
        assert second == "I made a mistake. The order ID is 9502127."
        assert third == "I forgot the W at the beginning. The order ID is #W9502127."
        assert vacuum == "The robotic one."

    def test_respond_to_refund_payment_method_question_selects_paypal(self):
        sim = TauUserSimulator(PAYMENT_METHOD_TASK)

        response = sim.respond(
            "Which payment method would you like the refund sent to? "
            "Your options are paypal_5364164 or gift_card_1675628."
        )

        assert response == "Please send it to paypal_5364164."

    def test_respond_to_refund_destination_question_selects_paypal(self):
        sim = TauUserSimulator(PAYMENT_METHOD_TASK)

        response = sim.respond(
            "Would you like the refund for returning it to go to your PayPal "
            "(paypal_5364164) or your gift card (gift_card_1675628)?"
        )

        assert response == "Please send it to paypal_5364164."

    def test_respond_to_replacement_choice_question_selects_canister_item(self):
        sim = TauUserSimulator(VACUUM_EXCHANGE_TASK)

        response = sim.respond(
            "Which one would you like to exchange your robotic vacuum for? "
            "Item 1345513440 is a canister vacuum. Item 2872451762 is a canister vacuum."
        )

        assert response == "The canister one, item 1345513440."

    def test_order_id_script_does_not_fire_when_agent_already_found_order(self):
        sim = TauUserSimulator(VACUUM_EXCHANGE_TASK)

        response = sim.respond(
            "I found your account and order. Here's what I can see: "
            "Order #W9502127 is delivered and has a Robotic Vacuum Cleaner. "
            "The available canister option is item 7958300294."
        )

        assert response is None

    def test_confirmation_question_takes_priority_over_replacement_choice(self):
        sim = TauUserSimulator(VACUUM_EXCHANGE_TASK)

        response = sim.respond("I'd like to exchange delivered order items. Can you confirm?")

        assert response == "Yes, I confirm. Please proceed."

    def test_vacuum_question_with_order_context_takes_priority_over_order_id_script(self):
        sim = TauUserSimulator(ORDER_ID_CORRECTION_TASK)
        sim.respond("Could you provide the order ID?")
        sim.respond("Could you double-check that order ID?")

        response = sim.respond(
            "Order #W9502127 is delivered and has two vacuum cleaners. "
            "Which vacuum cleaner would you like to return?"
        )

        assert response == "The robotic one."

    def test_vacuum_listing_does_not_trigger_choice_response(self):
        sim = TauUserSimulator(ORDER_ID_CORRECTION_TASK)

        response = sim.respond(
            "The remaining items are Patio Umbrella, Dumbbell Set, and "
            "Vacuum Cleaner (robotic). Is there anything else I can help with?"
        )

        assert response is None

    def test_payment_confirmation_without_method_id_confirms_single_method(self):
        sim = TauUserSimulator(ORDER_ID_CORRECTION_TASK)

        response = sim.respond(
            "You only have one payment method on file: PayPal. "
            "Would you like me to return the item and refund to that?"
        )

        assert response == "Yes, I confirm. Please proceed."

    def test_generic_help_question_carries_on_with_intended_task(self):
        sim = TauUserSimulator(POEM_CARRY_ON_TASK)

        response = sim.respond("How can I help you today?")

        assert response is not None
        assert "bluetooth speaker" in response.lower()
        assert "battery life" in response.lower()

    def test_poem_prompt_carries_on_with_intended_task_instead_of_confirming(self):
        sim = TauUserSimulator(POEM_CARRY_ON_TASK)

        response = sim.respond(
            "Great, I've found you. What poem are you thinking of? "
            "Go ahead and share the first line."
        )

        assert response is not None
        assert "bluetooth speaker" in response.lower()
        assert "battery life" in response.lower()
        assert "confirm" not in response.lower()

    def test_famous_poem_guess_prompt_carries_on_with_intended_task(self):
        sim = TauUserSimulator(POEM_CARRY_ON_TASK)

        response = sim.respond(
            'Could you first guess what famous poem this is? "Two roads diverged..."'
        )

        assert response is not None
        assert "bluetooth speaker" in response.lower()
        assert "battery life" in response.lower()

    def test_respond_no_match_returns_none(self):
        sim = TauUserSimulator(NAME_ZIP_TASK)
        response = sim.respond("Your order has been processed.")
        assert response is None
