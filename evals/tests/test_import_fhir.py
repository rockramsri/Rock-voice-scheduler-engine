"""Onboarding import: create on first sight, fake 555s, phones stay Rock's."""

from data import fhir_sync
from data.import_fhir import import_agency
from evals import seed


async def test_import_creates_nurse_with_fake_phone(eval_db):
    run = seed.seed_run(roster=[], agency={"emr_backend": "mock"})
    try:
        rid = await fhir_sync.apply(run.agency_id, {
            "kind": "nurse", "external_type": "Practitioner",
            "external_id": "imp-1", "name": "Imported Ada",
            "phone": "201-555-0199", "active": True,
        }, create=True, import_phone=False)
        row = (seed.client().table("nurses").select("*").eq("id", rid).execute().data[0])
        assert row["name"] == "Imported Ada"
        assert row["phone"].startswith("555-")
        assert row["phone"] != "201-555-0199"
        assert row["source"] == "emr"
    finally:
        seed.cleanup(run)


async def test_import_real_phones_only_on_first_insert(eval_db):
    run = seed.seed_run(roster=[], agency={"emr_backend": "mock"})
    try:
        rid = await fhir_sync.apply(run.agency_id, {
            "kind": "nurse", "external_type": "Practitioner",
            "external_id": "imp-2", "name": "Phone Ada",
            "phone": "201-555-0199", "active": True,
        }, create=True, import_phone=True)
        assert seed.client().table("nurses").select("phone").eq(
            "id", rid).execute().data[0]["phone"] == "201-555-0199"
        await fhir_sync.apply(run.agency_id, {
            "kind": "nurse", "external_type": "Practitioner",
            "external_id": "imp-2", "name": "Phone Ada",
            "phone": "201-555-0000", "active": True,
        }, create=True, import_phone=True)
        assert seed.client().table("nurses").select("phone").eq(
            "id", rid).execute().data[0]["phone"] == "201-555-0199"
    finally:
        seed.cleanup(run)


async def test_bundle_import_is_idempotent(eval_db):
    run = seed.seed_run(roster=[], agency={"emr_backend": "mock"})
    try:
        resources = [
            {"resourceType": "Practitioner", "id": "imp-3",
             "name": [{"text": "Bundle Nurse"}], "active": True},
            {"resourceType": "Patient", "id": "imp-pt",
             "name": [{"text": "Bundle Patient"}]},
        ]
        first = await import_agency(run.agency_id, patients=True, resources=resources)
        second = await import_agency(run.agency_id, patients=True, resources=resources)
        assert first == {"nurses": 1, "patients": 1, "skipped": 0}
        assert second == {"nurses": 0, "patients": 0, "skipped": 0}
        nurses = seed.client().table("nurses").select("id").eq(
            "agency_id", run.agency_id).execute().data
        assert len(nurses) == 1
    finally:
        seed.cleanup(run)
