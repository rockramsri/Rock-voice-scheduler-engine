"""B9 — call out Thursday when Tuesday is also scheduled; Tuesday stays put."""

from datetime import UTC, datetime, timedelta

import pytest

from evals import seed
from workplane.tools.scheduling_tools import match_shift_ref


def _hours_until(weekday: int, hour: int = 14) -> float:
    now = datetime.now(UTC)
    days = (weekday - now.weekday()) % 7
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=days)
    if target <= now:
        target += timedelta(days=7)
    return (target - now).total_seconds() / 3600


@pytest.fixture
async def world(eval_db):
    run = seed.seed_run(
        roster=[{"slug": "CG-A", "name": "Ana Reyes"}],
        shifts=[
            {"slug": "SH-TUE", "nurse": "CG-A", "starts_in_hours": _hours_until(1)},
            {"slug": "SH-THU", "nurse": "CG-A", "starts_in_hours": _hours_until(3)},
        ],
    )
    try:
        yield run
    finally:
        seed.cleanup(run)


def test_match_shift_ref_by_weekday():
    tue = {"id": "aaa", "starts_at": "2026-09-08T14:00:00+00:00",
           "ends_at": "2026-09-08T22:00:00+00:00",
           "specialty": "wound care", "area": "Jersey City"}
    thu = {"id": "bbb", "starts_at": "2026-09-10T14:00:00+00:00",
           "ends_at": "2026-09-10T22:00:00+00:00",
           "specialty": "wound care", "area": "Jersey City"}
    assert match_shift_ref([tue, thu], "Thursday")["id"] == "bbb"
    assert match_shift_ref([tue, thu], "tuesday")["id"] == "aaa"
    assert match_shift_ref([tue, thu], "the Thursday one")["id"] == "bbb"
    assert match_shift_ref([tue, thu], "wound care") is None  # ambiguous


async def test_thursday_callout_leaves_tuesday_scheduled(world):
    from data import db
    from workplane.tools.scheduling_tools import build_scheduling_tools

    upcoming = await db.upcoming_shifts_for(world.uuid("CG-A"), limit=3)
    assert {s["id"] for s in upcoming} == {world.uuid("SH-TUE"), world.uuid("SH-THU")}
    thu = next(s for s in upcoming if s["id"] == world.uuid("SH-THU"))
    day = datetime.fromisoformat(thu["starts_at"]).strftime("%A")

    nurse = seed.client().table("nurses").select("*").eq(
        "id", world.uuid("CG-A")).single().execute().data
    tools = build_scheduling_tools([nurse])
    report = next(t for t in tools if getattr(t, "__name__", "") == "report_my_callout"
                  or "report_my_callout" in repr(t))
    fn = getattr(report, "fn", None) or getattr(report, "__wrapped__", None) or report
    spoken = await fn(shift_ref=day, reason="sick")
    assert "Callout recorded" in spoken

    tuesday = await db.get_shift(world.uuid("SH-TUE"))
    thursday = await db.get_shift(world.uuid("SH-THU"))
    assert tuesday["status"] == "scheduled" and tuesday["nurse_id"] == world.uuid("CG-A")
    assert thursday["status"] == "callout" and thursday["nurse_id"] is None
