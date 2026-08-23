"""L1 — scoring.rank: hard filters, guards, fallbacks, ordering (pure, no DB)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from workers import scoring

NY = ZoneInfo("America/New_York")
AGENCY = {"timezone": "America/New_York"}

# Wednesday 2026-08-19, 08:00-16:00 New York (weekday() == 2).
STARTS = datetime(2026, 8, 19, 8, 0, tzinfo=NY)
SHIFT = {"specialty": "wound care", "area": "Jersey City",
         "starts_at": STARTS.isoformat(),
         "ends_at": (STARTS + timedelta(hours=8)).isoformat()}

ALL_WEEK = [{"dow": d, "start": "07:00", "end": "20:00"} for d in range(7)]


def nurse(id_: str, **over) -> dict:
    row = dict(id=id_, name=f"Nurse {id_}", phone=f"555-0{id_[-3:]}",
               specialties=["wound care"], areas=["Jersey City"], pay_level=2,
               license_ok=True, reliability=0.7, max_hours_week=40,
               availability=list(ALL_WEEK), active=True, preferences={})
    row.update(over)
    return row


def rank(nurses, exclude=frozenset(), **kw):
    return scoring.rank(SHIFT, nurses, set(exclude), AGENCY, **kw)


def ids(prospects):
    return [p.nurse_id for p in prospects]


def test_hard_filters_drop_ineligible():
    nurses = [nurse("n1"),
              nurse("n2", specialties=["pediatric"]),      # wrong specialty
              nurse("n3", license_ok=False),
              nurse("n4", active=False),
              nurse("n5")]
    prospects, notes, fallbacks = rank(nurses, exclude={"n5"})
    assert ids(prospects) == ["n1"]
    assert fallbacks == [] and notes == []   # hard filters are silent


def test_hard_avoid_dow_never_ranks_and_is_noted():
    nurses = [nurse("n1", preferences={"hard_avoid_dows": [2]}),   # Wed = 2
              nurse("n2")]
    prospects, notes, fallbacks = rank(nurses)
    assert ids(prospects) == ["n2"] and fallbacks == []
    assert any("hard preference" in note for note in notes)


def test_soft_avoid_dow_becomes_fallback_not_prospect():
    nurses = [nurse("n1", preferences={"avoid_dows": [2]}), nurse("n2")]
    prospects, notes, fallbacks = rank(nurses)
    assert ids(prospects) == ["n2"]
    assert ids(fallbacks) == ["n1"]
    assert any("held back" in note for note in notes)


def test_overtime_cap_skips_with_note():
    nurses = [nurse("n1"), nurse("n2")]
    prospects, notes, _ = rank(nurses, week_hours={"n1": 36.0})   # 36 + 8 > 40
    assert ids(prospects) == ["n2"]
    assert any("cap" in note for note in notes)


def test_continuity_bonus_outranks_identical_stranger():
    nurses = [nurse("stranger"), nurse("familiar")]
    prospects, _, _ = rank(nurses, continuity={"familiar": 3})
    assert ids(prospects) == ["familiar", "stranger"]
    assert "cared for this patient 3 times" in prospects[0].reason


def test_area_match_beats_nearby():
    nurses = [nurse("far", areas=["Newark"]), nurse("near")]
    prospects, _, _ = rank(nurses)
    assert ids(prospects) == ["near", "far"]
    assert "near Jersey City" in prospects[1].reason


def test_availability_window_beats_no_window():
    nurses = [nurse("free"), nurse("busy", availability=[])]
    prospects, _, _ = rank(nurses)
    assert ids(prospects) == ["free", "busy"]


def test_cheaper_pay_level_wins_ties():
    nurses = [nurse("pricey", pay_level=3), nurse("cheap", pay_level=1)]
    prospects, _, _ = rank(nurses)
    assert ids(prospects) == ["cheap", "pricey"]


def test_top_k_and_fallback_caps():
    clean = [nurse(f"c{i}", reliability=0.5 + i * 0.05) for i in range(6)]
    soft = [nurse(f"s{i}", preferences={"avoid_dows": [2]}) for i in range(3)]
    prospects, _, fallbacks = rank(clean + soft)
    assert len(prospects) == 4          # top_k default
    assert len(fallbacks) == 2          # last-resort tier is capped at 2
    assert ids(prospects) == ["c5", "c4", "c3", "c2"]   # reliability descending


def test_rank_is_deterministic():
    nurses = [nurse("n1"), nurse("n2", pay_level=1), nurse("n3", areas=["Newark"])]
    first = rank(nurses)
    second = rank(nurses)
    assert ids(first[0]) == ids(second[0])
    assert [p.score for p in first[0]] == [p.score for p in second[0]]
