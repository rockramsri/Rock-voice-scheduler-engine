"""Dispatch worker — watches the shifts table and runs the outreach ladder.

Run: python -m workers.dispatch_worker

One process, many short bursts: claim due shifts (SKIP LOCKED inside
Postgres), do seconds of work, write the checkpoint, release. Waits are
timestamps on the row — never a sleeping worker — so any worker resumes
any shift after any crash. Rung execution lives in workers/rungs.py.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from data import db
from shared import config
from workers import ladder, rungs, scoring

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)-18s %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("worker")

# Backoff after a poll-level failure (e.g. a transient Supabase error on the
# claim) so one blip can't spin the loop or take the worker down.
ERROR_BACKOFF_SECONDS = 5.0


async def run() -> None:
    worker_id = f"w-{uuid.uuid4().hex[:6]}"
    agency = await db.fetch_agency()
    log.info("%s watching shifts for %s (poll %.0fs)",
             worker_id, agency["name"], config.WORKER_POLL_SECONDS)
    while True:
        try:
            shifts = await db.claim_shifts(worker_id)
        except Exception:  # a transient claim error must not kill the loop
            log.exception("claim_shifts failed; backing off %.0fs", ERROR_BACKOFF_SECONDS)
            await asyncio.sleep(ERROR_BACKOFF_SECONDS)
            continue
        for shift in shifts:
            try:
                await _handle(shift, agency)
            except Exception:  # one bad shift must not kill the loop
                log.exception("burst failed for shift %s", shift["id"])
        await asyncio.sleep(config.WORKER_POLL_SECONDS)


async def _handle(shift: dict, agency: dict) -> None:
    log.info("claimed shift %s [%s] rung=%d", shift["id"][:8], shift["status"], shift["rung"])
    if shift["status"] == "callout":
        await _start_offering(shift, agency)
    elif shift["status"] == "offers_out":
        await _advance(shift, agency)


async def _start_offering(shift: dict, agency: dict) -> None:
    """Score prospects, write the scoreboard, hand over to the ladder."""
    nurses = await db.fetch_active_nurses()
    busy = await db.overlapping_nurse_ids(shift["starts_at"], shift["ends_at"])
    prospects = scoring.rank(shift, nurses, busy | {shift["callout_nurse_id"]}, agency)
    if not prospects:
        await rungs.escalate(shift, "no eligible prospects")
        return
    await db.insert_offers([{
        "shift_id": shift["id"], "nurse_id": p.nurse_id,
        "score": p.score, "reason": p.reason,
    } for p in prospects])
    names = ", ".join(f"{p.name} ({p.score})" for p in prospects)
    log.info("shift %s scored -> %s", shift["id"][:8], names)
    await db.log_event("worker", "prospects_scored", shift_id=shift["id"],
                       payload={"prospects": names})
    await db.release_shift(shift["id"], status="offers_out", rung=0,
                           next_action_at=rungs.now().isoformat())


async def _advance(shift: dict, agency: dict) -> None:
    """Execute the next rung; the plan adapts to the CURRENT lead time."""
    lead = _lead_hours(shift)
    plan = ladder.pick_plan(lead, agency)
    rung_no = shift["rung"] + 1
    if rung_no <= len(plan):
        rung = plan[rung_no - 1]
    elif plan[-1].channels == ("voice",):
        rung = plan[-1]  # voice rung repeats: one prospect per visit
    else:
        await rungs.escalate(shift, "ladder exhausted")
        return
    if "voice" in rung.channels:
        await rungs.voice_rung(shift, rung, agency, lead)
    else:
        await rungs.message_rung(shift, rung, agency)


def _lead_hours(shift: dict) -> float:
    starts = datetime.fromisoformat(shift["starts_at"])
    return (starts - rungs.now()).total_seconds() / 3600


if __name__ == "__main__":
    asyncio.run(run())
