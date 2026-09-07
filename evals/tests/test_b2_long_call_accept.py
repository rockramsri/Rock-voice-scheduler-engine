"""B2 — a YES after no_answer still wins; stand-down skips the winner."""

import pytest

from evals import seed


@pytest.fixture
async def world(eval_db):
    run = seed.seed_run(
        roster=[{"slug": "CG-A"}, {"slug": "CG-B"}],
        shifts=[{"slug": "SH-1", "nurse": "CG-A", "starts_in_hours": 26}],
    )
    try:
        yield run
    finally:
        seed.cleanup(run)


async def test_accept_from_no_answer_excludes_winner_from_stand_down(world):
    from data import db
    from workplane.offers import accept_offer, stand_down_losers

    shift = world.uuid("SH-1")
    await db.record_callout(shift, world.uuid("CG-A"), "sick")
    await db.insert_offers([
        {"shift_id": shift, "nurse_id": world.uuid("CG-B"), "score": 0.9, "reason": "t"},
        {"shift_id": shift, "nurse_id": world.uuid("CG-A"), "score": 0.4, "reason": "t"},
    ])
    winner = next(o for o in await db.offers_for_shift(shift)
                  if o["nurse_id"] == world.uuid("CG-B"))
    loser = next(o for o in await db.offers_for_shift(shift)
                 if o["nurse_id"] == world.uuid("CG-A"))
    await db.set_offer_state(winner["id"], "no_answer", ["scored"])
    offer = await db.get_offer_full(winner["id"])
    assert await accept_offer(offer) is True
    row = await db.get_offer_full(winner["id"])
    assert row["state"] == "accepted"
    await stand_down_losers(shift, winner["id"])
    stood = [e for e in seed.client().table("events").select("*")
             .eq("kind", "stand_down").eq("shift_id", shift).execute().data]
    assert all(e.get("nurse_id") != world.uuid("CG-B") for e in stood)
    loser_row = await db.get_offer_full(loser["id"])
    assert loser_row["state"] in {"stood_down", "scored"}
