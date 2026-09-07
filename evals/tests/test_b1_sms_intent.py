"""B1 — natural-language SMS accept/decline, regex first (40 phrasings)."""

import pytest

from workplane.sms_intent import classify_offer_reply

ACCEPT = [
    "yes", "y", "YES!", "yeah", "yep", "yup", "sure", "ok", "okay",
    "I'll take it", "I can take it", "I can do it", "count me in",
    "confirm", "Yes I can take it", "yes please", "yeah I can",
    "sure thing", "👍", "okay yes",
]
DECLINE = [
    "no", "n", "NO.", "nope", "nah", "can't", "cannot", "pass",
    "not this time", "no thanks",
]
AMBIGUOUS = [
    "maybe", "what time again?", "how much does it pay?",
    "I'll think about it", "yes but not this weekend, no",
    "can I call you back", "who is the patient", "what area",
    "is this overtime", "hmm",
]


@pytest.mark.parametrize("text", ACCEPT)
def test_accept_phrasings(text):
    assert classify_offer_reply(text) == "accept", text


@pytest.mark.parametrize("text", DECLINE)
def test_decline_phrasings(text):
    assert classify_offer_reply(text) == "decline", text


@pytest.mark.parametrize("text", AMBIGUOUS)
def test_ambiguous_phrasings_fall_through(text):
    assert classify_offer_reply(text) is None, text


def test_counts_are_the_forty():
    assert len(ACCEPT) == 20 and len(DECLINE) == 10 and len(AMBIGUOUS) == 10
