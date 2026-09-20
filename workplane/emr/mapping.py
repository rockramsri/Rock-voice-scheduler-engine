"""FHIR R4 resource builders. Pure: rows in, dicts out, no I/O.

Every resource carries a Rock identifier so If-None-Exist / search can
find the same row on replay. Patient name/address and nurse phone are
omitted unless the agency flags say otherwise. Callout reasons never
appear — they stay in Rock's own events table.
"""

from __future__ import annotations

from datetime import UTC, datetime

IDENT_SYSTEM = "https://rockscheduler.dev/ids"


def ident(value: str) -> dict:
    return {"system": IDENT_SYSTEM, "value": value}


def compact_ts(iso: str | None) -> str:
    """YYYYMMDDHHMMSS from an ISO timestamp; 'none' if the shift had no callout."""
    if not iso:
        return "none"
    digits = "".join(c for c in str(iso) if c.isdigit())
    return digits[:14] or "none"


def fhir_instant(value: str | None) -> str:
    """UTC instant with a T and Z. Medplum rejects spaces; HAPI is looser."""
    raw = str(value).strip().replace(" ", "T") if value else ""
    if not raw:
        dt = datetime.now(UTC)
    else:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def human_name(full: str) -> dict:
    parts = (full or "").split(None, 1)
    if len(parts) == 2:
        return {"text": full, "given": [parts[0]], "family": parts[1]}
    return {"text": full, "family": full or "Unknown"}


def send_flags(agency: dict) -> tuple[bool, bool, bool]:
    return (bool(agency.get("emr_send_patient_name")),
            bool(agency.get("emr_send_address")),
            bool(agency.get("emr_send_nurse_phone")))


def organization(agency: dict) -> dict:
    return {
        "resourceType": "Organization",
        "active": True,
        "name": agency.get("name") or "Agency",
        "identifier": [ident(agency["id"])],
    }


def practitioner(nurse: dict, *, send_phone: bool) -> dict:
    resource = {
        "resourceType": "Practitioner",
        "active": bool(nurse.get("active", True)),
        "identifier": [ident(nurse["id"])],
        "name": [human_name(nurse.get("name") or "Nurse")],
    }
    if send_phone and nurse.get("phone"):
        resource["telecom"] = [{"system": "phone", "value": nurse["phone"]}]
    return resource


def patient(row: dict, *, send_name: bool, send_address: bool) -> dict:
    resource = {
        "resourceType": "Patient",
        "active": True,
        "identifier": [ident(row["id"])],
    }
    if send_name and row.get("name"):
        resource["name"] = [human_name(row["name"])]
    if send_address and row.get("address"):
        resource["address"] = [{"text": row["address"]}]
    return resource


def appointment(shift: dict, *, patient_ref: str | None,
                practitioner_ref: str | None, status: str = "booked") -> dict:
    parts = []
    if patient_ref:
        parts.append({"actor": {"reference": patient_ref}, "status": "accepted"})
    if practitioner_ref:
        parts.append({"actor": {"reference": practitioner_ref}, "status": "accepted"})
    resource = {
        "resourceType": "Appointment",
        "status": status,
        "identifier": [ident(shift["id"])],
        "participant": parts,
    }
    if shift.get("starts_at"):
        resource["start"] = fhir_instant(shift["starts_at"])
    if shift.get("ends_at"):
        resource["end"] = fhir_instant(shift["ends_at"])
    return resource


def task(ident_value: str, *, status: str, focus_ref: str | None = None) -> dict:
    resource = {
        "resourceType": "Task",
        "status": status,
        "intent": "order",
        "identifier": [ident(ident_value)],
        "code": {"text": "backfill-shift"},
    }
    if focus_ref:
        resource["focus"] = {"reference": focus_ref}
    return resource


def provenance(ident_value: str, *, target_ref: str, recorded: str) -> dict:
    return {
        "resourceType": "Provenance",
        "recorded": fhir_instant(recorded),
        "identifier": [ident(ident_value)],
        "target": [{"reference": target_ref}],
        "agent": [{"who": {"display": "Rock Scheduler"}}],
    }
