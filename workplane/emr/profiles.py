"""Per-vendor FHIR knobs. The driver is one class; only these differ.

HAPI (lab/CI) is the first real profile. Medplum and OpenEMR add their
own rows here in later milestones. `before_create` is the hook for
vendor-required fields so domain mapping stays generic.
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

    def before_create(self, resource: dict) -> dict:
        return resource


def load_profile(name: str | None) -> FhirProfile:
    name = (name or "generic").strip()
    if name == "generic":
        return FhirProfile(name="generic")
    if name == "hapi":
        return FhirProfile(name="hapi",
                           default_base_url="http://localhost:8080/fhir")
    raise EmrPermanentError(f"unknown emr_profile: {name!r}")
