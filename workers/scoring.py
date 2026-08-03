"""Prospect scoring — hard filters, then a weighted sum, all deterministic.

The worker uses this (fast, explainable, no LLM cost per callout). The
voice find_nurse tool keeps its Pydantic AI ranking for conversational
answers; both read the same nurses table. Weights are module constants
until real outcome data earns them a home in the agencies table.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

W_SPECIALTY, W_AREA, W_AVAILABILITY, W_RELIABILITY, W_COST = 0.30, 0.25, 0.20, 0.15, 0.10


@dataclass(frozen=True)
class Prospect:
    nurse_id: str
    name: str
    phone: str
    score: float
    reason: str


def rank(shift: dict, nurses: list[dict], exclude_ids: set[str],
         agency: dict, top_k: int = 4) -> list[Prospect]:
    """Best-first prospects for one open shift."""
    prospects = []
    for nurse in nurses:
        if (nurse["id"] in exclude_ids or not nurse["active"]
                or not nurse["license_ok"]
                or shift["specialty"] not in nurse["specialties"]):
            continue
        area = 1.0 if shift["area"] in nurse["areas"] else 0.4
        avail = _availability_fit(shift, nurse["availability"], agency["timezone"])
        cost = (3 - nurse["pay_level"]) / 2  # pay levels 1..3 -> 1.0 .. 0.0
        score = (W_SPECIALTY * 1.0 + W_AREA * area + W_AVAILABILITY * avail
                 + W_RELIABILITY * nurse["reliability"] + W_COST * max(0.0, cost))
        where = shift["area"] if area == 1.0 else f"near {shift['area']}"
        prospects.append(Prospect(
            nurse_id=nurse["id"], name=nurse["name"], phone=nurse["phone"],
            score=round(score, 3),
            reason=f"{shift['specialty']} specialist based {where}",
        ))
    prospects.sort(key=lambda p: p.score, reverse=True)
    return prospects[:top_k]


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
