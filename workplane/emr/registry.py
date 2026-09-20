"""Driver selection — agencies.emr_backend picks the EmrClient class.

An unknown backend raises EmrPermanentError at drain time, which dead-letters
the row and writes an emr_writeback_dead event: misconfiguration shows up in
the console feed within seconds instead of hiding behind retries.
"""

from __future__ import annotations

from workplane.emr.base import EmrClient, EmrPermanentError
from workplane.emr.mock_driver import MockDriver


def build_client(agency: dict) -> EmrClient:
    backend = (agency.get("emr_backend") or "mock").strip()
    if backend == "mock":
        return MockDriver()
    # "fhir" arrives with M2 (workplane/emr/fhir_driver.py).
    raise EmrPermanentError(f"unknown emr_backend: {backend!r}")
