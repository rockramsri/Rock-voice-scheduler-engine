"""Sync-in rules and Medplum hook signature — no EHR required."""

import hashlib
import hmac
import json

from channels.webhook import medplum_signature_hex
from data.fhir_sync import from_fhir


def test_from_fhir_practitioner_reads_name_and_active():
    change = from_fhir({
        "resourceType": "Practitioner",
        "id": "p1",
        "active": False,
        "name": [{"text": "Ada Nurse", "family": "Nurse", "given": ["Ada"]}],
        "telecom": [{"system": "phone", "value": "555-0100"}],
    })
    assert change["kind"] == "nurse"
    assert change["name"] == "Ada Nurse"
    assert change["active"] is False
    assert change["phone"] == "555-0100"
    assert change["external_id"] == "p1"


def test_from_fhir_ignores_appointments():
    assert from_fhir({"resourceType": "Appointment", "id": "a1"}) is None


def test_medplum_signature_is_hmac_sha256_hex_of_raw_body():
    raw = b'{"resourceType":"Practitioner","id":"x"}'
    secret = "lab-secret"
    assert medplum_signature_hex(raw, secret) == hmac.new(
        secret.encode(), raw, hashlib.sha256).hexdigest()


async def test_medplum_hook_rejects_bad_signature(monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer
    from channels.webhook import build_app
    from shared import config

    monkeypatch.setattr(config, "MEDPLUM_HOOK_SECRET", "lab-secret")
    monkeypatch.setattr(config, "WEBHOOK_INSECURE_DEV", False)
    app = build_app()
    raw = json.dumps({"resourceType": "Practitioner", "id": "x"}).encode()
    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            "/emr/medplum/hook?agency=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            data=raw,
            headers={"X-Signature": "deadbeef",
                     "Content-Type": "application/fhir+json"})
        assert resp.status == 403
