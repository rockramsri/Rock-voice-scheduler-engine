"""Rung execution — one function per outreach step the worker can take.

Split from dispatch_worker so the claim/checkpoint loop and the actual
touching-of-humans stay separately readable. Every send is preceded by a
guarded write (offer rung bump or state claim), so crash-resume never
double-contacts anyone. Fake 555 numbers are skipped, never dialed.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from channels import outbound, sms
from data import db
from shared.phone import is_fake as _is_fake
from shared.spoken import spoken_when
from workers import ladder

log = logging.getLogger("worker.rungs")

CALLING_STALE = timedelta(minutes=3)


async def message_rung(shift: dict, rung: ladder.Rung, agency: dict) -> None:
    text = _offer_text(shift, agency)
    failed_only = True
    attempted = False
    for offer in await db.offers_for_shift(shift["id"], states=["scored", "messaged"]):
        channels = [c for c in rung.channels if c in _allowed_channels(offer)]
        if not channels:
            continue  # nurse is not comfortable with any channel in this rung
        retrying = bool(offer.get("last_send_error")) and offer.get("rung") == rung.number
        if retrying:
            if (offer.get("send_failures") or 0) >= 2:
                await db.log_event("worker", "offer_sent", shift_id=shift["id"],
                                   nurse_id=offer["nurse_id"], channel=offer.get("last_channel"),
                                   rung=rung.number, outcome="send_abandoned")
                continue
        elif not await db.bump_offer_rung(offer["id"], rung.number, "+".join(channels)):
            continue  # this rung already touched this offer (crash resume)
        attempted = True
        rung_ok = False
        for channel in channels:
            outcome = await _send(channel, offer["nurses"]["phone"], text)
            await db.log_event("worker", "offer_sent", shift_id=shift["id"],
                               nurse_id=offer["nurse_id"], channel=channel,
                               rung=rung.number, outcome=outcome)
            if outcome == "sent":
                rung_ok = True
                await db.clear_send_error(offer["id"])
            elif outcome.startswith("failed"):
                await db.record_send_failure(offer["id"], outcome)
        if rung_ok:
            failed_only = False
    if attempted and failed_only:
        next_at = now() + timedelta(seconds=60)
    else:
        next_at = now() + timedelta(minutes=rung.wait_minutes)
    await db.release_shift(shift["id"], status="offers_out", rung=rung.number,
                           next_action_at=next_at.isoformat())
    log.info("shift %s rung %d done, next check %s", shift["id"][:8], rung.number, next_at)


async def voice_rung(shift: dict, rung: ladder.Rung, agency: dict,
                     lead_hours: float) -> None:
    """One prospect per visit: call, wait for an outcome, come back for the next."""
    if not ladder.in_call_window(now(), agency):
        if lead_hours <= agency["urgent_lead_hours"]:
            await escalate(shift, "urgent shift inside quiet hours")
        else:
            window = ladder.next_call_window(now(), agency)
            await db.release_shift(shift["id"], status="offers_out", rung=rung.number,
                                   next_action_at=window.isoformat())
        return

    for offer in await db.offers_for_shift(shift["id"], states=["calling"]):
        touched_at = offer.get("last_touch_at")
        # A missing touch timestamp means we can't prove a call is still live:
        # treat it as stale and re-evaluate instead of crashing on fromisoformat.
        stale = (not touched_at
                 or now() - datetime.fromisoformat(touched_at) > CALLING_STALE)
        if stale:  # rang out / never answered / unknown
            await db.set_offer_state(offer["id"], "no_answer", ["calling"])
        else:
            await db.release_shift(shift["id"], status="offers_out", rung=rung.number,
                                   next_action_at=(now() + CALLING_STALE).isoformat())
            return  # a call is still live; check back shortly

    candidates = [o for o in await db.offers_for_shift(shift["id"], states=["scored", "messaged"])
                  if "voice" in _allowed_channels(o)]
    override = False
    if not candidates:
        # Every clean prospect is exhausted: last-resort tier. One gentle,
        # apologetic ask per opted-out nurse — never the full ladder.
        candidates = [o for o in await db.offers_for_shift(shift["id"], states=["fallback"])
                      if "voice" in _allowed_channels(o)]
        override = True
    if not candidates:
        await escalate(shift, "all prospects exhausted")
        return
    offer = candidates[0]
    claim_from = ["fallback"] if override else ["scored", "messaged"]
    if not await db.set_offer_state(offer["id"], "calling", claim_from):
        return  # raced with a reply; next poll re-evaluates
    phone = offer["nurses"]["phone"]
    if _is_fake(phone):
        await db.set_offer_state(offer["id"], "no_answer", ["calling"])
        outcome = "skipped_fake_number"
    else:
        meta = {"role": "offer", "offer_id": offer["id"]}
        if override:
            meta["override"] = True
        result = await outbound.place_call(
            phone, room_name=f"offer-{offer['id'][:8]}", metadata=json.dumps(meta))
        if result.get("ok"):
            if result.get("room"):
                await db.set_offer_call_room(offer["id"], result["room"])
            outcome = "dialing"
        else:
            attempts = await db.bump_dial_attempts(offer["id"])
            if attempts < 2:
                back = "messaged" if (offer.get("rung") or 0) > 0 else "scored"
                await db.set_offer_state(offer["id"], back, ["calling"])
                outcome = "dial_failed"
                await db.log_event("worker", "offer_call", shift_id=shift["id"],
                                   nurse_id=offer["nurse_id"], channel="voice",
                                   rung=rung.number, outcome=outcome,
                                   payload={"attempts": attempts})
                await db.release_shift(shift["id"], status="offers_out",
                                       rung=rung.number,
                                       next_action_at=(now() + timedelta(seconds=30)).isoformat())
                log.info("voice rung: %s dial_failed, retry in 30s",
                         offer["nurses"]["name"])
                return
            await db.set_offer_state(offer["id"], "no_answer", ["calling"])
            outcome = "dial_failed_x2"
    if override:
        await db.log_event("worker", "preference_override_ask", shift_id=shift["id"],
                           nurse_id=offer["nurse_id"], channel="voice",
                           payload={"reason": _last_memory_note(offer["nurses"])})
    log.info("voice rung%s: %s -> %s", " (override)" if override else "",
             offer["nurses"]["name"], outcome)
    await db.log_event("worker", "offer_call", shift_id=shift["id"],
                       nurse_id=offer["nurse_id"], channel="voice",
                       rung=rung.number, outcome=outcome)
    await db.release_shift(shift["id"], status="offers_out", rung=rung.number,
                           next_action_at=(now() + timedelta(minutes=rung.wait_minutes)).isoformat())


async def escalate(shift: dict, reason: str) -> None:
    # TODO(Phase 3+): dial the human coordinator here via channels.outbound.
    log.warning("shift %s ESCALATED: %s", shift["id"][:8], reason)
    await db.log_event("worker", "escalated", shift_id=shift["id"],
                       payload={"reason": reason})
    await db.release_shift(shift["id"], status="escalated")


async def _send(channel: str, phone: str, text: str) -> str:
    if _is_fake(phone):
        return "skipped_fake_number"
    if channel == "whatsapp":
        result = await sms.send_whatsapp(phone, text)
    else:
        result = await sms.send_sms(phone, text)
    return "sent" if result.get("ok") else f"failed: {result.get('error', '?')[:80]}"


def _offer_text(shift: dict, agency: dict) -> str:
    when = spoken_when(shift["starts_at"], shift["ends_at"], agency["timezone"])
    return (f"{agency['name']}: an open {shift['specialty']} shift {when} in "
            f"{shift['area']}. Reply YES to take it or NO to pass.")


def _allowed_channels(offer: dict) -> list[str]:
    """Channels this nurse is comfortable with (dashboard-editable preference)."""
    prefs = offer["nurses"].get("preferences") or {}
    return prefs.get("channels") or ["sms", "whatsapp", "voice"]


def _last_memory_note(nurse: dict) -> str:
    """Most recent learned-preference note, for the override audit trail."""
    memory = (nurse.get("preferences") or {}).get("memory") or []
    return memory[-1]["note"] if memory else ""


def now() -> datetime:
    return datetime.now(UTC)
