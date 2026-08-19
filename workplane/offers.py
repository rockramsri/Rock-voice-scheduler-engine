"""Accept/decline an offer — the ONE implementation, used everywhere.

The OfferAgent's voice tools, the SMS webhook's YES/NO path, and any future
dashboard button all call these two functions, so the lock, the guarded
state change, and the audit trail can never drift apart. A winning accept
also stands down every other open prospect (state + courtesy text), fired
as a background task so voice calls stay snappy.
"""

from __future__ import annotations

import asyncio
import logging

from data import db
from shared.phone import is_fake
from shared.spoken import spoken_when
from workplane import emr

log = logging.getLogger("workplane.offers")

RESPONDABLE = ["scored", "messaged", "calling", "fallback"]
STAND_DOWN_FROM = ["scored", "messaged", "calling", "no_answer", "fallback"]

_background: set[asyncio.Task] = set()


async def accept_offer(offer: dict) -> bool:
    """First YES wins. Returns False when someone else already got the shift."""
    won = await db.lock_shift(offer["shift_id"], offer["nurse_id"])
    if won:
        await db.set_offer_state(offer["id"], "accepted", RESPONDABLE)
        log.info("offer %s ACCEPTED - shift %s filled", offer["id"], offer["shift_id"])
        shift = offer.get("shifts") or {"id": offer["shift_id"]}
        await emr.post_chart_event(
            "shift_reassigned", shift, nurse_id=offer["nurse_id"],
            details={"assigned_nurse": (offer.get("nurses") or {}).get("name", "")})
        task = asyncio.create_task(stand_down_losers(offer["shift_id"]))
        _background.add(task)
        task.add_done_callback(_background.discard)
    else:
        await db.set_offer_state(offer["id"], "declined", RESPONDABLE)
        log.info("offer %s accepted too late - shift already filled", offer["id"])
    await db.log_event("workplane", "offer_response", shift_id=offer["shift_id"],
                       nurse_id=offer["nurse_id"], outcome="yes" if won else "yes_too_late")
    return won


async def stand_down_losers(shift_id: str) -> None:
    """Tell every still-open prospect the shift is covered; mark them stood_down."""
    from channels import sms  # local import: keeps voice plane free of channel deps

    try:
        shift = await db.get_shift(shift_id)
        losers = await db.offers_for_shift(shift_id, states=STAND_DOWN_FROM)
        when = spoken_when(shift["starts_at"], shift["ends_at"])
        text = (f"Rockram Home Health Care: the {when} {shift['specialty']} shift in "
                f"{shift['area']} has been covered. Thanks for being available — "
                "we'll reach out next time.")
        for offer in losers:
            if not await db.set_offer_state(offer["id"], "stood_down", STAND_DOWN_FROM):
                continue  # raced with a late reply; leave it be
            if offer["state"] == "fallback":
                # Opted-out and never contacted — flip state silently, no text.
                await db.log_event("workplane", "stand_down", shift_id=shift_id,
                                   nurse_id=offer["nurse_id"], outcome="silent_fallback")
                continue
            phone = offer["nurses"]["phone"]
            channels = (offer["nurses"].get("preferences") or {}).get("channels") or ["sms"]
            outcome = "skipped"
            if not is_fake(phone):
                if "sms" in channels:
                    result = await sms.send_sms(phone, text)
                elif "whatsapp" in channels:
                    result = await sms.send_whatsapp(phone, text)
                else:
                    result = {"ok": False, "error": "no message channel allowed"}
                outcome = "sent" if result.get("ok") else f"failed: {result.get('error', '?')[:60]}"
            await db.log_event("workplane", "stand_down", shift_id=shift_id,
                               nurse_id=offer["nurse_id"], outcome=outcome)
            log.info("stand-down %s -> %s", offer["nurses"]["name"], outcome)
    except Exception:
        log.exception("stand-down for shift %s failed", shift_id)


async def decline_offer(offer: dict) -> None:
    """Pruned forever: a decliner is never contacted again for this shift."""
    await db.set_offer_state(offer["id"], "declined", RESPONDABLE)
    await db.log_event("workplane", "offer_response", shift_id=offer["shift_id"],
                       nurse_id=offer["nurse_id"], outcome="no")
    log.info("offer %s declined", offer["id"])
