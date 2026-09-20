"""EMR contract suite — every backend in EMR_TEST_BACKENDS must pass.

M1 = mock. M2 = hapi. M3 = medplum. Unreachable servers skip. Numbering
follows docs/emr-architecture.md §7.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from data import db
from evals import seed
from shared import config
from workplane.emr.base import EmrPermanentError, EmrTransientError
from workplane.emr.mapping import IDENT_SYSTEM
from workers.outbox_worker import drain_outbox_once

_MEDPLUM_SECRET_ENV = "EMR_TEST_MEDPLUM_SECRET"


def _reachable(url: str, timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


def _http_json(method: str, url: str, *, payload=None, headers=None, form=None):
    hdrs = dict(headers or {})
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        hdrs.setdefault("Content-Type", "application/json")
    elif form is not None:
        body = urllib.parse.urlencode(form).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"null")
        except json.JSONDecodeError:
            return exc.code, {"_raw": raw[:200].decode(errors="replace")}


def _medplum_mint() -> tuple[str, str, str]:
    """Admin login → mint a ClientApplication → client_credentials token."""
    root = config.MEDPLUM_BASE_URL
    _, login = _http_json("POST", f"{root}/auth/login", payload={
        "email": "admin@example.com", "password": "medplum_admin",
        "codeChallengeMethod": "plain", "codeChallenge": "lab",
    })
    if not login.get("code"):
        pytest.skip("Medplum admin login failed")
    _, tok = _http_json("POST", f"{root}/oauth2/token", form={
        "grant_type": "authorization_code", "code": login["code"],
        "code_verifier": "lab",
    })
    user = tok.get("access_token")
    if not user:
        pytest.skip("Medplum admin token failed")
    auth = {"Authorization": f"Bearer {user}"}
    _, me = _http_json("GET", f"{root}/auth/me", headers=auth)
    proj = (me.get("project") or {}).get("id")
    _, app = _http_json("POST", f"{root}/admin/projects/{proj}/client",
                        headers=auth, payload={"name": "Rock Eval Drainer"})
    if not (app.get("id") and app.get("secret")):
        pytest.skip("Medplum client mint failed")
    _, cc = _http_json("POST", f"{root}/oauth2/token", form={
        "grant_type": "client_credentials",
        "client_id": app["id"], "client_secret": app["secret"],
    })
    if not cc.get("access_token"):
        pytest.skip("Medplum client_credentials failed")
    return app["id"], app["secret"], cc["access_token"]


@pytest.fixture(scope="session")
def medplum_creds():
    if not _reachable(f"{config.MEDPLUM_BASE_URL}/healthcheck"):
        pytest.skip("Medplum not reachable")
    return _medplum_mint()


def _fhir_json(world, path: str) -> dict:
    req = urllib.request.Request(
        f"{world.fhir_base}/{path.lstrip('/')}",
        headers={"Accept": "application/fhir+json", **world.fhir_headers})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _fhir_total(world, rtype: str, value: str) -> int:
    q = urllib.parse.quote(f"{IDENT_SYSTEM}|{value}", safe="")
    bundle = _fhir_json(world, f"{rtype}?identifier={q}")
    if bundle.get("total") is not None:
        return int(bundle["total"])
    return len(bundle.get("entry") or [])


def _fhir_read(world, rtype: str, rid: str) -> dict:
    return _fhir_json(world, f"{rtype}/{rid}")


def _fhir_put(world, resource: dict) -> dict:
    rtype, rid = resource["resourceType"], resource["id"]
    headers = {"Accept": "application/fhir+json",
               "Content-Type": "application/fhir+json", **world.fhir_headers}
    vid = (resource.get("meta") or {}).get("versionId")
    if vid:
        headers["If-Match"] = f'W/"{vid}"'
    req = urllib.request.Request(
        f"{world.fhir_base}/{rtype}/{rid}",
        data=json.dumps(resource).encode(), method="PUT", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


async def _push_hook(world, resource: dict, *, secret: str) -> int:
    from aiohttp.test_utils import TestClient, TestServer
    from channels.webhook import build_app, medplum_signature_hex

    raw = json.dumps(resource).encode()
    app = build_app()
    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            f"/emr/medplum/hook?agency={world.agency_id}",
            data=raw,
            headers={"X-Signature": medplum_signature_hex(raw, secret),
                     "X-Medplum-Interaction": "update",
                     "Content-Type": "application/fhir+json"})
        return resp.status


@pytest.fixture(params=list(config.EMR_TEST_BACKENDS))
async def world(eval_db, request):
    backend = request.param
    agency = {}
    fhir_base, fhir_headers = None, {}
    if backend == "hapi":
        if not _reachable(f"{config.HAPI_BASE_URL}/metadata"):
            pytest.skip("HAPI not reachable")
        agency = {
            "emr_backend": "hapi", "emr_profile": "hapi",
            "emr_base_url": config.HAPI_BASE_URL, "emr_auth_kind": "none",
        }
        fhir_base = config.HAPI_BASE_URL
    elif backend == "medplum":
        cid, secret, token = request.getfixturevalue("medplum_creds")
        os.environ[_MEDPLUM_SECRET_ENV] = secret
        agency = {
            "emr_backend": "medplum", "emr_profile": "medplum",
            "emr_base_url": config.MEDPLUM_FHIR_URL,
            "emr_auth_kind": "client_credentials",
            "emr_client_id": cid, "emr_secret_ref": _MEDPLUM_SECRET_ENV,
        }
        fhir_base = config.MEDPLUM_FHIR_URL
        fhir_headers = {"Authorization": f"Bearer {token}"}
    elif backend != "mock":
        pytest.skip(f"{backend} is not a contract target yet")
    run = seed.seed_run(
        roster=[{"slug": "CG-OUT"}, {"slug": "CG-WIN"}],
        shifts=[{"slug": "SH-1", "nurse": "CG-OUT", "starts_in_hours": 26,
                 "status": "scheduled"}],
        agency=agency,
    )
    run.backend = backend
    run.fhir_base = fhir_base
    run.fhir_headers = fhir_headers
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
    if world.fhir_base:
        assert _fhir_total(world, "Organization", aid) == 1
        assert _fhir_total(world, "Appointment", sid) == 1


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
    if world.fhir_base:
        assert _fhir_total(world, "Appointment", shift_id) == 1
        appt = next(l for l in _links(world) if l["external_type"] == "Appointment")
        q = urllib.parse.quote(f"Appointment/{appt['external_id']}", safe="")
        bundle = _fhir_json(world, f"Provenance?target={q}")
        n = bundle.get("total")
        assert (int(n) if n is not None else len(bundle.get("entry") or [])) == 1


# ---- 4 escalated ----

async def test_escalated(world):
    shift_id = world.uuid("SH-1")
    await db.enqueue_emr(world.agency_id, "escalated", shift_id, None, None,
                         f"escalated:{shift_id}:test4")
    assert await drain_outbox_once(agency_id=world.agency_id) == 1
    assert _outbox(world)[0]["done_at"]
    if world.fhir_base:
        task = next(l for l in _links(world) if l["external_type"] == "Task")
        body = _fhir_read(world, "Task", task["external_id"])
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


# ---- 8 sync-in: EHR wins name/active; Rock keeps phone + preferences ----

async def test_sync_in(world, monkeypatch):
    if not world.fhir_base:
        pytest.skip("sync-in needs a FHIR server")
    nid = world.uuid("CG-OUT")
    await db.enqueue_emr(world.agency_id, "upsert_practitioner", None, nid, None,
                         f"upsert_practitioner:{nid}:sync")
    assert await drain_outbox_once(agency_id=world.agency_id) == 1
    link = next(l for l in _links(world)
                if l["external_type"] == "Practitioner" and l["rock_id"] == nid)

    seed.client().table("nurses").update({
        "phone": "555-0199", "preferences": {"notes": "keep-me"},
    }).eq("id", nid).execute()

    body = _fhir_read(world, "Practitioner", link["external_id"])
    body["name"] = [{"text": "Renamed Nurse", "family": "Nurse", "given": ["Renamed"]}]
    _fhir_put(world, body)

    if world.backend == "medplum":
        monkeypatch.setattr(config, "MEDPLUM_HOOK_SECRET", "eval-hook")
        assert await _push_hook(world, _fhir_read(world, "Practitioner",
                                                 link["external_id"]),
                                secret="eval-hook") == 200
    else:
        from workers.outbox_worker import sync_pull_once
        seed.client().table("agencies").update({"emr_sync_mode": "pull"}).eq(
            "id", world.agency_id).execute()
        await sync_pull_once(world.agency_id, since=None)

    row = (seed.client().table("nurses").select("*").eq("id", nid).execute().data[0])
    assert row["name"] == "Renamed Nurse"
    assert row["phone"] == "555-0199"
    assert (row.get("preferences") or {}).get("notes") == "keep-me"

    body = _fhir_read(world, "Practitioner", link["external_id"])
    body["active"] = False
    _fhir_put(world, body)
    if world.backend == "medplum":
        assert await _push_hook(world, _fhir_read(world, "Practitioner",
                                                 link["external_id"]),
                                secret="eval-hook") == 200
    else:
        from workers.outbox_worker import sync_pull_once
        await sync_pull_once(world.agency_id, since=None)

    row = (seed.client().table("nurses").select("*").eq("id", nid).execute().data[0])
    assert row["active"] is False


# ---- 9 minimum necessary (FHIR bodies) ----

async def test_minimum_necessary(world):
    if not world.fhir_base:
        pytest.skip("minimum-necessary inspects FHIR resources")
    shift_id = world.uuid("SH-1")
    assert await db.record_callout_with_outbox(shift_id, world.uuid("CG-OUT"), "sick")
    assert await db.lock_shift_with_outbox(shift_id, world.uuid("CG-WIN"))
    await drain_outbox_once(agency_id=world.agency_id)
    pat = next(l for l in _links(world) if l["external_type"] == "Patient")
    body = _fhir_read(world, "Patient", pat["external_id"])
    assert "name" not in body
    assert "address" not in body
    prac = next(l for l in _links(world) if l["external_type"] == "Practitioner")
    pbody = _fhir_read(world, "Practitioner", prac["external_id"])
    assert "telecom" not in pbody
    appt = next(l for l in _links(world) if l["external_type"] == "Appointment")
    task = next(l for l in _links(world) if l["external_type"] == "Task")
    dumped = json.dumps({
        "Patient": body, "Practitioner": pbody,
        "Appointment": _fhir_read(world, "Appointment", appt["external_id"]),
        "Task": _fhir_read(world, "Task", task["external_id"]),
    })
    assert "sick" not in dumped
    assert "555-" not in dumped
    print(f"\n{world.backend} minimum-necessary dump (no PHI): {dumped[:400]}")


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
