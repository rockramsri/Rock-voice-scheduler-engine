"""S6 — escalate pages a human; the mock path still carries a phone number."""

from datetime import UTC, datetime, timedelta

import pytest

from channels import webhook
from evals import seed
from workers import rungs


@pytest.fixture
async def world(eval_db):
    run = seed.seed_run(
        roster=[{"slug": "CG-A"}, {"slug": "CG-B"}],
        shifts=[{"slug": "SH-1", "nurse": "CG-A", "starts_in_hours": 26,
                 "status": "offers_out"}],
    )
    try:
        yield run
    finally:
        seed.cleanup(run)


def _agency(world):
    return seed.client().table("agencies").select("*").eq(
        "id", world.agency_id).single().execute().data


async def test_escalate_pages_with_mock_number(world, monkeypatch):
    from data import db

    monkeypatch.setattr(rungs, "now", lambda: datetime(2026, 8, 19, 14, 0, tzinfo=UTC))
    shift = await db.get_shift(world.uuid("SH-1"))
    agency = _agency(world)
    await rungs.escalate(shift, "all prospects exhausted", agency)

    row = await db.get_shift(world.uuid("SH-1"))
    assert row["status"] == "escalated"
    assert row["escalation_state"] == "paged"
    assert row.get("next_action_at")
    events = seed.client().table("events").select("kind, payload").eq(
        "shift_id", world.uuid("SH-1")).execute().data
    paged = [e for e in events if e["kind"] == "escalation_paged"]
    assert paged
    payload = paged[0]["payload"] or {}
    assert payload.get("oncall_phone") == "555-0199"
    assert "555-0199" in (payload.get("body") or "")
    assert f"ACK {world.uuid('SH-1')[:6]}" in (payload.get("body") or "")


async def test_ack_from_oncall_number(world, monkeypatch):
    from data import db

    monkeypatch.setattr(rungs, "now", lambda: datetime(2026, 8, 19, 14, 0, tzinfo=UTC))
    async def fake_agency():
        return _agency(world)
    monkeypatch.setattr(db, "fetch_agency", fake_agency)
    shift = await db.get_shift(world.uuid("SH-1"))
    await rungs.escalate(shift, "ladder exhausted", _agency(world))
    code = world.uuid("SH-1")[:6]
    reply = await webhook._escalation_ack("555-0199", f"ACK {code}")
    assert reply and "Acknowledged" in reply
    row = await db.get_shift(world.uuid("SH-1"))
    assert row["escalation_state"] == "acked"
    assert row.get("next_action_at") is None


async def test_ack_from_other_number_is_ignored(world, monkeypatch):
    from data import db

    monkeypatch.setattr(rungs, "now", lambda: datetime(2026, 8, 19, 14, 0, tzinfo=UTC))
    async def fake_agency():
        return _agency(world)
    monkeypatch.setattr(db, "fetch_agency", fake_agency)
    shift = await db.get_shift(world.uuid("SH-1"))
    await rungs.escalate(shift, "ladder exhausted", _agency(world))
    code = world.uuid("SH-1")[:6]
    assert await webhook._escalation_ack("+12025551212", f"ACK {code}") is None
    row = await db.get_shift(world.uuid("SH-1"))
    assert row["escalation_state"] == "paged"


async def test_two_voice_pages_then_unreachable(world, monkeypatch):
    from data import db

    frozen = datetime(2026, 8, 19, 14, 0, tzinfo=UTC)
    monkeypatch.setattr(rungs, "now", lambda: frozen)
    shift = await db.get_shift(world.uuid("SH-1"))
    agency = _agency(world)
    await rungs.escalate(shift, "all prospects exhausted", agency)
    shift = await db.get_shift(world.uuid("SH-1"))
    await rungs.repage_oncall(shift, agency)
    shift = await db.get_shift(world.uuid("SH-1"))
    assert shift["escalation_state"] == "paged" and shift["escalation_pages"] == 1
    await rungs.repage_oncall(shift, agency)
    shift = await db.get_shift(world.uuid("SH-1"))
    assert shift["escalation_pages"] == 2
    await rungs.repage_oncall(shift, agency)
    shift = await db.get_shift(world.uuid("SH-1"))
    assert shift["escalation_state"] == "unreachable"
    events = seed.client().table("events").select("kind").eq(
        "shift_id", world.uuid("SH-1")).execute().data
    assert any(e["kind"] == "escalation_unreachable" for e in events)


async def test_claim_shifts_picks_due_paged_escalation(world, monkeypatch):
    from data import db

    monkeypatch.setattr(rungs, "now", lambda: datetime(2026, 8, 19, 14, 0, tzinfo=UTC))
    shift = await db.get_shift(world.uuid("SH-1"))
    await rungs.escalate(shift, "all prospects exhausted", _agency(world))
    seed.client().table("shifts").update({
        "next_action_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "claimed_by": None, "claimed_at": None,
    }).eq("id", world.uuid("SH-1")).execute()
    claimed = await db.claim_shifts("esc-worker", limit=50)
    assert world.uuid("SH-1") in [s["id"] for s in claimed]
