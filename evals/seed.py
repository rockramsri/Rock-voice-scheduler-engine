"""Eval DB plumbing: env swap, safety guard, per-run seeding, snapshot, cleanup.

The one rule that keeps evals safe: `load_eval_env()` must run BEFORE anything
imports `shared.config` (which freezes SUPABASE_* at import time). The pytest
conftest and every runner import this module first. If production modules were
imported too early, `require_eval_db()` catches it and refuses loudly.

Isolation model: every run seeds a FRESH agency row and hangs all of its
nurses/patients/shifts off it (new UUIDs each time), so parallel runs never
contend and cleanup is a delete-by-agency. See ARCHITECTURE.md §3.
"""

from __future__ import annotations

import os
import uuid as uuidlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import dotenv_values

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent
ARTIFACTS_DIR = EVALS_DIR / "artifacts"

_env_state: str | None = None   # None = not attempted | "ok" | "missing"


def load_eval_env() -> bool:
    """Point SUPABASE_* at the eval project. Returns False if not configured.

    Reads evals/.env.eval and sets os.environ BEFORE shared.config can freeze
    values (real env vars win because config's load_dotenv never overrides).
    Hard-refuses to proceed if the eval URL is missing or equals production's.
    """
    global _env_state
    if _env_state is not None:
        return _env_state == "ok"

    # File first (local dev), process env as fallback (hosted: Railway etc.).
    values = dotenv_values(EVALS_DIR / ".env.eval")
    url = values.get("EVAL_SUPABASE_URL") or os.environ.get("EVAL_SUPABASE_URL", "")
    key = (values.get("EVAL_SUPABASE_SERVICE_ROLE_KEY")
           or os.environ.get("EVAL_SUPABASE_SERVICE_ROLE_KEY", ""))
    if not url or not key:
        _env_state = "missing"
        return False

    prod_url = (dotenv_values(REPO_ROOT / ".env").get("SUPABASE_URL") or "").rstrip("/")
    if url.rstrip("/") == prod_url:
        raise SystemExit("REFUSING: EVAL_SUPABASE_URL equals the production SUPABASE_URL")

    os.environ["SUPABASE_URL"] = url
    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = key
    for name, value in values.items():           # JUDGE_MODEL etc.
        if value and name not in ("EVAL_SUPABASE_URL", "EVAL_SUPABASE_SERVICE_ROLE_KEY"):
            os.environ.setdefault(name, value)
    _env_state = "ok"
    return True


def require_eval_db() -> None:
    """Assert the swap actually took effect (catches too-early config imports)."""
    if not load_eval_env():
        raise RuntimeError("evals/.env.eval is not configured — see env.eval.example")
    from shared import config   # safe now: env already swapped
    if config.SUPABASE_URL != os.environ["SUPABASE_URL"]:
        raise SystemExit(
            "REFUSING: shared.config was imported before load_eval_env(); "
            "it is frozen on the production database"
        )


def client():
    """The supabase client, guaranteed to point at the eval project."""
    require_eval_db()
    from data import db   # lazy: import only after the env swap is proven
    return db.client()


# ---- per-run seeding ----

ALL_WEEK = [{"dow": d, "start": "07:00", "end": "20:00"} for d in range(7)]

NURSE_DEFAULTS = dict(specialties=["wound care"], areas=["Jersey City"], pay_level=2,
                      license_ok=True, reliability=0.7, max_hours_week=40,
                      availability=ALL_WEEK, active=True, preferences={})


@dataclass
class Run:
    """Handles to one seeded world; slug_map translates CG-xxx/SH-xxx to UUIDs."""
    agency_id: str
    slug_map: dict[str, str] = field(default_factory=dict)
    nurse_ids: list[str] = field(default_factory=list)
    shift_ids: list[str] = field(default_factory=list)
    patient_ids: list[str] = field(default_factory=list)

    def uuid(self, slug: str) -> str:
        return self.slug_map[slug]


def seed_run(roster: list[dict], shifts: list[dict] | None = None,
             patients: list[dict] | None = None, agency: dict | None = None) -> Run:
    """Seed one namespaced world. All numbers are fake 555s (never dialed).

    roster entries: {slug, name?, phone?, + any nurses-table column}.
    shift entries:  {slug, patient (slug), nurse (slug|None), specialty, area,
                     starts_in_hours, duration_hours=8, status="scheduled",
                     pay_rate=40, callout_nurse (slug)?}
    Times are offsets from now so scenarios never go stale.
    """
    sb = client()
    tag = uuidlib.uuid4().hex[:8]
    run = Run(agency_id="")

    agency_row = {"name": f"Eval Agency {tag}", **(agency or {})}
    run.agency_id = sb.table("agencies").insert(agency_row).execute().data[0]["id"]
    run.slug_map["AGENCY"] = run.agency_id

    for i, spec in enumerate(roster):
        spec = dict(spec)
        slug = spec.pop("slug")
        row = {**NURSE_DEFAULTS,
               "name": spec.pop("name", f"Nurse {slug}"),
               "phone": spec.pop("phone", f"555-9{i:03d}"),
               "agency_id": run.agency_id, **spec}
        nurse_id = sb.table("nurses").insert(row).execute().data[0]["id"]
        run.slug_map[slug] = nurse_id
        run.nurse_ids.append(nurse_id)

    for spec in (patients or [{"slug": "PT-1", "name": "Eval Patient", "area": "Jersey City"}]):
        spec = dict(spec)
        slug = spec.pop("slug")
        row = {"agency_id": run.agency_id, "care_needs": ["wound care"], **spec}
        pid = sb.table("patients").insert(row).execute().data[0]["id"]
        run.slug_map[slug] = pid
        run.patient_ids.append(pid)

    now = datetime.now(UTC)
    for spec in (shifts or []):
        spec = dict(spec)
        slug = spec.pop("slug")
        starts = now + timedelta(hours=spec.pop("starts_in_hours", 26))
        ends = starts + timedelta(hours=spec.pop("duration_hours", 8))
        nurse = spec.pop("nurse", None)
        callout_nurse = spec.pop("callout_nurse", None)
        row = {"agency_id": run.agency_id,
               "patient_id": run.uuid(spec.pop("patient", "PT-1")),
               "nurse_id": run.uuid(nurse) if nurse else None,
               "specialty": spec.pop("specialty", "wound care"),
               "area": spec.pop("area", "Jersey City"),
               "starts_at": starts.isoformat(), "ends_at": ends.isoformat(),
               "pay_rate": spec.pop("pay_rate", 40),
               "status": spec.pop("status", "scheduled"), **spec}
        if callout_nurse:
            row.update({"callout_nurse_id": run.uuid(callout_nurse),
                        "callout_at": now.isoformat(),
                        "next_action_at": now.isoformat()})
        shift_id = sb.table("shifts").insert(row).execute().data[0]["id"]
        run.slug_map[slug] = shift_id
        run.shift_ids.append(shift_id)

    return run


def snapshot(run: Run, save_to: str | Path | None = None):
    """Dump the run's rows into a DbSnapshot (the oracle's whole world)."""
    from evals.contracts import DbSnapshot

    sb = client()
    snap = DbSnapshot(run_agency_id=run.agency_id, slug_map=dict(run.slug_map))
    for table in ("agencies", "nurses", "patients", "shifts", "offers"):
        query = sb.table(table).select("*")
        if table == "offers":
            if not run.shift_ids:
                continue
            query = query.in_("shift_id", run.shift_ids)
        elif table == "agencies":
            query = query.eq("id", run.agency_id)
        else:
            query = query.eq("agency_id", run.agency_id)
        setattr(snap, table, query.execute().data)

    events: dict[int, dict] = {}
    if run.shift_ids:
        for row in (sb.table("events").select("*")
                    .in_("shift_id", run.shift_ids).execute().data):
            events[row["id"]] = row
    if run.nurse_ids:
        for row in (sb.table("events").select("*")
                    .in_("nurse_id", run.nurse_ids).execute().data):
            events[row["id"]] = row
    snap.events = sorted(events.values(), key=lambda e: (e["at"], e["id"]))

    if save_to:
        snap.save(save_to)
    return snap


def cleanup(run: Run) -> None:
    """Delete the run's rows in FK order. Safe to call twice."""
    sb = client()
    if run.shift_ids:
        sb.table("events").delete().in_("shift_id", run.shift_ids).execute()
        sb.table("offers").delete().in_("shift_id", run.shift_ids).execute()
    if run.nurse_ids:
        sb.table("events").delete().in_("nurse_id", run.nurse_ids).execute()
    sb.table("shifts").delete().eq("agency_id", run.agency_id).execute()
    sb.table("patients").delete().eq("agency_id", run.agency_id).execute()
    sb.table("nurses").delete().eq("agency_id", run.agency_id).execute()
    sb.table("agencies").delete().eq("id", run.agency_id).execute()
