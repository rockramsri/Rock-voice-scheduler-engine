"""B7 — a decline parks next_action_at at now, not three minutes out."""

from datetime import UTC, datetime, timedelta

import pytest

from evals import seed
from workplane.offers import decline_offer


@pytest.fixture
async def world(eval_db):
    run = seed.seed_run(
        roster=[{"slug": "CG-A"}, {"slug": "CG-B"}],
        shifts=[{"slug": "SH-1", "nurse": "CG-A", "starts_in_hours": 26,
                 "status": "scheduled"}],
    )
    try:
        yield run
    finally:
        seed.cleanup(run)


async def test_decline_sets_next_action_at_now(world):
    from data import db

    shift_id = world.uuid("SH-1")
    assert await db.record_callout(shift_id, world.uuid("CG-A"), "sick")
    seed.client().table("shifts").update({
        "status": "offers_out",
        "next_action_at": (datetime.now(UTC) + timedelta(minutes=3)).isoformat(),
    }).eq("id", shift_id).execute()
    await db.insert_offers([{"shift_id": shift_id, "nurse_id": world.uuid("CG-B"),
                             "score": 0.9, "reason": "t"}])
    offer = (await db.offers_for_shift(shift_id))[0]
    before = datetime.now(UTC)
    await decline_offer(offer)
    row = await db.get_shift(shift_id)
    due = datetime.fromisoformat(row["next_action_at"])
    assert due <= datetime.now(UTC) + timedelta(seconds=2)
    assert due >= before - timedelta(seconds=2)
    assert row["status"] == "offers_out"


async def test_wake_shift_ignores_filled(world):
    from data import db

    shift_id = world.uuid("SH-1")
    seed.client().table("shifts").update({
        "status": "filled", "nurse_id": world.uuid("CG-B"),
        "next_action_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }).eq("id", shift_id).execute()
    assert await db.wake_shift(shift_id) is False
    row = await db.get_shift(shift_id)
    assert row["status"] == "filled"
    due = datetime.fromisoformat(row["next_action_at"])
    assert due > datetime.now(UTC) + timedelta(minutes=30)
