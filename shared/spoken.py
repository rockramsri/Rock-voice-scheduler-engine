"""Human phrasing for shift times ("Tuesday 8am to 4pm"), shared by voice + SMS."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def spoken_when(starts_iso: str, ends_iso: str, tz: str = "America/New_York") -> str:
    starts = datetime.fromisoformat(starts_iso).astimezone(ZoneInfo(tz))
    ends = datetime.fromisoformat(ends_iso).astimezone(ZoneInfo(tz))
    return f"{starts.strftime('%A')} {_clock(starts)} to {_clock(ends)}"


def _clock(dt: datetime) -> str:
    hour = dt.strftime("%-I")
    minutes = dt.strftime(":%M") if dt.minute else ""
    return f"{hour}{minutes}{dt.strftime('%p').lower()}"
