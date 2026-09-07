"""B6 — four declines widen the net; escalate only after everyone is asked."""

from datetime import UTC, datetime

import pytest

from evals import seed
from workers import dispatch_worker, ladder, rungs
from workplane.offers import decline_offer


@pytest.fixture
async def world(eval_db):
    roster = [{"slug": f"CG-{i}", "reliability": 0.50 + i * 0.02} for i in range(1, 9)]
    roster.append({"slug": "CG-X"})
    run = seed.seed_run(
        roster=roster,
        shifts=[{"slug": "SH-1", "nurse": "CG-X", "starts_in_hours": 26,
                 "status": "scheduled"}],
    )
    try:
        yield run
    finally:
        seed.cleanup(run)


def _agency(world):
    return seed.client().table("agencies").select("*").eq(
        "id", world.agency_id).single().execute().data


async def test_eight_eligible_widen_before_escalate(world, monkeypatch):
    from data import db

    frozen = datetime(2026, 8, 19, 14, 0, tzinfo=UTC)
    monkeypatch.setattr(rungs, "now", lambda: frozen)

    assert await db.record_callout(world.uuid("SH-1"), world.uuid("CG-X"), "sick")
    shift = await db.get_shift(world.uuid("SH-1"))
    agency = _agency(world)
    await dispatch_worker._start_offering(shift, agency)

    first = await db.offers_for_shift(world.uuid("SH-1"))
    assert len(first) == 4
    first_ids = {o["nurse_id"] for o in first}
    for offer in first:
        await decline_offer(offer)

    shift = await db.get_shift(world.uuid("SH-1"))
    await rungs.voice_rung(shift, ladder.Rung(4, ("voice",), 3), agency, 26)

    after = await db.offers_for_shift(world.uuid("SH-1"))
    assert len(after) == 8
    second = [o for o in after if o["nurse_id"] not in first_ids]
    assert len(second) == 4
    assert all(o["state"] == "scored" for o in second)
    events = seed.client().table("events").select("kind").eq(
        "shift_id", world.uuid("SH-1")).execute().data
    assert not any(e["kind"] == "escalated" for e in events)
    assert any(e["kind"] == "net_widened" for e in events)

    for offer in second:
        await decline_offer(offer)
    shift = await db.get_shift(world.uuid("SH-1"))
    await rungs.voice_rung(shift, ladder.Rung(4, ("voice",), 3), agency, 26)

    shift = await db.get_shift(world.uuid("SH-1"))
    assert shift["status"] == "escalated"
    remaining = {o["nurse_id"] for o in await db.offers_for_shift(world.uuid("SH-1"))}
    assert remaining == {world.uuid(f"CG-{i}") for i in range(1, 9)}
