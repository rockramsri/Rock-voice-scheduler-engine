"""Prospect scoring — hard filters, then a weighted sum, all deterministic.

The worker uses this (fast, explainable, no LLM cost per callout). The
voice find_nurse tool keeps its Pydantic AI ranking for conversational
answers; both read the same nurses table. Weights are module constants
until real outcome data earns them a home in the agencies table.

Three guards ride along with the base weights and every skip is returned
as a spoken-friendly note (audited + shown in the console):
- learned preferences: hard_avoid_dows never rank; avoid_dows (soft) are
  held back as last-resort fallbacks the voice rung may ask ONCE, gently
- the overtime cap (nurses.max_hours_week vs hours already booked that week)
- continuity of care (prior shifts with THIS patient add a score bonus)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

W_SPECIALTY, W_AREA, W_AVAILABILITY, W_RELIABILITY, W_COST = 0.30, 0.25, 0.20, 0.15, 0.10
W_CONTINUITY = 0.20  # additive bonus: familiar faces outrank strangers on ties

DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class Prospect:
    nurse_id: str
    name: str
    phone: str
    score: float
    reason: str


def rank(shift: dict, nurses: list[dict], exclude_ids: set[str], agency: dict,
         top_k: int = 4, *, continuity: dict[str, int] | None = None,
         week_hours: dict[str, float] | None = None,
         ) -> tuple[list[Prospect], list[str], list[Prospect]]:
    """Best-first prospects, notes for every guarded skip, and last-resort
    fallbacks (soft memory skips — the voice rung may ask them once, gently)."""
    continuity = continuity or {}
    week_hours = week_hours or {}
    starts_local = (datetime.fromisoformat(shift["starts_at"])
                    .astimezone(ZoneInfo(agency["timezone"])))
    dow = starts_local.weekday()
    shift_hours = ((datetime.fromisoformat(shift["ends_at"])
                    - datetime.fromisoformat(shift["starts_at"])).total_seconds() / 3600)

    prospects: list[Prospect] = []
    fallbacks: list[Prospect] = []
    notes: list[str] = []
    for nurse in nurses:
        if (nurse["id"] in exclude_ids or not nurse["active"]
                or not nurse["license_ok"]
                or shift["specialty"] not in nurse["specialties"]):
            continue
        prefs = nurse.get("preferences") or {}
        if dow in set(prefs.get("hard_avoid_dows") or []):
            notes.append(f"{nurse['name']} skipped — hard preference: "
                         f"never {DAY_NAMES[dow]}s")
            continue
        booked = week_hours.get(nurse["id"], 0.0)
        cap = nurse.get("max_hours_week") or 40
        if booked + shift_hours > cap:
            notes.append(f"{nurse['name']} skipped — {booked:.0f}h booked this week; "
                         f"+{shift_hours:.0f}h would exceed the {cap}h cap")
            continue
        area = 1.0 if shift["area"] in nurse["areas"] else 0.4
        avail = _availability_fit(shift, nurse["availability"], agency["timezone"])
        cost = (3 - nurse["pay_level"]) / 2  # pay levels 1..3 -> 1.0 .. 0.0
        times = continuity.get(nurse["id"], 0)
        score = (W_SPECIALTY * 1.0 + W_AREA * area + W_AVAILABILITY * avail
                 + W_RELIABILITY * nurse["reliability"] + W_COST * max(0.0, cost)
                 + W_CONTINUITY * min(times, 5) / 5)
        where = shift["area"] if area == 1.0 else f"near {shift['area']}"
        reason = f"{shift['specialty']} specialist based {where}"
        if times:
            reason += f", cared for this patient {times} time{'s' if times > 1 else ''} before"
        prospect = Prospect(nurse_id=nurse["id"], name=nurse["name"], phone=nurse["phone"],
                            score=round(score, 3), reason=reason)
        if dow in set(prefs.get("avoid_dows") or []):
            notes.append(f"{nurse['name']} held back — learned preference: "
                         f"no {DAY_NAMES[dow]}s (last resort only)")
            fallbacks.append(prospect)
        else:
            prospects.append(prospect)
    prospects.sort(key=lambda p: p.score, reverse=True)
    fallbacks.sort(key=lambda p: p.score, reverse=True)
    return prospects[:top_k], notes, fallbacks[:2]


def _availability_fit(shift: dict, availability: list[dict], tz: str) -> float:
    """1.0 if a weekly window covers the shift, else 0.3 (maybe reachable)."""
    starts = datetime.fromisoformat(shift["starts_at"]).astimezone(ZoneInfo(tz))
    ends = datetime.fromisoformat(shift["ends_at"]).astimezone(ZoneInfo(tz))
    for window in availability:
        if (window["dow"] == starts.weekday()
                and window["start"] <= starts.strftime("%H:%M")
                and window["end"] >= ends.strftime("%H:%M")):
            return 1.0
    return 0.3
