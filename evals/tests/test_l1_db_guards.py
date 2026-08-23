"""L1 — guarded transitions + atomic lock, against the ISOLATED eval DB.

These prove the storage-layer safety rules the whole system leans on:
record_callout / set_offer_state / bump_offer_rung guards, lock_shift's
first-YES-wins (including the double-booking exclusion), and claim_shifts'
stale-claim takeover. Every test seeds its own namespaced world.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from evals import seed


@pytest.fixture
async def world(eval_db):
    """Two nurses + one scheduled shift held by CG-A; CG-B is the replacement."""
    run = seed.seed_run(
        roster=[{"slug": "CG-A"}, {"slug": "CG-B"}],
        shifts=[{"slug": "SH-1", "nurse": "CG-A", "starts_in_hours": 26}],
    )
    try:
        yield run
    finally:
        seed.cleanup(run)


async def test_record_callout_guard(world):
    from data import db
    shift = world.uuid("SH-1")
    assert await db.record_callout(shift, world.uuid("CG-A"), "sick") is True
    # Second callout on the same shift loses the guard (status != scheduled).
    assert await db.record_callout(shift, world.uuid("CG-A"), "again") is False
    row = await db.get_shift(shift)
    assert row["status"] == "callout" and row["nurse_id"] is None


async def test_set_offer_state_guards(world):
    from data import db
    shift = world.uuid("SH-1")
    await db.record_callout(shift, world.uuid("CG-A"), "sick")
    await db.insert_offers([{"shift_id": shift, "nurse_id": world.uuid("CG-B"),
                             "score": 0.9, "reason": "test"}])
    offer = (await db.offers_for_shift(shift))[0]

    assert await db.set_offer_state(offer["id"], "messaged", ["scored"]) is True
    assert await db.set_offer_state(offer["id"], "messaged", ["scored"]) is False  # already moved
    assert await db.set_offer_state(offer["id"], "accepted",
                                    ["scored", "messaged", "calling", "fallback"]) is True


async def test_bump_offer_rung_guards(world):
    from data import db
    shift = world.uuid("SH-1")
    await db.record_callout(shift, world.uuid("CG-A"), "sick")
    await db.insert_offers([{"shift_id": shift, "nurse_id": world.uuid("CG-B"),
                             "score": 0.9, "reason": "test"}])
    offer = (await db.offers_for_shift(shift))[0]

    assert await db.bump_offer_rung(offer["id"], 1, "sms") is True
    assert await db.bump_offer_rung(offer["id"], 1, "sms") is False   # rung must increase
    assert await db.bump_offer_rung(offer["id"], 0, "sms") is False
    assert await db.bump_offer_rung(offer["id"], 2, "whatsapp") is True
    await db.set_offer_state(offer["id"], "accepted", ["messaged"])
    assert await db.bump_offer_rung(offer["id"], 3, "voice") is False  # resolved offers never re-touched


async def test_insert_offers_is_idempotent(world):
    from data import db
    shift = world.uuid("SH-1")
    row = {"shift_id": shift, "nurse_id": world.uuid("CG-B"), "score": 0.9, "reason": "t"}
    await db.insert_offers([row])
    await db.insert_offers([row])   # UNIQUE(shift_id, nurse_id) makes this a no-op
    assert len(await db.offers_for_shift(shift)) == 1


async def test_lock_shift_first_yes_wins(world):
    from data import db
    shift = world.uuid("SH-1")
    await db.record_callout(shift, world.uuid("CG-A"), "sick")

    results = await asyncio.gather(db.lock_shift(shift, world.uuid("CG-B")),
                                   db.lock_shift(shift, world.uuid("CG-A")))
    assert sorted(results) == [False, True]   # exactly one winner, race-safe
    row = await db.get_shift(shift)
    assert row["status"] == "filled" and row["nurse_id"] in (world.uuid("CG-A"),
                                                             world.uuid("CG-B"))


async def test_lock_shift_rejects_double_booking(eval_db):
    """The btree_gist exclusion makes an overlapping second booking impossible."""
    from data import db
    run = seed.seed_run(
        roster=[{"slug": "CG-A"}, {"slug": "CG-B"}],
        shifts=[{"slug": "SH-OPEN", "nurse": "CG-A", "starts_in_hours": 26},
                # CG-B already works an overlapping window elsewhere:
                {"slug": "SH-BUSY", "nurse": "CG-B", "starts_in_hours": 24,
                 "duration_hours": 6}],
    )
    try:
        await db.record_callout(run.uuid("SH-OPEN"), run.uuid("CG-A"), "sick")
        assert await db.lock_shift(run.uuid("SH-OPEN"), run.uuid("CG-B")) is False
        row = await db.get_shift(run.uuid("SH-OPEN"))
        assert row["status"] == "callout" and row["nurse_id"] is None
    finally:
        seed.cleanup(run)


async def test_claim_shifts_and_stale_takeover(world):
    from data import db
    shift = world.uuid("SH-1")
    await db.record_callout(shift, world.uuid("CG-A"), "sick")   # next_action_at = now

    claimed = await db.claim_shifts("worker-1", limit=50)
    assert shift in [s["id"] for s in claimed]

    # A fresh claim is invisible to other workers...
    again = await db.claim_shifts("worker-2", limit=50)
    assert shift not in [s["id"] for s in again]

    # ...until it goes stale (>3 min), then takeover is allowed.
    stale = (datetime.now(UTC) - timedelta(minutes=4)).isoformat()
    seed.client().table("shifts").update({"claimed_at": stale}).eq("id", shift).execute()
    takeover = await db.claim_shifts("worker-2", limit=50)
    assert shift in [s["id"] for s in takeover]
