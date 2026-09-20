"""EMR contract suite — the scenarios every backend must satisfy.

M1 runs the mock lane (agencies default to emr_backend='mock'). M2+ adds
fhir backends via EMR_TEST_BACKENDS with per-backend reachability skips.
Numbering follows docs/emr-architecture.md section 7:
  2 callout-then-fill   3 replay idempotent   5 transient-then-success
  6 permanent dead-letters   7 crash resume   10 unknown backend visible
"""

import time

import pytest

from data import db
from evals import seed
from workplane.emr.base import EmrPermanentError, EmrTransientError
from workers.outbox_worker import drain_outbox_once


@pytest.fixture
async def world(eval_db):
    run = seed.seed_run(
        roster=[{"slug": "CG-OUT"}, {"slug": "CG-WIN"}],
        shifts=[{"slug": "SH-1", "nurse": "CG-OUT", "starts_in_hours": 26,
                 "status": "scheduled"}],
    )
    try:
        yield run
    finally:
        seed.cleanup(run)


def _outbox(run):
    return (seed.client().table("outbox").select("*")
            .eq("agency_id", run.agency_id).order("id").execute().data)


def _writeback_events(run, kind="emr_writeback"):
    return (seed.client().table("events").select("*")
            .eq("kind", kind).eq("agency_id", run.agency_id)
            .order("id").execute().data)


def _links(run):
    return (seed.client().table("emr_links").select("*")
            .eq("agency_id", run.agency_id).execute().data)


def _reopen(run, **fields):
    """Test-only knob: reset outbox rows (replay, backdate, un-park)."""
    seed.client().table("outbox").update(fields).eq(
        "agency_id", run.agency_id).execute()


# ---- scenario 2: callout then fill ----

async def test_callout_then_fill(world):
    shift_id = world.uuid("SH-1")
    t0 = time.monotonic()
    assert await db.record_callout_with_outbox(shift_id, world.uuid("CG-OUT"), "sick")
    # Guarded: a second callout of the same shift matches zero rows.
    assert not await db.record_callout_with_outbox(shift_id, world.uuid("CG-OUT"), "sick")
    assert await db.lock_shift_with_outbox(shift_id, world.uuid("CG-WIN"))

    rows = _outbox(world)
    assert sorted(r["kind"] for r in rows) == ["callout_documented", "shift_reassigned"]
    assert all(r["done_at"] is None for r in rows)

    processed = await drain_outbox_once(agency_id=world.agency_id)
    elapsed = time.monotonic() - t0
    assert processed == 2
    assert all(r["done_at"] for r in _outbox(world))

    events = _writeback_events(world)
    actions = sorted(e["payload"]["action"] for e in events)
    assert actions == ["callout_documented", "shift_reassigned"]
    assert all(str(e["payload"].get("record_id", "")).startswith("WSK-") for e in events)
    assert all(e["payload"]["backend"] == "mock" for e in events)
    print(f"\nM1 gate timing (drain-once mode): callout -> both emr_writeback "
          f"events in {elapsed:.2f}s")


# ---- scenario 3: replay is idempotent ----

async def test_replay_is_idempotent(world):
    shift_id = world.uuid("SH-1")
    assert await db.record_callout_with_outbox(shift_id, world.uuid("CG-OUT"), "sick")
    assert await db.lock_shift_with_outbox(shift_id, world.uuid("CG-WIN"))
    await drain_outbox_once(agency_id=world.agency_id)
    rows_before, links_before = _outbox(world), _links(world)

    # Re-running the RPCs is a no-op: guards match zero rows, keys collide.
    assert not await db.record_callout_with_outbox(shift_id, world.uuid("CG-OUT"), "again")
    assert len(_outbox(world)) == len(rows_before)

    # Force a full replay of both jobs (crash-after-execute, before-complete).
    _reopen(world, done_at=None, claimed_by=None, claimed_at=None)
    assert await drain_outbox_once(agency_id=world.agency_id) == 2

    assert len(_outbox(world)) == len(rows_before)          # no new rows
    assert len(_links(world)) == len(links_before)          # links upserted, not duplicated
    assert all(r["done_at"] for r in _outbox(world))


# ---- scenario 5: transient failure, then success ----

async def test_transient_then_success(world, monkeypatch):
    from workplane.emr.mock_driver import MockDriver
    original = MockDriver.execute
    calls = {"n": 0}

    async def flaky(self, job, ctx):
        calls["n"] += 1
        if calls["n"] == 1:
            raise EmrTransientError("simulated 503")
        return await original(self, job, ctx)

    monkeypatch.setattr(MockDriver, "execute", flaky)
    shift_id = world.uuid("SH-1")
    await db.enqueue_emr(world.agency_id, "escalated", shift_id, None, None,
                         f"escalated:{shift_id}:test5")

    await drain_outbox_once(agency_id=world.agency_id)
    row = _outbox(world)[0]
    assert row["done_at"] is None and row["attempts"] == 1
    assert "503" in (row["last_error"] or "")
    assert len(_writeback_events(world, "emr_writeback_failed")) == 1

    _reopen(world, next_attempt_at="now()")     # skip the 30s backoff wait
    await drain_outbox_once(agency_id=world.agency_id)
    row = _outbox(world)[0]
    assert row["done_at"] and row["attempts"] == 2
    assert len(_writeback_events(world)) == 1   # exactly one successful write


# ---- scenario 6: permanent failure dead-letters on attempt one ----

async def test_permanent_dead_letters(world, monkeypatch):
    from workplane.emr.mock_driver import MockDriver

    async def broken(self, job, ctx):
        raise EmrPermanentError("simulated 400: bad resource")

    monkeypatch.setattr(MockDriver, "execute", broken)
    shift_id = world.uuid("SH-1")
    await db.enqueue_emr(world.agency_id, "escalated", shift_id, None, None,
                         f"escalated:{shift_id}:test6")

    await drain_outbox_once(agency_id=world.agency_id)
    row = _outbox(world)[0]
    assert row["dead_at"] is not None and row["attempts"] == 1
    dead = _writeback_events(world, "emr_writeback_dead")
    assert len(dead) == 1 and "permanent" in (dead[0]["outcome"] or "")

    # Nothing retried: dead rows are invisible to the claim.
    assert await drain_outbox_once(agency_id=world.agency_id) == 0
    assert len(_writeback_events(world)) == 0


# ---- scenario 7: a crashed drainer's claim is rescued ----

async def test_crash_resume(world):
    shift_id = world.uuid("SH-1")
    await db.enqueue_emr(world.agency_id, "escalated", shift_id, None, None,
                         f"escalated:{shift_id}:test7")

    # A drainer claims the row, then dies before completing it.
    claimed = await db.claim_outbox("obx-crashed", 10, world.agency_id)
    assert len(claimed) == 1

    # A live claim blocks other drainers (no double work while it may be running).
    assert await drain_outbox_once(agency_id=world.agency_id) == 0

    # 5+ minutes later the claim is stale — any drainer rescues and finishes it.
    seed.client().table("outbox").update(
        {"claimed_at": "2020-01-01T00:00:00+00:00"}).eq(
        "agency_id", world.agency_id).execute()
    assert await drain_outbox_once(agency_id=world.agency_id) == 1
    assert _outbox(world)[0]["done_at"]
    assert len(_writeback_events(world)) == 1   # exactly one write, no duplicate


# ---- scenario 10: misconfiguration is visible, fast ----

async def test_config_visible_failure(world):
    seed.client().table("agencies").update({"emr_backend": "axiscare"}).eq(
        "id", world.agency_id).execute()
    shift_id = world.uuid("SH-1")
    await db.enqueue_emr(world.agency_id, "escalated", shift_id, None, None,
                         f"escalated:{shift_id}:test10")

    await drain_outbox_once(agency_id=world.agency_id)
    row = _outbox(world)[0]
    assert row["dead_at"] is not None and row["attempts"] == 1
    dead = _writeback_events(world, "emr_writeback_dead")
    assert len(dead) == 1 and "axiscare" in (dead[0]["outcome"] or "")


# ---- gate measurement: the real polling drainer, end to end ----

async def test_live_drainer_timing(world):
    """Callout -> emr_writeback event with the actual polling loop running."""
    import asyncio

    from workers import outbox_worker

    task = asyncio.create_task(outbox_worker.run())
    try:
        shift_id = world.uuid("SH-1")
        t0 = time.monotonic()
        assert await db.record_callout_with_outbox(shift_id, world.uuid("CG-OUT"), "sick")
        elapsed = None
        while time.monotonic() - t0 < 15:
            events = _writeback_events(world)
            if any(e["payload"]["action"] == "callout_documented" for e in events):
                elapsed = time.monotonic() - t0
                break
            await asyncio.sleep(0.2)
        assert elapsed is not None, "drainer never wrote the emr_writeback event"
        print(f"\nM1 gate timing (live polling drainer): callout -> "
              f"emr_writeback event in {elapsed:.2f}s")
        assert elapsed < 10
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
