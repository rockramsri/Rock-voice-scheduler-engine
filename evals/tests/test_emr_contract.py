"""EMR contract suite — every backend in EMR_TEST_BACKENDS must pass.

M1 = mock. M2 adds hapi (skipped if localhost:8080 is down). Numbering
follows docs/emr-architecture.md §7.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

import pytest

from data import db
from evals import seed
from shared import config
from workplane.emr.base import EmrPermanentError, EmrTransientError
from workplane.emr.mapping import IDENT_SYSTEM
from workers.outbox_worker import drain_outbox_once


def _reachable(base: str, timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(f"{base.rstrip('/')}/metadata", timeout=timeout)
        return True
    except Exception:
        return False


def _hapi_total(rtype: str, value: str) -> int:
    q = urllib.parse.quote(f"{IDENT_SYSTEM}|{value}", safe="")
    url = f"{config.HAPI_BASE_URL}/{rtype}?identifier={q}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return int(json.loads(resp.read()).get("total") or 0)


def _hapi_read(rtype: str, rid: str) -> dict:
    url = f"{config.HAPI_BASE_URL}/{rtype}/{rid}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read())


@pytest.fixture(params=list(config.EMR_TEST_BACKENDS))
async def world(eval_db, request):
    backend = request.param
    agency = {}
    if backend == "hapi":
        if not _reachable(config.HAPI_BASE_URL):
            pytest.skip("HAPI not reachable")
        agency = {
            "emr_backend": "hapi", "emr_profile": "hapi",
            "emr_base_url": config.HAPI_BASE_URL, "emr_auth_kind": "none",
        }
    elif backend != "mock":
        pytest.skip(f"{backend} is not an M2 contract target")
    run = seed.seed_run(
        roster=[{"slug": "CG-OUT"}, {"slug": "CG-WIN"}],
        shifts=[{"slug": "SH-1", "nurse": "CG-OUT", "starts_in_hours": 26,
                 "status": "scheduled"}],
        agency=agency,
    )
    run.backend = backend
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
    seed.client().table("outbox").update(fields).eq(
        "agency_id", run.agency_id).execute()


def _driver_class(backend: str):
    if backend == "mock":
        from workplane.emr.mock_driver import MockDriver
        return MockDriver
    from workplane.emr.fhir_driver import FhirDriver
    return FhirDriver


# ---- 1 seed roster ----

async def test_seed_roster(world):
    aid = world.agency_id
    await db.enqueue_emr(aid, "seed_agency", None, None, None, f"seed_agency:{aid}")
    for nid in world.nurse_ids:
        await db.enqueue_emr(aid, "upsert_practitioner", None, nid, None,
                             f"upsert_practitioner:{nid}")
    for pid in world.patient_ids:
        await db.enqueue_emr(aid, "upsert_patient", None, None, pid,
                             f"upsert_patient:{pid}")
    sid = world.uuid("SH-1")
    await db.enqueue_emr(aid, "upsert_appointment", sid, world.uuid("CG-OUT"),
                         world.uuid("PT-1"), f"upsert_appointment:{sid}")
    assert await drain_outbox_once(agency_id=aid) >= 1
    links_before = _links(world)
    assert links_before

    _reopen(world, done_at=None, claimed_by=None, claimed_at=None)
    await drain_outbox_once(agency_id=aid)
    assert len(_links(world)) == len(links_before)
    if world.backend == "hapi":
        assert _hapi_total("Organization", aid) == 1
        assert _hapi_total("Appointment", sid) == 1


# ---- 2 callout then fill ----

async def test_callout_then_fill(world):
    shift_id = world.uuid("SH-1")
    t0 = time.monotonic()
    assert await db.record_callout_with_outbox(shift_id, world.uuid("CG-OUT"), "sick")
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
    assert all(e["payload"]["backend"] == world.backend for e in events)
    if world.backend == "mock":
        assert all(str(e["payload"].get("record_id", "")).startswith("WSK-") for e in events)
    else:
        types = {row["external_type"] for row in _links(world)}
        assert {"Organization", "Practitioner", "Patient", "Appointment", "Task"} <= types
    print(f"\n{world.backend} callout -> both emr_writeback in {elapsed:.2f}s")


# ---- 3 replay is idempotent ----

async def test_replay_is_idempotent(world):
    shift_id = world.uuid("SH-1")
    assert await db.record_callout_with_outbox(shift_id, world.uuid("CG-OUT"), "sick")
    assert await db.lock_shift_with_outbox(shift_id, world.uuid("CG-WIN"))
    await drain_outbox_once(agency_id=world.agency_id)
    rows_before, links_before = _outbox(world), _links(world)

    assert not await db.record_callout_with_outbox(shift_id, world.uuid("CG-OUT"), "again")
    assert len(_outbox(world)) == len(rows_before)

    _reopen(world, done_at=None, claimed_by=None, claimed_at=None)
    assert await drain_outbox_once(agency_id=world.agency_id) == 2

    assert len(_outbox(world)) == len(rows_before)
    assert len(_links(world)) == len(links_before)
    assert all(r["done_at"] for r in _outbox(world))
    if world.backend == "hapi":
        assert _hapi_total("Appointment", shift_id) == 1
        appt = next(l for l in _links(world) if l["external_type"] == "Appointment")
        q = urllib.parse.quote(f"Appointment/{appt['external_id']}", safe="")
        url = f"{config.HAPI_BASE_URL}/Provenance?target={q}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            assert int(json.loads(resp.read()).get("total") or 0) == 1


# ---- 4 escalated ----

async def test_escalated(world):
    shift_id = world.uuid("SH-1")
    await db.enqueue_emr(world.agency_id, "escalated", shift_id, None, None,
                         f"escalated:{shift_id}:test4")
    assert await drain_outbox_once(agency_id=world.agency_id) == 1
    assert _outbox(world)[0]["done_at"]
    if world.backend == "hapi":
        task = next(l for l in _links(world) if l["external_type"] == "Task")
        body = _hapi_read("Task", task["external_id"])
        assert body["status"] == "on-hold"


# ---- 5 transient then success ----

async def test_transient_then_success(world, monkeypatch):
    target = _driver_class(world.backend)
    original = target.execute
    calls = {"n": 0}

    async def flaky(self, job, ctx):
        calls["n"] += 1
        if calls["n"] == 1:
            raise EmrTransientError("simulated 503")
        return await original(self, job, ctx)

    monkeypatch.setattr(target, "execute", flaky)
    shift_id = world.uuid("SH-1")
    await db.enqueue_emr(world.agency_id, "escalated", shift_id, None, None,
                         f"escalated:{shift_id}:test5")

    await drain_outbox_once(agency_id=world.agency_id)
    row = _outbox(world)[0]
    assert row["done_at"] is None and row["attempts"] == 1
    assert "503" in (row["last_error"] or "")
    assert len(_writeback_events(world, "emr_writeback_failed")) == 1

    _reopen(world, next_attempt_at="now()")
    await drain_outbox_once(agency_id=world.agency_id)
    row = _outbox(world)[0]
    assert row["done_at"] and row["attempts"] == 2
    assert len(_writeback_events(world)) == 1


# ---- 6 permanent dead-letters ----

async def test_permanent_dead_letters(world, monkeypatch):
    target = _driver_class(world.backend)

    async def broken(self, job, ctx):
        raise EmrPermanentError("simulated 400: bad resource")

    monkeypatch.setattr(target, "execute", broken)
    shift_id = world.uuid("SH-1")
    await db.enqueue_emr(world.agency_id, "escalated", shift_id, None, None,
                         f"escalated:{shift_id}:test6")

    await drain_outbox_once(agency_id=world.agency_id)
    row = _outbox(world)[0]
    assert row["dead_at"] is not None and row["attempts"] == 1
    dead = _writeback_events(world, "emr_writeback_dead")
    assert len(dead) == 1 and "permanent" in (dead[0]["outcome"] or "")
    assert await drain_outbox_once(agency_id=world.agency_id) == 0
    assert len(_writeback_events(world)) == 0


# ---- 7 crash resume ----

async def test_crash_resume(world):
    shift_id = world.uuid("SH-1")
    await db.enqueue_emr(world.agency_id, "escalated", shift_id, None, None,
                         f"escalated:{shift_id}:test7")

    claimed = await db.claim_outbox("obx-crashed", 10, world.agency_id)
    assert len(claimed) == 1
    assert await drain_outbox_once(agency_id=world.agency_id) == 0

    seed.client().table("outbox").update(
        {"claimed_at": "2020-01-01T00:00:00+00:00"}).eq(
        "agency_id", world.agency_id).execute()
    assert await drain_outbox_once(agency_id=world.agency_id) == 1
    assert _outbox(world)[0]["done_at"]
    assert len(_writeback_events(world)) == 1


# ---- 9 minimum necessary (FHIR bodies) ----

async def test_minimum_necessary(world):
    if world.backend != "hapi":
        pytest.skip("minimum-necessary inspects FHIR resources")
    shift_id = world.uuid("SH-1")
    assert await db.record_callout_with_outbox(shift_id, world.uuid("CG-OUT"), "sick")
    await drain_outbox_once(agency_id=world.agency_id)
    pat = next(l for l in _links(world) if l["external_type"] == "Patient")
    body = _hapi_read("Patient", pat["external_id"])
    assert "name" not in body
    assert "address" not in body
    prac = next(l for l in _links(world) if l["external_type"] == "Practitioner")
    pbody = _hapi_read("Practitioner", prac["external_id"])
    assert "telecom" not in pbody
    dumped = json.dumps(body) + json.dumps(pbody)
    assert "sick" not in dumped


# ---- 10 misconfiguration is visible ----

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


# ---- live polling drainer ----

async def test_live_drainer_timing(world):
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
        print(f"\n{world.backend} live drainer: callout -> event in {elapsed:.2f}s")
        assert elapsed < 10
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
