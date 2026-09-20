"""Per-vendor FHIR knobs. The driver is one class; only these differ.

`before_create` adds vendor-required fields so mapping stays generic.
"""

from __future__ import annotations

from dataclasses import dataclass

from workplane.emr.base import EmrPermanentError

_NPI = "http://hl7.org/fhir/sid/us-npi"


def _npi(rock_id: str) -> str:
    """10-digit placeholder NPI from a Rock id. Lab servers require the field."""
    hexish = "".join(c for c in str(rock_id) if c in "0123456789abcdef") or "1"
    return f"{int(hexish[:12], 16) % 10 ** 10:010d}"


@dataclass(frozen=True)
class FhirProfile:
    name: str
    default_base_url: str = ""
    default_auth_kind: str = "none"
    supports_conditional_create: bool = True
    # HAPI reports version conflicts as 409; Medplum uses 412. Treat both.
    conflict_statuses: tuple[int, ...] = (409, 412)
    no_identifier_search: tuple[str, ...] = ()
    skip_types: tuple[str, ...] = ()
    rest_appointment: bool = False
    verify_tls: bool = True

    def token_url(self, fhir_base: str) -> str:
        base = fhir_base.rstrip("/")
        if self.name == "openemr":
            root = (base.split("/apis/", 1)[0] if "/apis/" in base
                    else base.split("/fhir", 1)[0])
            return root + "/oauth2/default/token"
        if base.endswith("/fhir/R4"):
            return base[: -len("/fhir/R4")] + "/oauth2/token"
        if "/fhir" in base:
            return base.split("/fhir", 1)[0] + "/oauth2/token"
        return base + "/oauth2/token"

    def rest_base(self, fhir_base: str) -> str:
        base = fhir_base.rstrip("/")
        if base.endswith("/fhir"):
            return base[: -len("/fhir")] + "/api"
        return base + "/api"

    def before_create(self, resource: dict) -> dict:
        rtype = resource.get("resourceType")
        if self.name == "medplum" and rtype == "Provenance":
            resource = dict(resource)
            resource.pop("identifier", None)
            return resource
        if self.name != "openemr":
            return resource
        resource = dict(resource)
        if rtype in ("Practitioner", "Organization"):
            idents = list(resource.get("identifier") or [])
            if not any(i.get("system") == _NPI for i in idents):
                seed = (idents[0].get("value") if idents else "1") or "1"
                idents.append({"system": _NPI, "value": _npi(str(seed))})
            resource["identifier"] = idents
        if rtype in ("Practitioner", "Patient"):
            names = list(resource.get("name") or [{}])
            n = dict(names[0])
            n["use"] = "official"
            n.setdefault("family", "Unknown")
            if not n.get("given"):
                n["given"] = ["Patient" if rtype == "Patient" else "Nurse"]
            resource["name"] = [n]
        if rtype == "Patient":
            resource.setdefault("gender", "unknown")
            resource.setdefault("birthDate", "1970-01-01")
        return resource


def load_profile(name: str | None) -> FhirProfile:
    name = (name or "generic").strip()
    if name == "generic":
        return FhirProfile(name="generic")
    if name == "hapi":
        return FhirProfile(name="hapi",
                           default_base_url="http://localhost:8080/fhir",
                           no_identifier_search=("Provenance",))
    if name == "medplum":
        return FhirProfile(name="medplum",
                           default_base_url="http://localhost:8103/fhir/R4",
                           default_auth_kind="client_credentials",
                           no_identifier_search=("Provenance",))
    if name == "openemr":
        return FhirProfile(
            name="openemr",
            default_base_url="https://localhost:9300/apis/default/fhir",
            default_auth_kind="oauth2_password",
            supports_conditional_create=False,
            skip_types=("Task", "Provenance"),
            rest_appointment=True,
            verify_tls=False,
        )
    raise EmrPermanentError(f"unknown emr_profile: {name!r}")
