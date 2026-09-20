"""Onboarding import: EHR Practitioners (and optional Patients) → Rock.

  python -m data.import_fhir --agency UUID
  python -m data.import_fhir --agency UUID --patients --real-phones
  python -m data.import_fhir --agency UUID --bundle lab/sample_bundle.json

Default phones are fake 555s. `--real-phones` copies Practitioner.telecom
once; after that the number is Rock-owned and sync-in will not overwrite it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from data import db, fhir_sync
from shared import config
from workplane.emr.base import EmrContext
from workplane.emr.registry import build_client


def _resources_from_bundle(path: Path) -> list[dict]:
    bundle = json.loads(path.read_text())
    if bundle.get("resourceType") == "Bundle":
        return [e["resource"] for e in bundle.get("entry") or [] if e.get("resource")]
    return [bundle]


def _empty_ctx(agency: dict) -> EmrContext:
    return EmrContext(agency=agency, shift=None, nurse=None, patient=None,
                      links={}, secret=config.env_secret(agency.get("emr_secret_ref")))


async def import_agency(agency_id: str, *, patients: bool = False,
                        real_phones: bool = False,
                        resources: list[dict] | None = None) -> dict:
    agency = await db.agency_by_id(agency_id)
    if agency is None:
        raise SystemExit(f"agency {agency_id} not found")
    if resources is None:
        client = build_client(agency)
        resources = await client.pull_changes(None, _empty_ctx(agency))
    counts = {"nurses": 0, "patients": 0, "skipped": 0}
    for resource in resources:
        rtype = resource.get("resourceType")
        if rtype == "Patient" and not patients:
            counts["skipped"] += 1
            continue
        existed = await db.emr_link_by_external(
            agency_id, rtype or "", str(resource.get("id") or ""))
        rid = await fhir_sync.apply_resource(
            agency_id, resource, create=True, import_phone=real_phones)
        if not rid:
            counts["skipped"] += 1
            continue
        if rtype == "Patient":
            counts["patients"] += 0 if existed else 1
        elif rtype == "Practitioner":
            counts["nurses"] += 0 if existed else 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agency", required=True, help="agencies.id to import into")
    parser.add_argument("--patients", action="store_true",
                        help="also import Patient resources")
    parser.add_argument("--real-phones", action="store_true",
                        help="copy telecom phone on first insert only")
    parser.add_argument("--bundle", help="FHIR Bundle file instead of a server pull")
    args = parser.parse_args()
    resources = None
    if args.bundle:
        resources = _resources_from_bundle(Path(args.bundle))
    counts = asyncio.run(import_agency(
        args.agency, patients=args.patients, real_phones=args.real_phones,
        resources=resources))
    print(f"imported nurses={counts['nurses']} patients={counts['patients']} "
          f"skipped={counts['skipped']}")


if __name__ == "__main__":
    main()
