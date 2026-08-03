"""Phone hygiene — one guard shared by every outbound touch point.

Fake (555) and malformed numbers must never reach Twilio/TextBelt: they
burn credits and litter the event log with provider errors. Callers log
these as "skipped_fake_number" instead.
"""


def is_fake(phone: str) -> bool:
    if not phone.startswith("+"):
        return True
    national = phone.removeprefix("+1")
    digits = "".join(c for c in national if c.isdigit())
    if digits.startswith("555"):
        return True
    # US numbers must carry exactly 10 national digits (catches typos).
    return phone.startswith("+1") and len(digits) != 10
