"""EHR → Rock identity sync. One shape in, one pair of upsert rules.

A change is a plain dict (kind, external ids, name, active, …). The FHIR
driver and the Medplum hook both land here. Rules:

  EHR wins  — name, active, specialties, language
  Rock wins — phone, preferences (never overwritten after the row exists)
  never delete — deactivate only
  unknown ids — ignored on incremental sync; import CLI passes create=True
"""

from __future__ import annotations

from data import db


def from_fhir(resource: dict) -> dict | None:
    """Practitioner/Patient → change dict. Anything else is ignored."""
    rtype = resource.get("resourceType")
    rid = resource.get("id")
    if not rtype or not rid:
        return None
    if rtype == "Practitioner":
        return {
            "kind": "nurse",
            "external_type": "Practitioner",
            "external_id": str(rid),
            "name": _name(resource),
            "active": bool(resource.get("active", True)),
            "specialties": _specialties(resource),
            "phone": _phone(resource),
        }
    if rtype == "Patient":
        return {
            "kind": "patient",
            "external_type": "Patient",
            "external_id": str(rid),
            "name": _name(resource),
            "language": _language(resource),
            "phone": _phone(resource),
        }
    return None


async def apply(agency_id: str, change: dict, *, create: bool = False,
                import_phone: bool = False) -> str | None:
    """Apply one change. Returns the Rock id, or None if we skipped it."""
    kind = change.get("kind")
    if kind == "nurse":
        return await db.upsert_nurse_from_emr(
            agency_id, change, create=create, import_phone=import_phone)
    if kind == "patient":
        return await db.upsert_patient_from_emr(
            agency_id, change, create=create, import_phone=import_phone)
    return None


async def apply_resource(agency_id: str, resource: dict, *, create: bool = False,
                         import_phone: bool = False) -> str | None:
    change = from_fhir(resource)
    if not change:
        return None
    return await apply(agency_id, change, create=create, import_phone=import_phone)


def _name(resource: dict) -> str | None:
    names = resource.get("name") or []
    if not names:
        return None
    first = names[0]
    if first.get("text"):
        return str(first["text"]).strip() or None
    given = " ".join(first.get("given") or [])
    family = first.get("family") or ""
    return f"{given} {family}".strip() or None


def _phone(resource: dict) -> str | None:
    for telecom in resource.get("telecom") or []:
        if telecom.get("system") == "phone" and telecom.get("value"):
            return str(telecom["value"])
    return None


def _specialties(resource: dict) -> list[str] | None:
    texts = []
    for qual in resource.get("qualification") or []:
        text = (qual.get("code") or {}).get("text")
        if text:
            texts.append(str(text))
    return texts or None


def _language(resource: dict) -> str | None:
    for comm in resource.get("communication") or []:
        text = (comm.get("language") or {}).get("text")
        coding = ((comm.get("language") or {}).get("coding") or [{}])[0]
        code = coding.get("code")
        if text:
            return str(text)
        if code:
            return str(code)
    return None
