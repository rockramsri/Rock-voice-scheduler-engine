"""Supabase data access — the only module that talks to Postgres.

supabase-py is sync, so every call runs in a thread to keep the event loop
free. Two discipline rules enforced here: state transitions are ALWAYS
guarded (WHERE carries the expected previous state, so races lose cleanly),
and rungs are bumped BEFORE sending anything (no duplicate outreach).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from supabase import Client, create_client

from shared import config, redact

_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY):
            raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing in .env")
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
    return _client


async def _run(fn) -> Any:
    return await asyncio.to_thread(fn)


# ---- reads ----

async def fetch_agency() -> dict:
    rows = (await _run(lambda: client().table("agencies").select("*").limit(1).execute())).data
    if not rows:
        raise SystemExit("no agency row — run `python -m data.seed` first")
    return rows[0]


async def fetch_active_nurses() -> list[dict]:
    result = await _run(lambda: client().table("nurses").select("*")
                        .eq("active", True).execute())
    return result.data


def _escape_like(value: str) -> str:
    """Neutralize ILIKE wildcards so caller text matches literally.

    Postgres LIKE/ILIKE treats % and _ as wildcards (default escape '\\'), so a
    name of "%" would otherwise match every nurse. Escape backslash first.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def find_nurse_by_name(name: str) -> dict | None:
    """Case-insensitive exact match, then prefix match (wildcards escaped)."""
    wanted = name.strip()
    if not wanted:
        return None
    pattern = _escape_like(wanted)

    def _q():
        # Exact (case-insensitive) name wins; fall back to a prefix match.
        # Fresh builders per query so filters never accumulate.
        exact = (client().table("nurses").select("*")
                 .ilike("name", pattern).limit(1).execute())
        if exact.data:
            return exact
        return (client().table("nurses").select("*")
                .ilike("name", f"{pattern}%").limit(1).execute())

    result = await _run(_q)
    return result.data[0] if result.data else None


def _phone_digits(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())


async def find_nurses_by_phone(phone: str) -> list[dict]:
    """Active nurses on this number (exact E.164, else last-10-digit match)."""
    clean = phone.removeprefix("whatsapp:").strip()
    exact = await _run(lambda: client().table("nurses").select("*")
                       .eq("phone", clean).eq("active", True).execute())
    if exact.data:
        return exact.data
    wanted = _phone_digits(clean)[-10:]
    if len(wanted) < 10:
        return []
    nurses = await fetch_active_nurses()
    return [n for n in nurses if _phone_digits(n.get("phone") or "")[-10:] == wanted]


async def upcoming_shifts_for(nurse_id: str, limit: int = 3) -> list[dict]:
    """Next scheduled shifts for this nurse, soonest first."""
    result = await _run(lambda: client().table("shifts")
                        .select("*, patients(name, area)")
                        .eq("nurse_id", nurse_id).eq("status", "scheduled")
                        .order("starts_at").limit(limit).execute())
    return result.data or []


async def next_shift_for(nurse_id: str) -> dict | None:
    rows = await upcoming_shifts_for(nurse_id, limit=1)
    return rows[0] if rows else None


def agency_display_name(row: dict | None, default: str = "the agency") -> str:
    """Agency name from an agency row or a nested `agencies` join."""
    if not row:
        return default
    nested = row.get("agencies")
    if isinstance(nested, dict) and nested.get("name"):
        return str(nested["name"])
    if row.get("name") and ("timezone" in row or "quiet_start" in row):
        return str(row["name"])
    return default


async def get_shift(shift_id: str) -> dict | None:
    result = await _run(lambda: client().table("shifts")
                        .select("*, agencies(name)")
                        .eq("id", shift_id).limit(1).execute())
    return result.data[0] if result.data else None


async def get_offer_full(offer_id: str) -> dict | None:
    """Offer + its shift + its nurse — everything an OfferAgent may know."""
    result = await _run(lambda: client().table("offers")
                        .select("*, shifts(*, patients(name, area), agencies(name)), nurses(*)")
                        .eq("id", offer_id).limit(1).execute())
    return result.data[0] if result.data else None


async def offers_for_shift(shift_id: str, states: list[str] | None = None) -> list[dict]:
    def _q():
        q = (client().table("offers").select("*, nurses(name, phone, preferences)")
             .eq("shift_id", shift_id).order("score", desc=True))
        if states:
            q = q.in_("state", states)
        return q.execute()
    return (await _run(_q)).data


async def pending_offer_for_phone(phone: str) -> dict | None:
    """Newest awaiting-reply offer for this phone (SMS/WhatsApp YES-NO routing)."""
    clean = phone.removeprefix("whatsapp:")
    result = await _run(lambda: client().table("offers")
                        .select("*, nurses!inner(name, phone), shifts(*, agencies(name))")
                        .eq("nurses.phone", clean).eq("state", "messaged")
                        .order("last_touch_at", desc=True).limit(1).execute())
    return result.data[0] if result.data else None


async def recent_sms_events(phone: str, limit: int = 8) -> list[dict]:
    """Newest-first sms_in/sms_out events for one phone (conversation memory)."""
    clean = phone.removeprefix("whatsapp:")
    result = await _run(lambda: client().table("events")
                        .select("kind, payload, at")
                        .in_("kind", ["sms_in", "sms_out"])
                        .eq("payload->>phone", clean)
                        .order("at", desc=True).limit(limit).execute())
    return result.data


async def record_webhook_receipt(provider: str, external_id: str) -> bool:
    """First-seen insert. False if this (provider, external_id) already landed."""
    if not external_id:
        return True  # nothing to de-dupe; caller still processes the body
    try:
        result = await _run(lambda: client().table("webhook_receipts")
                            .insert({"provider": provider,
                                     "external_id": external_id}).execute())
        return bool(result.data)
    except Exception as exc:  # unique violation → replay; other errors stay loud
        message = str(exc).lower()
        if "duplicate" in message or "unique" in message or "23505" in message:
            return False
        raise


async def inbound_sms_count(phone: str, *, minutes: int = 10) -> int:
    """How many sms_in events this phone produced in the last `minutes`."""
    clean = phone.removeprefix("whatsapp:")
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    result = await _run(lambda: client().table("events")
                        .select("id")
                        .eq("kind", "sms_in")
                        .eq("payload->>phone", clean)
                        .gte("at", cutoff.isoformat()).execute())
    return len(result.data or [])


async def overlapping_nurse_ids(starts_at: str, ends_at: str) -> set[str]:
    """Nurses already booked during this window (excluded before scoring).

    Only statuses that actually occupy the slot count as busy; cancelled and
    completed shifts must not keep a nurse off a new offer.
    """
    result = await _run(lambda: client().table("shifts").select("nurse_id")
                        .not_.is_("nurse_id", "null")
                        .in_("status", ["scheduled", "filled", "offers_out", "callout"])
                        .lt("starts_at", ends_at).gt("ends_at", starts_at).execute())
    return {row["nurse_id"] for row in result.data}


async def continuity_counts(patient_id: str) -> dict[str, int]:
    """Times each nurse has already held a shift for this patient (continuity of care)."""
    cutoff = datetime.now(UTC).isoformat()
    result = await _run(lambda: client().table("shifts").select("nurse_id")
                        .eq("patient_id", patient_id)
                        .not_.is_("nurse_id", "null")
                        .in_("status", ["scheduled", "filled", "completed"])
                        .lt("starts_at", cutoff).execute())
    counts: dict[str, int] = {}
    for row in result.data:
        counts[row["nurse_id"]] = counts.get(row["nurse_id"], 0) + 1
    return counts


async def nurse_week_hours(week_start: str, week_end: str) -> dict[str, float]:
    """Hours each nurse is already booked inside [week_start, week_end) — overtime guard."""
    result = await _run(lambda: client().table("shifts")
                        .select("nurse_id, starts_at, ends_at")
                        .not_.is_("nurse_id", "null")
                        .in_("status", ["scheduled", "filled", "offers_out", "callout"])
                        .lt("starts_at", week_end).gt("ends_at", week_start).execute())
    window_start = datetime.fromisoformat(week_start)
    window_end = datetime.fromisoformat(week_end)
    hours: dict[str, float] = {}
    for row in result.data:
        clipped_start = max(datetime.fromisoformat(row["starts_at"]), window_start)
        clipped_end = min(datetime.fromisoformat(row["ends_at"]), window_end)
        overlap = max(0.0, (clipped_end - clipped_start).total_seconds() / 3600)
        hours[row["nurse_id"]] = hours.get(row["nurse_id"], 0.0) + overlap
    return hours


# ---- writes (all guarded) ----

async def learn_nurse_preference(nurse_id: str, note: str,
                                 avoid_dows: list[int] | None = None) -> None:
    """Persist a learned preference on the nurse row (caregiver memory).

    The SQL function appends to a capped `memory` list and unions `avoid_dows`
    (Python weekday numbers, Mon=0..Sun=6) in one UPDATE so concurrent
    writers cannot lose a note. Audited as a memory_learned event.
    """
    from shared.untrusted import sanitize_note
    note = sanitize_note(note)
    params = {"p_nurse": nurse_id, "p_note": note}
    if avoid_dows is not None:
        params["p_avoid_dows"] = avoid_dows
    await _run(lambda: client().rpc("learn_nurse_preference", params).execute())
    await log_event("workplane", "memory_learned", nurse_id=nurse_id,
                    payload={"reason": note, "avoid_dows": avoid_dows or []})


async def record_override_outcome(nurse_id: str, accepted: bool) -> None:
    """Track answers to last-resort override asks (memory that updates itself).

    An accepted ask resets the counter — the preference stays soft. Two
    declined asks promote avoid_dows into hard_avoid_dows, and scoring then
    never offers those days again, not even as a fallback.
    """
    result = await _run(lambda: client().rpc(
        "record_override_outcome",
        {"p_nurse": nurse_id, "p_accepted": accepted}).execute())
    prefs = result.data if isinstance(result.data, dict) else {}
    await log_event("workplane", "override_outcome", nurse_id=nurse_id,
                    outcome="accepted" if accepted else "declined",
                    payload={"declines": prefs.get("override_declines", 0),
                             "hard_avoid_dows": prefs.get("hard_avoid_dows", [])})


async def record_callout(shift_id: str, nurse_id: str, reason: str) -> bool:
    """scheduled -> callout: opens the seat and wakes the worker immediately."""
    result = await _run(lambda: client().table("shifts").update({
        "status": "callout", "nurse_id": None, "callout_nurse_id": nurse_id,
        "callout_reason": reason, "callout_at": "now()", "next_action_at": "now()",
    }).eq("id", shift_id).eq("status", "scheduled").execute())
    return bool(result.data)


async def claim_shifts(worker: str, limit: int = 5) -> list[dict]:
    result = await _run(lambda: client().rpc(
        "claim_shifts", {"p_worker": worker, "p_limit": limit}).execute())
    return result.data or []


async def insert_offers(rows: list[dict]) -> None:
    """Idempotent: UNIQUE(shift_id, nurse_id) makes rescoring a no-op."""
    await _run(lambda: client().table("offers")
               .upsert(rows, on_conflict="shift_id,nurse_id",
                       ignore_duplicates=True).execute())


async def bump_offer_rung(offer_id: str, rung: int, channel: str) -> bool:
    """The tick-before-sending guard: False means this rung already touched it."""
    result = await _run(lambda: client().table("offers").update({
        "rung": rung, "last_channel": channel, "last_touch_at": "now()",
        "state": "messaged",
    }).eq("id", offer_id).lt("rung", rung)
      .in_("state", ["scored", "messaged"]).execute())
    return bool(result.data)


async def touch_offer(offer_id: str) -> bool:
    """Heartbeat last_touch_at so a live call never looks stale."""
    result = await _run(lambda: client().table("offers").update({
        "last_touch_at": "now()",
    }).eq("id", offer_id).eq("state", "calling").execute())
    return bool(result.data)


async def set_offer_call_room(offer_id: str, room: str) -> None:
    await _run(lambda: client().table("offers").update({"call_room": room})
               .eq("id", offer_id).execute())


async def record_send_failure(offer_id: str, error: str) -> int:
    result = await _run(lambda: client().rpc(
        "record_send_failure",
        {"p_offer": offer_id, "p_error": error[:200]}).execute())
    return int(result.data or 0)


async def clear_send_error(offer_id: str) -> None:
    await _run(lambda: client().table("offers").update({"last_send_error": None})
               .eq("id", offer_id).execute())


async def bump_dial_attempts(offer_id: str) -> int:
    result = await _run(lambda: client().rpc(
        "bump_dial_attempts", {"p_offer": offer_id}).execute())
    return int(result.data or 0)


async def set_offer_state(offer_id: str, to_state: str, from_states: list[str]) -> bool:
    # Stamp last_touch_at on every transition so a scored->calling jump (a
    # voice-only prospect never messaged) leaves a non-null timestamp for the
    # voice rung's staleness check — a NULL there used to crash the worker.
    result = await _run(lambda: client().table("offers").update({
        "state": to_state, "responded_at": "now()", "last_touch_at": "now()",
    }).eq("id", offer_id).in_("state", from_states).execute())
    return bool(result.data)


async def lock_shift(shift_id: str, nurse_id: str) -> bool:
    """First YES wins; double-booking is rejected by the exclusion constraint."""
    result = await _run(lambda: client().rpc(
        "lock_shift", {"p_shift": shift_id, "p_nurse": nurse_id}).execute())
    return bool(result.data)


async def wake_shift(shift_id: str) -> bool:
    """Pull a parked callout/offers_out shift back onto the worker poll."""
    result = await _run(lambda: client().table("shifts").update({
        "next_action_at": "now()",
    }).eq("id", shift_id).in_("status", ["callout", "offers_out"]).execute())
    return bool(result.data)


async def increment_rescore_rounds(shift_id: str) -> int:
    n = await _run(lambda: client().rpc(
        "increment_rescore_rounds", {"p_shift": shift_id}).execute())
    return int(n.data or 0)


async def mark_escalated(shift_id: str, *, state: str,
                         next_action_at: str | None = None,
                         pages: int | None = None) -> bool:
    """callout/offers_out/escalated → escalated with a paging checkpoint."""
    fields: dict[str, Any] = {
        "status": "escalated", "escalation_state": state,
        "next_action_at": next_action_at, "claimed_by": None, "claimed_at": None,
    }
    if pages is not None:
        fields["escalation_pages"] = pages
    result = await _run(lambda: client().table("shifts").update(fields)
                        .eq("id", shift_id)
                        .in_("status", ["callout", "offers_out", "escalated"]).execute())
    return bool(result.data)


async def ack_escalation(code: str) -> str | None:
    """Guarded paged → acked by ACK code (first 6 chars of the shift id)."""
    result = await _run(lambda: client().rpc(
        "ack_escalation", {"p_code": (code or "").strip().lower()[:6]}).execute())
    data = result.data
    if isinstance(data, list):
        return data[0] if data else None
    return data or None


async def release_shift(shift_id: str, *, status: str, rung: int | None = None,
                        next_action_at: str | None = None) -> None:
    """End a work burst: set the checkpoint, drop the claim, walk away.

    Guarded on the in-flight statuses so a YES that locked the shift mid-burst
    ('filled') is never overwritten by our release.
    """
    fields: dict[str, Any] = {"status": status, "claimed_by": None, "claimed_at": None,
                              "next_action_at": next_action_at}
    if rung is not None:
        fields["rung"] = rung
    await _run(lambda: client().table("shifts").update(fields)
               .eq("id", shift_id).in_("status", ["callout", "offers_out"]).execute())


# ---- EMR outbox (data/emr.sql; drained by workers/outbox_worker.py) ----
# The rule everywhere below: the state change and its outbox row are one
# transaction (the *_with_outbox RPCs), payloads carry ids only, and every
# complete/fail is a guarded UPDATE on claimed_by so a stale ex-claimer
# can never finish a row another drainer rescued.

async def record_callout_with_outbox(shift_id: str, nurse_id: str, reason: str) -> bool:
    """record_callout + the EHR write-back intent, one transaction."""
    result = await _run(lambda: client().rpc("record_callout_with_outbox", {
        "p_shift": shift_id, "p_nurse": nurse_id, "p_reason": reason}).execute())
    return bool(result.data)


async def lock_shift_with_outbox(shift_id: str, nurse_id: str) -> bool:
    """lock_shift + the EHR write-back intent, one transaction. Guard unchanged."""
    result = await _run(lambda: client().rpc("lock_shift_with_outbox", {
        "p_shift": shift_id, "p_nurse": nurse_id}).execute())
    return bool(result.data)


async def enqueue_emr(agency_id: str, kind: str, shift_id: str | None,
                      nurse_id: str | None, patient_id: str | None, key: str) -> None:
    """Queue one EHR write. A duplicate key means already queued — same success."""
    await _run(lambda: client().rpc("enqueue_emr", {
        "p_agency": agency_id, "p_kind": kind, "p_shift": shift_id,
        "p_nurse": nurse_id, "p_patient": patient_id, "p_key": key}).execute())


async def claim_outbox(worker: str, limit: int = 10,
                       agency_id: str | None = None) -> list[dict]:
    """Due, unheld outbox rows (SKIP LOCKED). agency_id narrows for eval isolation."""
    params: dict[str, Any] = {"p_worker": worker, "p_limit": limit}
    if agency_id:
        params["p_agency"] = agency_id
    result = await _run(lambda: client().rpc("claim_outbox", params).execute())
    return result.data or []


async def complete_outbox(row_id: int, worker: str, attempts: int) -> bool:
    result = await _run(lambda: client().table("outbox").update({
        "done_at": "now()", "attempts": attempts, "last_error": None,
    }).eq("id", row_id).eq("claimed_by", worker).is_("done_at", "null").execute())
    return bool(result.data)


async def fail_outbox(row_id: int, worker: str, attempts: int, error: str,
                      next_attempt_at: str | None, dead: bool = False) -> bool:
    """Park the row for retry (next_attempt_at) or give up for good (dead)."""
    if not config.LOG_MESSAGE_CONTENT:
        error = redact.scrub_text(error)
    fields: dict[str, Any] = {"attempts": attempts, "last_error": error[:200],
                              "claimed_by": None, "claimed_at": None}
    if dead:
        fields["dead_at"] = "now()"
    else:
        fields["next_attempt_at"] = next_attempt_at
    result = await _run(lambda: client().table("outbox").update(fields)
                        .eq("id", row_id).eq("claimed_by", worker)
                        .is_("done_at", "null").execute())
    return bool(result.data)


async def upsert_emr_link(agency_id: str, rock_kind: str, rock_id: str,
                          external_type: str, external_id: str, backend: str) -> None:
    """Remember Rock id <-> external id; replays refresh, never duplicate (PK)."""
    await _run(lambda: client().table("emr_links").upsert({
        "agency_id": agency_id, "rock_kind": rock_kind, "rock_id": rock_id,
        "external_type": external_type, "external_id": external_id,
        "backend": backend, "updated_at": "now()",
    }, on_conflict="agency_id,rock_kind,rock_id,external_type").execute())


async def emr_links_for(agency_id: str, rock_ids: list[str]) -> list[dict]:
    if not rock_ids:
        return []
    result = await _run(lambda: client().table("emr_links").select("*")
                        .eq("agency_id", agency_id).in_("rock_id", rock_ids).execute())
    return result.data or []


async def emr_links_of_types(agency_id: str, types: tuple[str, ...]) -> list[dict]:
    result = await _run(lambda: client().table("emr_links").select("*")
                        .eq("agency_id", agency_id)
                        .in_("external_type", list(types)).execute())
    return result.data or []


async def agency_by_id(agency_id: str) -> dict | None:
    result = await _run(lambda: client().table("agencies").select("*")
                        .eq("id", agency_id).limit(1).execute())
    return result.data[0] if result.data else None


async def emr_link_by_external(agency_id: str, external_type: str,
                               external_id: str) -> dict | None:
    result = await _run(lambda: client().table("emr_links").select("*")
                        .eq("agency_id", agency_id)
                        .eq("external_type", external_type)
                        .eq("external_id", str(external_id))
                        .limit(1).execute())
    return result.data[0] if result.data else None


def _fake_555(external_id: str) -> str:
    digits = "".join(c for c in str(external_id) if c.isdigit()) or "0000"
    return f"555-{digits[-4:]:0>4}"


async def upsert_nurse_from_emr(agency_id: str, change: dict, *,
                                create: bool = False,
                                import_phone: bool = False) -> str | None:
    """EHR wins name/active/specialties. Phone and preferences stay Rock's."""
    rtype = change.get("external_type") or "Practitioner"
    link = await emr_link_by_external(agency_id, rtype, change["external_id"])
    if not link:
        if not create:
            return None
        phone = (change.get("phone") if import_phone and change.get("phone")
                 else _fake_555(change["external_id"]))
        agency = await agency_by_id(agency_id)
        inserted = await _run(lambda: client().table("nurses").insert({
            "agency_id": agency_id,
            "name": change.get("name") or "Imported Nurse",
            "phone": phone,
            "specialties": change.get("specialties") or [],
            "active": bool(change.get("active", True)),
            "source": "emr",
        }).execute())
        rock_id = inserted.data[0]["id"]
        await upsert_emr_link(agency_id, "nurse", rock_id, rtype,
                              str(change["external_id"]),
                              (agency or {}).get("emr_backend") or "fhir")
        return rock_id
    fields: dict[str, Any] = {}
    if change.get("name"):
        fields["name"] = change["name"]
    if "active" in change:
        fields["active"] = bool(change["active"])
    if change.get("specialties") is not None:
        fields["specialties"] = change["specialties"]
    if fields:
        await _run(lambda: client().table("nurses").update(fields)
                   .eq("id", link["rock_id"]).eq("agency_id", agency_id).execute())
    return link["rock_id"]


async def upsert_patient_from_emr(agency_id: str, change: dict, *,
                                  create: bool = False,
                                  import_phone: bool = False) -> str | None:
    """EHR wins name/language. Phone stays Rock's. Patients have no active flag."""
    rtype = change.get("external_type") or "Patient"
    link = await emr_link_by_external(agency_id, rtype, change["external_id"])
    if not link:
        if not create:
            return None
        agency = await agency_by_id(agency_id)
        inserted = await _run(lambda: client().table("patients").insert({
            "agency_id": agency_id,
            "name": change.get("name") or "Imported Patient",
            "area": "Unknown",
            "language": change.get("language") or "en",
            "phone": (change.get("phone") if import_phone and change.get("phone")
                      else ""),
            "source": "emr",
        }).execute())
        rock_id = inserted.data[0]["id"]
        await upsert_emr_link(agency_id, "patient", rock_id, rtype,
                              str(change["external_id"]),
                              (agency or {}).get("emr_backend") or "fhir")
        return rock_id
    fields: dict[str, Any] = {}
    if change.get("name"):
        fields["name"] = change["name"]
    if change.get("language"):
        fields["language"] = change["language"]
    if fields:
        await _run(lambda: client().table("patients").update(fields)
                   .eq("id", link["rock_id"]).eq("agency_id", agency_id).execute())
    return link["rock_id"]


async def mark_agency_synced(agency_id: str) -> None:
    await _run(lambda: client().table("agencies")
               .update({"emr_last_sync_at": "now()"}).eq("id", agency_id).execute())


async def agencies_due_for_pull() -> list[dict]:
    """agencies.emr_sync_mode='pull' whose interval has elapsed (or never synced)."""
    result = await _run(lambda: client().table("agencies").select("*")
                        .eq("emr_sync_mode", "pull").execute())
    now = datetime.now(UTC)
    due: list[dict] = []
    for row in result.data or []:
        last = row.get("emr_last_sync_at")
        wait = int(row.get("emr_sync_interval_seconds") or 300)
        if not last:
            due.append(row)
            continue
        stamp = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if now - stamp >= timedelta(seconds=wait):
            due.append(row)
    return due


async def nurse_by_id(nurse_id: str) -> dict | None:
    result = await _run(lambda: client().table("nurses").select("*")
                        .eq("id", nurse_id).limit(1).execute())
    return result.data[0] if result.data else None


async def patient_by_id(patient_id: str) -> dict | None:
    result = await _run(lambda: client().table("patients").select("*")
                        .eq("id", patient_id).limit(1).execute())
    return result.data[0] if result.data else None


# Free-text payload keys that may carry PHI (message bodies, callout reasons,
# prospect names). Redacted when LOG_MESSAGE_CONTENT is off — see _safe_payload.
_FREE_TEXT_KEYS = ("text", "reason", "prospects")


def _safe_payload(payload: dict) -> dict:
    """PHI-free copy of an event payload (only when content logging is off).

    Note: masking 'phone' means recent_sms_events (which keys off the bare
    number) won't find prior turns in prod mode — an accepted trade-off, since
    the message bodies are scrubbed too.
    """
    safe = dict(payload)
    for key in _FREE_TEXT_KEYS:
        if isinstance(safe.get(key), str):
            safe[key] = redact.scrub_text(safe[key])
    if isinstance(safe.get("phone"), str):
        safe["phone"] = redact.mask_phone(safe["phone"])
    return safe


async def log_event(actor: str, kind: str, *, agency_id: str | None = None,
                    shift_id: str | None = None, nurse_id: str | None = None,
                    channel: str | None = None, rung: int | None = None,
                    outcome: str | None = None, payload: dict | None = None) -> None:
    payload = payload or {}
    if not config.LOG_MESSAGE_CONTENT and payload:
        payload = _safe_payload(payload)
    await _run(lambda: client().table("events").insert({
        "actor": actor, "kind": kind, "agency_id": agency_id, "shift_id": shift_id,
        "nurse_id": nurse_id, "channel": channel, "rung": rung, "outcome": outcome,
        "payload": payload,
    }).execute())
