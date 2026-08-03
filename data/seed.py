"""Seed the Rock-Scheduler database: agency, fake roster, demo shifts.

  python -m data.seed                      idempotent (safe to re-run)
  python -m data.seed --me +19295550123    put YOUR phone on James Okafor so
                                           outreach texts/calls reach you

All nurse numbers are fake 555s by default; the worker skips those instead
of dialing Twilio, so a full backfill cascade can run without touching a
real phone until you opt in with --me.
"""

from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from data.db import client

ALL_WEEK = [{"dow": d, "start": "07:00", "end": "20:00"} for d in range(7)]

NURSES = [
    ("Maria Alvarez", "555-0101", ["wound care"], ["Jersey City"], 3, True),
    ("James Okafor", "555-0102", ["wound care"], ["Hoboken"], 2, True),
    ("Priya Natarajan", "555-0103", ["geriatric"], ["Jersey City"], 3, True),
    ("Tom Whitfield", "555-0104", ["wound care"], ["Newark"], 1, False),
    ("Elena Petrova", "555-0105", ["pediatric"], ["Montclair"], 2, True),
    ("Darnell Hayes", "555-0106", ["physical therapy"], ["Hackensack"], 3, True),
    ("Grace Lim", "555-0107", ["geriatric"], ["Edison"], 2, True),
    ("Robert Cianci", "555-0108", ["pediatric"], ["Princeton"], 2, False),
    ("Fatima Diallo", "555-0109", ["wound care"], ["Bayonne"], 1, True),
    ("Hannah Weiss", "555-0110", ["physical therapy"], ["Morristown"], 2, True),
]

PATIENTS = [
    ("Dorothy Chen", "Jersey City", ["wound care"]),
    ("Robert Rivera", "Hoboken", ["wound care", "geriatric"]),
]


def main(me: str | None) -> None:
    sb = client()

    agencies = sb.table("agencies").select("*").eq("name", "Rockram Home Health Care").execute().data
    agency = agencies[0] if agencies else sb.table("agencies").insert(
        {"name": "Rockram Home Health Care"}).execute().data[0]
    print(f"agency  : {agency['name']} ({agency['id'][:8]})")

    existing = {n["name"] for n in sb.table("nurses").select("name").execute().data}
    nurse_rows = [{
        "agency_id": agency["id"], "name": name, "phone": phone,
        "specialties": specs, "areas": areas, "pay_level": pay,
        "license_ok": licensed, "availability": ALL_WEEK,
    } for name, phone, specs, areas, pay, licensed in NURSES if name not in existing]
    if nurse_rows:
        sb.table("nurses").insert(nurse_rows).execute()
    print(f"nurses  : {len(nurse_rows)} inserted ({len(existing)} already present)")
    if me:
        sb.table("nurses").update({"phone": me}).eq("name", "James Okafor").execute()
        print(f"nurses  : James Okafor now rings {me}")

    for name, area, needs in PATIENTS:
        if not sb.table("patients").select("id").eq("name", name).execute().data:
            sb.table("patients").insert({
                "agency_id": agency["id"], "name": name, "area": area,
                "care_needs": needs,
            }).execute()
    patients = {p["name"]: p for p in sb.table("patients").select("*").execute().data}
    print(f"patients: {len(patients)}")

    if sb.table("shifts").select("id").limit(1).execute().data:
        print("shifts  : already present, skipping")
        return
    nurses = {n["name"]: n for n in sb.table("nurses").select("*").execute().data}
    tz = ZoneInfo(agency["timezone"])
    tomorrow_8am = datetime.combine(
        datetime.now(tz).date() + timedelta(days=1), time(8), tz)
    in_4_hours = datetime.now(tz) + timedelta(hours=4)
    sb.table("shifts").insert([
        {   # relaxed-ladder demo: ~1 day of lead time
            "agency_id": agency["id"], "patient_id": patients["Dorothy Chen"]["id"],
            "nurse_id": nurses["Maria Alvarez"]["id"], "specialty": "wound care",
            "area": "Jersey City", "starts_at": tomorrow_8am.isoformat(),
            "ends_at": (tomorrow_8am + timedelta(hours=8)).isoformat(), "pay_rate": 42,
        },
        {   # urgent-ladder demo: starts in ~4 hours
            "agency_id": agency["id"], "patient_id": patients["Robert Rivera"]["id"],
            "nurse_id": nurses["Fatima Diallo"]["id"], "specialty": "wound care",
            "area": "Hoboken", "starts_at": in_4_hours.isoformat(),
            "ends_at": (in_4_hours + timedelta(hours=6)).isoformat(), "pay_rate": 45,
        },
    ]).execute()
    print("shifts  : 2 created (tomorrow 8am relaxed, +4h urgent)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--me", help="your real phone in E.164; goes on James Okafor")
    main(parser.parse_args().me)
