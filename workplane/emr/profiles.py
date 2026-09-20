"""Per-vendor FHIR knobs. The driver is one class; only these differ.

HAPI is the CI target. Medplum adds client_credentials and drops
Provenance.identifier (the server schema has no such element).
`before_create` is the hook for vendor-required fields so domain
mapping stays generic.
"""

from __future__ import annotations

from dataclasses import dataclass

from workplane.emr.base import EmrPermanentError


@dataclass(frozen=True)
class FhirProfile:
    name: str
    default_base_url: str = ""
    default_auth_kind: str = "none"
    supports_conditional_create: bool = True
    # HAPI reports version conflicts as 409; Medplum uses 412. Treat both.
    conflict_statuses: tuple[int, ...] = (409, 412)
    # Resource types whose server cannot search by identifier.
    no_identifier_search: tuple[str, ...] = ()

    def before_create(self, resource: dict) -> dict:
        # Medplum's Provenance schema has no identifier element (lab: 400).
        if (self.name == "medplum"
                and resource.get("resourceType") == "Provenance"):
            resource = dict(resource)
            resource.pop("identifier", None)
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
    raise EmrPermanentError(f"unknown emr_profile: {name!r}")
