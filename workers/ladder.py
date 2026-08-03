"""Outreach ladder — lead time picks the plan, quiet hours gate the calls.

Pure functions only (no I/O) so the escalation policy is trivially
testable. The plan is re-picked from CURRENT lead time on every rung, so a
shift that drifts closer automatically gets the more aggressive ladder.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Rung:
    number: int
    channels: tuple[str, ...]   # "sms" | "whatsapp" | "voice"
    wait_minutes: int           # silence to allow AFTER this rung fires


RELAXED = (
    Rung(1, ("sms",), 60),
    Rung(2, ("sms",), 300),
    Rung(3, ("whatsapp",), 120),
    Rung(4, ("voice",), 3),     # voice rung repeats: one prospect per visit
)
NORMAL = (
    Rung(1, ("sms",), 30),
    Rung(2, ("whatsapp",), 120),
    Rung(3, ("voice",), 3),
)
URGENT = (
    Rung(1, ("sms", "whatsapp"), 10),
    Rung(2, ("voice",), 3),
)


def pick_plan(lead_hours: float, agency: dict) -> tuple[Rung, ...]:
    if lead_hours <= agency["urgent_lead_hours"]:
        return URGENT
    if lead_hours >= agency["relaxed_lead_hours"]:
        return RELAXED
    return NORMAL


def in_call_window(now: datetime, agency: dict) -> bool:
    """Calls allowed between quiet_end (06) and quiet_start (22), agency-local."""
    hour = now.astimezone(ZoneInfo(agency["timezone"])).hour
    return agency["quiet_end"] <= hour < agency["quiet_start"]


def next_call_window(now: datetime, agency: dict) -> datetime:
    """Earliest moment calling becomes allowed again (now, if already allowed)."""
    if in_call_window(now, agency):
        return now
    local = now.astimezone(ZoneInfo(agency["timezone"]))
    start = local.replace(hour=agency["quiet_end"], minute=0, second=0, microsecond=0)
    if local.hour >= agency["quiet_start"]:
        start += timedelta(days=1)
    return start
