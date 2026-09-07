"""B4 — a transient dial failure retries the same prospect in 30s."""

from datetime import UTC, datetime

import pytest

from evals import seed
from workers import ladder


@pytest.fixture
async def world(eval_db):
    run = seed.seed_run(
        roster=[{"slug": "CG-A"}, {"slug": "CG-B", "phone": "+12025551212"}],
        shifts=[{"slug": "SH-1", "nurse": "CG-A", "starts_in_hours": 26,
                 "status": "offers_out", "rung": 3}],
    )
    try:
        yield run
    finally:
        seed.cleanup(run)


async def test_dial_failed_then_retry_same_prospect(world, monkeypatch):
    from data import db
    from workers import rungs

    shift_id = world.uuid("SH-1")
    seed.client().table("shifts").update({
        "status": "offers_out", "nurse_id": None, "rung": 3,
        "callout_nurse_id": world.uuid("CG-A"),
    }).eq("id", shift_id).execute()
    await db.insert_offers([{"shift_id": shift_id, "nurse_id": world.uuid("CG-B"),
                             "score": 0.9, "reason": "t"}])
    offer = (await db.offers_for_shift(shift_id))[0]
    await db.bump_offer_rung(offer["id"], 1, "sms")

    calls: list[str] = []

    async def fake_place(to, room_name=None, metadata=""):
        calls.append(to)
        if len(calls) == 1:
            return {"ok": False, "error": "sip down", "room": room_name}
        return {"ok": True, "to": to, "room": room_name}

    monkeypatch.setattr(rungs.outbound, "place_call", fake_place)
    monkeypatch.setattr(rungs, "now", lambda: datetime(2026, 8, 19, 14, 0, tzinfo=UTC))

    shift = await db.get_shift(shift_id)
    agency = seed.client().table("agencies").select("*").eq(
        "id", world.agency_id).single().execute().data
    rung = ladder.Rung(4, ("voice",), 3)
    await rungs.voice_rung(shift, rung, agency, lead_hours=26)
    row = await db.get_offer_full(offer["id"])
    assert row["state"] == "messaged"
    assert row["dial_attempts"] == 1

    shift = await db.get_shift(shift_id)
    await rungs.voice_rung(shift, rung, agency, lead_hours=26)
    assert calls == ["+12025551212", "+12025551212"]
    events = seed.client().table("events").select("outcome").eq(
        "kind", "offer_call").eq("shift_id", shift_id).execute().data
    outcomes = [e["outcome"] for e in events]
    assert "dial_failed" in outcomes
    assert "dialing" in outcomes
