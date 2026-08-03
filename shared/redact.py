"""PHI-safe redaction helpers for event logging.

The events table can hold verbatim SMS bodies and callout reasons — great for
the live demo, unacceptable for a production PHI posture. These helpers turn
free text into a non-reversible placeholder and mask phone numbers to their
last four digits. They are applied at one choke point (data.db.log_event),
gated by shared.config.LOG_MESSAGE_CONTENT, so a single flag flips prod safe.
"""

from __future__ import annotations

import hashlib


def scrub_text(s: str | None) -> str:
    """Replace free text with a length + short-hash placeholder (no content).

    The hash lets you tell two different messages apart in the log without ever
    storing what they said; the length hints at message size for debugging.
    """
    if not s:
        return ""
    digest = hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]
    return f"[redacted {len(s)} chars sha256:{digest}]"


def mask_phone(p: str | None) -> str:
    """Keep only the last four digits of a phone number; mask the rest."""
    if not p:
        return ""
    prefix = "whatsapp:" if p.startswith("whatsapp:") else ""
    digits = "".join(c for c in p if c.isdigit())
    if not digits:
        return p  # nothing numeric to mask — return untouched
    return f"{prefix}***{digits[-4:]}"
