"""Scheduling facade tools attached to the FrontDesk voice agent.

Intent-shaped and engine-agnostic: the voice plane calls these without
knowing that Supabase sits behind them. Docstrings below ARE the LLM tool
schema — keep them one tight sentence. report_my_callout is the trigger for
the whole backfill machine: one guarded row update wakes the worker.

Tools are built per call as closures over the caller's OWN roster rows
(resolved from caller ID in voice/entry.py). Identity is baked in: no free
nurse_name can reach a nurse who does not share this phone, so a prompt
injection can at most act on the caller's own record.
"""

import logging
from datetime import datetime

from livekit.agents import function_tool

from data import db
from shared.spoken import spoken_when
from workplane import emr

log = logging.getLogger("workplane.tools")


def _describe(shift: dict) -> str:
    when = spoken_when(shift["starts_at"], shift["ends_at"])
    return f"{shift['specialty']} visit {when} in {shift['area']}"


def match_shift_ref(shifts: list[dict], shift_ref: str) -> dict | None:
    """Pick one upcoming shift from a spoken day, area, specialty, or id prefix."""
    raw = (shift_ref or "").strip().lower()
    if not raw:
        return None
    if raw in {"next", "the next one", "upcoming", "first"}:
        return shifts[0] if shifts else None
    hits: list[dict] = []
    for shift in shifts:
        starts = datetime.fromisoformat(shift["starts_at"])
        dow = starts.strftime("%A").lower()
        short = starts.strftime("%a").lower()
        when = spoken_when(shift["starts_at"], shift["ends_at"]).lower()
        sid = shift["id"].replace("-", "").lower()
        if (dow in raw or short in raw or raw in when or raw in sid
                or raw.replace("-", "") in sid
                or (shift.get("specialty") or "").lower() in raw
                or (shift.get("area") or "").lower() in raw):
            hits.append(shift)
    if len(hits) == 1:
        return hits[0]
    day_hits = [s for s in hits
                if datetime.fromisoformat(s["starts_at"]).strftime("%A").lower() in raw]
    if len(day_hits) == 1:
        return day_hits[0]
    return None


def build_scheduling_tools(matches: list[dict]) -> list:
    """Caller-scoped scheduling tools closed over the caller's own roster rows.

    `matches` are the nurse rows whose phone matched the caller ID (0, 1, or
    several). The returned tools can only ever read or mutate one of those
    rows — a nurse outside this phone is unreachable, not just discouraged.
    """
    allowed = {n["name"]: n for n in matches}

    def _resolve(nurse_name: str) -> dict | None:
        # Single owner: ignore the argument entirely (fully deterministic).
        # Shared phone: the name must already be one of THIS phone's nurses.
        if len(allowed) == 1:
            return next(iter(allowed.values()))
        return allowed.get(nurse_name)

    @function_tool
    async def get_my_next_shift(nurse_name: str = "") -> str:
        """Look up your own next scheduled shift."""
        log.info("tool get_my_next_shift(nurse_name=%r)", nurse_name)
        nurse = _resolve(nurse_name)
        if nurse is None:
            return ("I can only look up your own shift. Which of the names on "
                    "this number are you?")
        shift = await db.next_shift_for(nurse["id"])
        if shift is None:
            return f"{nurse['name']}, you have no upcoming shift scheduled."
        return (f"{nurse['name']}, your next shift is a {_describe(shift)}.")

    @function_tool
    async def list_my_upcoming_shifts(nurse_name: str = "") -> str:
        """List your next three scheduled shifts so you can pick one to call out."""
        log.info("tool list_my_upcoming_shifts(nurse_name=%r)", nurse_name)
        nurse = _resolve(nurse_name)
        if nurse is None:
            return ("I can only look up your own shifts. Which of the names on "
                    "this number are you?")
        upcoming = await db.upcoming_shifts_for(nurse["id"], limit=3)
        if not upcoming:
            return f"{nurse['name']}, you have no upcoming shifts scheduled."
        lines = [f"{i+1}. {_describe(s)}" for i, s in enumerate(upcoming)]
        return (f"{nurse['name']}, your next {len(upcoming)} shift"
                f"{'s' if len(upcoming) != 1 else ''}: " + " ".join(lines))

    @function_tool
    async def report_my_callout(shift_ref: str, reason: str, nurse_name: str = "") -> str:
        """Record that you cannot make one of your upcoming shifts; say which day or shift."""
        log.info("tool report_my_callout(shift_ref=%r, nurse_name=%r, reason=%r)",
                 shift_ref, nurse_name, reason)
        nurse = _resolve(nurse_name)
        if nurse is None:
            return ("I can only record a callout for you. Which of the names on "
                    "this number are you?")
        upcoming = await db.upcoming_shifts_for(nurse["id"], limit=3)
        if not upcoming:
            return f"{nurse['name']}, you have no upcoming shift to call out from."
        chosen = match_shift_ref(upcoming, shift_ref)
        if chosen is None and len(upcoming) == 1:
            chosen = upcoming[0]
        if chosen is None:
            listed = "; ".join(_describe(s) for s in upcoming)
            return (f"Which shift are you calling out from? You have: {listed}. "
                    "Say the day or the time.")
        if not await db.record_callout(chosen["id"], nurse["id"], reason):
            return "That shift is already being handled."
        await db.log_event("frontdesk", "callout_recorded", shift_id=chosen["id"],
                           nurse_id=nurse["id"], payload={"reason": reason})
        await emr.post_chart_event("callout_documented", chosen,
                                   nurse_id=nurse["id"], details={"reason": reason})
        return (f"Callout recorded for your {_describe(chosen)}, {nurse['name']}. "
                "Replacement outreach has already started — nothing else is "
                "needed from you.")

    return [get_my_next_shift, list_my_upcoming_shifts, report_my_callout]
