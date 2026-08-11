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

from livekit.agents import function_tool

from data import db
from shared.spoken import spoken_when

log = logging.getLogger("workplane.tools")


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
        when = spoken_when(shift["starts_at"], shift["ends_at"])
        # Speak specialty + time + area only — never the patient's name (PHI).
        return (f"{nurse['name']}, your next shift is a {shift['specialty']} "
                f"visit {when} in {shift['area']}.")

    @function_tool
    async def report_my_callout(reason: str, nurse_name: str = "") -> str:
        """Record that you cannot make your own next shift; replacement outreach starts automatically."""
        log.info("tool report_my_callout(nurse_name=%r, reason=%r)", nurse_name, reason)
        nurse = _resolve(nurse_name)
        if nurse is None:
            return ("I can only record a callout for you. Which of the names on "
                    "this number are you?")
        shift = await db.next_shift_for(nurse["id"])
        if shift is None:
            return f"{nurse['name']}, you have no upcoming shift to call out from."
        if not await db.record_callout(shift["id"], nurse["id"], reason):
            return "That shift is already being handled."
        await db.log_event("frontdesk", "callout_recorded", shift_id=shift["id"],
                           nurse_id=nurse["id"], payload={"reason": reason})
        when = spoken_when(shift["starts_at"], shift["ends_at"])
        return (f"Callout recorded for your {when} shift, {nurse['name']}. "
                "Replacement outreach has already started — nothing else is "
                "needed from you.")

    return [get_my_next_shift, report_my_callout]
