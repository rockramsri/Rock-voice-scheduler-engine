"""B3 — concurrent learn_nurse_preference calls keep every note."""

import asyncio

import pytest

from evals import seed


@pytest.fixture
async def world(eval_db):
    run = seed.seed_run(roster=[{"slug": "CG-A"}])
    try:
        yield run
    finally:
        seed.cleanup(run)


async def test_ten_concurrent_notes_all_land(world):
    from data import db

    nurse = world.uuid("CG-A")
    notes = [f"note-{i:02d}-unique" for i in range(10)]
    await asyncio.gather(*[
        db.learn_nurse_preference(nurse, note) for note in notes
    ])
    row = seed.client().table("nurses").select("preferences").eq(
        "id", nurse).single().execute().data
    memory = (row.get("preferences") or {}).get("memory") or []
    landed = {item.get("note") for item in memory}
    missing = set(notes) - landed
    assert not missing, f"lost notes: {missing}; have {landed}"
