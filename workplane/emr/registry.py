"""Driver selection — agencies.emr_backend picks the EmrClient class.

An unknown backend raises EmrPermanentError at drain time, which dead-letters
the row and writes an emr_writeback_dead event: misconfiguration shows up in
the console feed within seconds instead of hiding behind retries.
"""

from __future__ import annotations

from workplane.emr.base import EmrClient, EmrPermanentError
from workplane.emr.mock_driver import MockDriver
from workplane.emr.stubs import AxisCareDriver, WellSkyDriver

# fhir + vendor aliases all share FhirDriver; the profile is the vendor knob.
_FHIR = {"fhir", "hapi", "medplum", "openemr"}
_STUBS = {"axiscare": AxisCareDriver, "wellsky": WellSkyDriver}


def build_client(agency: dict) -> EmrClient:
    backend = (agency.get("emr_backend") or "mock").strip()
    if backend == "mock":
        return MockDriver()
    if backend in _FHIR:
        from workplane.emr.fhir_driver import FhirDriver
        from workplane.emr.profiles import load_profile
        profile = agency.get("emr_profile") or (backend if backend != "fhir" else "generic")
        return FhirDriver(agency, load_profile(profile))
    stub = _STUBS.get(backend)
    if stub:
        return stub()
    raise EmrPermanentError(f"unknown emr_backend: {backend!r}")
