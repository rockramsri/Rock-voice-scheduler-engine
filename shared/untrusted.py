"""Sanitize free-text that originated from a nurse (decline reasons, notes).

Untrusted text may ride a user turn or a read-only tool return. It must never
be interpolated into Agent.instructions. Cap + token-strip is the last line
of defense before a note is shown to a model.
"""

from __future__ import annotations

import re

_BANNED = re.compile(r"(system|instruction|ignore)", re.IGNORECASE)
_NEWLINES = re.compile(r"[\r\n]+")


def sanitize_note(note: str, *, limit: int = 200) -> str:
    """Collapse whitespace, drop jailbreak tokens, cap length."""
    text = _NEWLINES.sub(" ", (note or "")).strip()
    text = _BANNED.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]
