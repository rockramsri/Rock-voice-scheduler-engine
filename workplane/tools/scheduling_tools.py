"""Scheduling facade tools attached to the FrontDesk voice agent.

Intent-shaped and engine-agnostic: the voice plane calls these without
knowing that Supabase sits behind them. Docstrings below ARE the LLM tool
schema — keep them one tight sentence. report_callout is the trigger for
the whole backfill machine: one guarded row update wakes the worker.
"""

import logging

from livekit.agents import function_tool

from data import db
from shared.spoken import spoken_when
from workplane.agents.matching_agent import rank_nurses

log = logging.getLogger("workplane.tools")


@function_tool
async def find_nurse(specialty: str, area: str) -> str:
    """Find the top available nurses for a care specialty near a town or area."""
    log.info("tool find_nurse(specialty=%r, area=%r)", specialty, area)
    matches = await rank_nurses(specialty, area)
    if not matches:
        return f"No {specialty} nurses are available near {area} right now."
    spoken = "; ".join(f"{m.name} — {m.reason}" for m in matches[:3])
    return f"Top matches: {spoken}."


@function_tool
async def get_shift(nurse_name: str) -> str:
    """Look up a nurse's next scheduled shift by their name."""
    log.info("tool get_shift(nurse_name=%r)", nurse_name)
    nurse = await db.find_nurse_by_name(nurse_name)
    if nurse is None:
        return f"No shift found — there is no nurse called {nurse_name} on the roster."
    shift = await db.next_shift_for(nurse["id"])
    if shift is None:
        return f"{nurse['name']} has no upcoming shift scheduled."
    when = spoken_when(shift["starts_at"], shift["ends_at"])
    # Speak specialty + time + area only — never the patient's name (PHI),
    # matching what the SMS agent and offer texts already disclose.
    return (f"{nurse['name']}'s next shift is a {shift['specialty']} visit "
            f"{when} in {shift['area']}.")


@function_tool
async def report_callout(nurse_name: str, reason: str) -> str:
    """Record that a nurse cannot make their next shift; replacement outreach starts automatically."""
    log.info("tool report_callout(nurse_name=%r, reason=%r)", nurse_name, reason)
    nurse = await db.find_nurse_by_name(nurse_name)
    if nurse is None:
        return f"There is no nurse called {nurse_name} on the roster."
    shift = await db.next_shift_for(nurse["id"])
    if shift is None:
        return f"{nurse['name']} has no upcoming shift to call out from."
    if not await db.record_callout(shift["id"], nurse["id"], reason):
        return "That shift is already being handled."
    await db.log_event("frontdesk", "callout_recorded", shift_id=shift["id"],
                       nurse_id=nurse["id"], payload={"reason": reason})
    when = spoken_when(shift["starts_at"], shift["ends_at"])
    return (f"Callout recorded for {nurse['name']}'s {when} shift. Replacement "
            "outreach has already started — nothing else is needed from them.")
