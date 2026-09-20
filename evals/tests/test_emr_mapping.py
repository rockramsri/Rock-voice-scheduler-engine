"""Pure FHIR mapping tests — flags, identifiers, no I/O."""

from workplane.emr.fhir_driver import _token_url
from workplane.emr.mapping import (
    IDENT_SYSTEM, compact_ts, fhir_instant, human_name, organization, patient,
    practitioner, send_flags,
)
from workplane.emr.profiles import load_profile

AGENCY = {"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "name": "Rock Lab"}
NURSE = {"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "name": "Ada Nurse",
         "phone": "555-0100", "active": True}
PATIENT = {"id": "cccccccc-cccc-cccc-cccc-cccccccccccc", "name": "Pat Patient",
           "address": "1 Main St"}


def test_human_name_splits_first_word():
    assert human_name("Ada Nurse") == {
        "text": "Ada Nurse", "given": ["Ada"], "family": "Nurse"}


def test_compact_ts_strips_to_14_digits():
    assert compact_ts("2026-09-21T12:00:00+00:00") == "20260921120000"
    assert compact_ts(None) == "none"


def test_organization_uses_rock_identifier():
    org = organization(AGENCY)
    assert org["identifier"] == [{"system": IDENT_SYSTEM, "value": AGENCY["id"]}]
    assert org["name"] == "Rock Lab"


def test_flags_default_off():
    assert send_flags({}) == (False, False, False)
    assert send_flags({"emr_send_patient_name": True}) == (True, False, False)


def test_patient_omits_name_and_address_when_flags_off():
    resource = patient(PATIENT, send_name=False, send_address=False)
    assert "name" not in resource
    assert "address" not in resource
    assert resource["identifier"][0]["value"] == PATIENT["id"]


def test_patient_includes_name_and_address_when_flags_on():
    resource = patient(PATIENT, send_name=True, send_address=True)
    assert resource["name"][0]["family"] == "Patient"
    assert resource["address"][0]["text"] == "1 Main St"


def test_practitioner_phone_is_opt_in():
    off = practitioner(NURSE, send_phone=False)
    on = practitioner(NURSE, send_phone=True)
    assert "telecom" not in off
    assert on["telecom"][0]["value"] == "555-0100"


def test_medplum_token_url_is_on_the_server_root():
    assert _token_url("http://localhost:8103/fhir/R4") == "http://localhost:8103/oauth2/token"
    assert _token_url("http://localhost:8080/fhir") == "http://localhost:8080/oauth2/token"


def test_fhir_instant_uses_t_and_z():
    assert fhir_instant("2026-09-20 13:24:01.123456+00:00") == "2026-09-20T13:24:01Z"
    assert fhir_instant("2026-09-20T13:24:01+00:00") == "2026-09-20T13:24:01Z"


def test_medplum_strips_provenance_identifier():
    body = {"resourceType": "Provenance", "identifier": [{"value": "x"}],
            "target": [{"reference": "Appointment/1"}]}
    assert "identifier" not in load_profile("medplum").before_create(body)
    assert "identifier" in load_profile("hapi").before_create(dict(body))


def test_reason_never_in_mapped_resources():
    # Mapping functions have no reason parameter — this is the guarantee.
    blob = str(organization(AGENCY)) + str(practitioner(NURSE, send_phone=True))
    blob += str(patient(PATIENT, send_name=True, send_address=True))
    assert "sick" not in blob
    assert "reason" not in blob
