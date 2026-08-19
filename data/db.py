"""Supabase data access — the only module that talks to Postgres.

supabase-py is sync, so every call runs in a thread to keep the event loop
free. Two discipline rules enforced here: state transitions are ALWAYS
guarded (WHERE carries the expected previous state, so races lose cleanly),
and rungs are bumped BEFORE sending anything (no duplicate outreach).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
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


async def next_shift_for(nurse_id: str) -> dict | None:
    result = await _run(lambda: client().table("shifts")
                        .select("*, patients(name, area)")
                        .eq("nurse_id", nurse_id).eq("status", "scheduled")
                        .order("starts_at").limit(1).execute())
    return result.data[0] if result.data else None


async def get_shift(shift_id: str) -> dict | None:
    result = await _run(lambda: client().table("shifts").select("*")
                        .eq("id", shift_id).limit(1).execute())
    return result.data[0] if result.data else None


async def get_offer_full(offer_id: str) -> dict | None:
    """Offer + its shift + its nurse — everything an OfferAgent may know."""
    result = await _run(lambda: client().table("offers")
                        .select("*, shifts(*, patients(name, area)), nurses(*)")
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
                        .select("*, nurses!inner(name, phone), shifts(*)")
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

    Appends to a capped `memory` list and unions `avoid_dows` (Python weekday
    numbers, Mon=0..Sun=6) inside the preferences jsonb; scoring skips those
    days at rank time. Audited as a memory_learned event.
    """
    rows = (await _run(lambda: client().table("nurses").select("preferences")
                       .eq("id", nurse_id).limit(1).execute())).data
    prefs = (rows[0].get("preferences") if rows else None) or {}
    memory = prefs.get("memory", [])
    memory.append({"note": note, "at": datetime.now(UTC).isoformat()})
    prefs["memory"] = memory[-20:]
    if avoid_dows:
        prefs["avoid_dows"] = sorted({*prefs.get("avoid_dows", []), *avoid_dows})
    await _run(lambda: client().table("nurses").update({"preferences": prefs})
               .eq("id", nurse_id).execute())
    await log_event("workplane", "memory_learned", nurse_id=nurse_id,
                    payload={"reason": note, "avoid_dows": avoid_dows or []})


async def record_override_outcome(nurse_id: str, accepted: bool) -> None:
    """Track answers to last-resort override asks (memory that updates itself).

    An accepted ask resets the counter — the preference stays soft. Two
    declined asks promote avoid_dows into hard_avoid_dows, and scoring then
    never offers those days again, not even as a fallback.
    """
    rows = (await _run(lambda: client().table("nurses").select("preferences")
                       .eq("id", nurse_id).limit(1).execute())).data
    prefs = (rows[0].get("preferences") if rows else None) or {}
    if accepted:
        prefs["override_declines"] = 0
    else:
        prefs["override_declines"] = prefs.get("override_declines", 0) + 1
        if prefs["override_declines"] >= 2 and prefs.get("avoid_dows"):
            prefs["hard_avoid_dows"] = sorted({*prefs.get("hard_avoid_dows", []),
                                               *prefs["avoid_dows"]})
    await _run(lambda: client().table("nurses").update({"preferences": prefs})
               .eq("id", nurse_id).execute())
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
