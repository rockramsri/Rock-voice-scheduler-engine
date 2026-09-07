"""Deterministic (then LLM-proposed) intent for inbound offer replies.

The webhook fast path uses `classify_offer_reply`. The SMS agent may ask an
LLM to label leftover text, but an accept is honored only when the
affirmative regex also matches somewhere — the model proposes, regex enforces.
"""

from __future__ import annotations

import re
from typing import Literal

Intent = Literal["accept", "decline", "question", "other"]

_YES_EMOJI = ("👍", "✅", "🙌", "👌", "💯")
_PUNCT = re.compile(r"[^\w\s']+", re.UNICODE)
_SPACE = re.compile(r"\s+")
_APOS = re.compile(r"[’`]")

# Leading-token accept / decline (after normalize).
_ACCEPT_HEAD = re.compile(
    r"^(yes|yeah|yep|yup|sure|ok|okay|y|i'?ll take it|i can take it|"
    r"i can do it|count me in|confirm)\b"
)
_ACCEPT_ANY = re.compile(
    r"\b(yes|yeah|yep|yup|sure|ok|okay|i'?ll take it|i can take it|"
    r"i can do it|count me in|confirm)\b"
)
_DECLINE_HEAD = re.compile(
    r"^(no|n|nope|nah|can'?t|cannot|pass|not this time)\b"
)
_NEGATION = re.compile(
    r"\b(no|not|can'?t|cannot|unable|but|won't|wont)\b"
)


def normalize_sms(text: str) -> str:
    """Lowercase, map yes-emoji, strip punctuation, collapse whitespace."""
    raw = (text or "").strip()
    for emoji in _YES_EMOJI:
        if emoji in raw:
            raw = raw.replace(emoji, " yes ")
    raw = _APOS.sub("'", raw)
    raw = raw.lower()
    raw = _PUNCT.sub(" ", raw)
    return _SPACE.sub(" ", raw).strip()


def has_negation(text: str) -> bool:
    return bool(_NEGATION.search(normalize_sms(text)))


def accept_token_present(text: str) -> bool:
    return bool(_ACCEPT_ANY.search(normalize_sms(text)))


def classify_offer_reply(text: str) -> Literal["accept", "decline"] | None:
    """Regex layer: accept / decline / None (ambiguous → LLM or agent)."""
    norm = normalize_sms(text)
    if not norm:
        return None
    if _ACCEPT_HEAD.match(norm) and not has_negation(norm):
        return "accept"
    if _DECLINE_HEAD.match(norm):
        return "decline"
    return None


async def classify_with_llm(text: str) -> Intent:
    """Constrained labeler. Fail-soft to 'other' if the model is unavailable."""
    from pydantic_ai import Agent

    from shared.config import WORKPLANE_MODEL

    agent = Agent(WORKPLANE_MODEL, output_type=Intent, instructions=(
        "Classify this SMS reply to a home-health shift offer. "
        "accept = they are taking the shift. decline = they are passing. "
        "question = they asked something. other = anything else, including "
        "mixed yes-but-no. Reply with only the label."))
    try:
        result = await agent.run(text)
        return result.output
    except Exception:
        return "other"


async def maybe_accept_from_classifier(text: str) -> bool:
    """True only when the LLM says accept AND an affirmative regex hits."""
    if classify_offer_reply(text) == "accept":
        return True
    if not accept_token_present(text) or has_negation(text):
        return False
    return await classify_with_llm(text) == "accept"
