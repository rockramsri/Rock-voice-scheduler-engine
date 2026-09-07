"""B5 — a failed send retries the same rung; exactly one bump."""

from datetime import UTC, datetime

import pytest

from evals import seed
from workers import ladder


@pytest.fixture
async def world(eval_db):
    run = seed.seed_run(
        roster=[{"slug": "CG-A"}, {"slug": "CG-B", "phone": "+12025551212"}],
        shifts=[{"slug": "SH-1", "nurse": "CG-A", "starts_in_hours": 26,
                 "status": "offers_out", "rung": 0}],
    )
    try:
        yield run
    finally:
        seed.cleanup(run)


async def test_failed_send_retries_same_rung(world, monkeypatch):
    from data import db
    from workers import rungs

    shift_id = world.uuid("SH-1")
    seed.client().table("shifts").update({
        "status": "offers_out", "nurse_id": None,
        "callout_nurse_id": world.uuid("CG-A"),
    }).eq("id", shift_id).execute()
    await db.insert_offers([{"shift_id": shift_id, "nurse_id": world.uuid("CG-B"),
                             "score": 0.9, "reason": "t"}])
    attempts: list[str] = []

    async def fake_sms(phone, text):
        attempts.append(phone)
        if len(attempts) == 1:
            return {"ok": False, "error": "provider 500"}
        return {"ok": True}

    monkeypatch.setattr(rungs.sms, "send_sms", fake_sms)
    monkeypatch.setattr(rungs, "now", lambda: datetime(2026, 8, 19, 14, 0, tzinfo=UTC))

    shift = await db.get_shift(shift_id)
    agency = seed.client().table("agencies").select("*").eq(
        "id", world.agency_id).single().execute().data
    rung = ladder.Rung(1, ("sms",), 30)
    await rungs.message_rung(shift, rung, agency)
    offer = (await db.offers_for_shift(shift_id))[0]
    assert offer["rung"] == 1
    assert offer["last_send_error"]
    assert offer["send_failures"] == 1

    shift = await db.get_shift(shift_id)
    await rungs.message_rung(shift, rung, agency)
    offer = (await db.offers_for_shift(shift_id))[0]
    assert offer["rung"] == 1
    assert offer.get("last_send_error") in (None, "")
    events = seed.client().table("events").select("outcome, rung").eq(
        "kind", "offer_sent").eq("shift_id", shift_id).execute().data
    sent = [e for e in events if e["outcome"] == "sent"]
    failed = [e for e in events if str(e["outcome"]).startswith("failed")]
    assert len(sent) == 1 and len(failed) == 1
    assert sent[0]["rung"] == failed[0]["rung"] == 1
    assert len(attempts) == 2
