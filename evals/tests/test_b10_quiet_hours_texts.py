"""B10 — message_rung honors quiet hours when quiet_hours_texts is on."""

from datetime import UTC, datetime, timedelta

import pytest

from evals import seed
from workers import ladder, rungs


FROZEN = datetime(2026, 8, 20, 7, 0, tzinfo=UTC)  # 03:00 America/New_York


@pytest.fixture
async def world(eval_db):
    run = seed.seed_run(
        roster=[{"slug": "CG-A"}, {"slug": "CG-B", "phone": "+12025551212"}],
        shifts=[{"slug": "SH-1", "nurse": "CG-A", "starts_in_hours": 26,
                 "status": "scheduled"}],
    )
    try:
        yield run
    finally:
        seed.cleanup(run)


def _agency(world):
    return seed.client().table("agencies").select("*").eq(
        "id", world.agency_id).single().execute().data


async def _prep_offers_out(world, starts_at: datetime):
    from data import db
    shift_id = world.uuid("SH-1")
    seed.client().table("shifts").update({
        "status": "offers_out", "nurse_id": None,
        "callout_nurse_id": world.uuid("CG-A"),
        "starts_at": starts_at.isoformat(),
        "ends_at": (starts_at + timedelta(hours=8)).isoformat(),
        "rung": 0,
    }).eq("id", shift_id).execute()
    await db.insert_offers([{"shift_id": shift_id, "nurse_id": world.uuid("CG-B"),
                             "score": 0.9, "reason": "t"}])
    return await db.get_shift(shift_id)


async def test_relaxed_text_defers_at_3am(world, monkeypatch):
    from data import db
    monkeypatch.setattr(rungs, "now", lambda: FROZEN)
    shift = await _prep_offers_out(world, FROZEN + timedelta(hours=30))
    agency = _agency(world)
    sent: list[str] = []

    async def fake_sms(phone, text):
        sent.append(phone)
        return {"ok": True}

    monkeypatch.setattr(rungs.sms, "send_sms", fake_sms)
    await rungs.message_rung(shift, ladder.Rung(1, ("sms",), 30), agency)
    assert sent == []
    row = await db.get_shift(world.uuid("SH-1"))
    assert row["status"] == "offers_out"
    expected = ladder.next_call_window(FROZEN, agency)
    delta = abs((datetime.fromisoformat(row["next_action_at"]) - expected).total_seconds())
    assert delta < 60
    events = seed.client().table("events").select("kind").eq(
        "shift_id", world.uuid("SH-1")).execute().data
    assert not any(e["kind"] == "offer_sent" for e in events)


async def test_urgent_text_escalates_at_3am(world, monkeypatch):
    from data import db
    monkeypatch.setattr(rungs, "now", lambda: FROZEN)
    shift = await _prep_offers_out(world, FROZEN + timedelta(hours=3))
    agency = _agency(world)
    await rungs.message_rung(shift, ladder.Rung(1, ("sms",), 10), agency)
    row = await db.get_shift(world.uuid("SH-1"))
    assert row["status"] == "escalated"
    events = seed.client().table("events").select("kind, payload").eq(
        "shift_id", world.uuid("SH-1")).eq("kind", "escalated").execute().data
    assert events and "urgent shift inside quiet hours" in (
        (events[0].get("payload") or {}).get("reason") or "")
