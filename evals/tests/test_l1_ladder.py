"""L1 — quiet-hours window + ladder plan selection (pure functions, no DB)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from workers import ladder

AGENCY = {"timezone": "America/New_York", "quiet_start": 22, "quiet_end": 6,
          "urgent_lead_hours": 5, "relaxed_lead_hours": 24}

NY = ZoneInfo("America/New_York")


def ny(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 19, hour, minute, tzinfo=NY)   # a Wednesday


def test_calls_allowed_during_the_day():
    for hour in (6, 9, 12, 18, 21):
        assert ladder.in_call_window(ny(hour), AGENCY), f"{hour}:00 should allow calls"
    assert ladder.in_call_window(ny(21, 59), AGENCY)


def test_calls_blocked_in_quiet_hours():
    for hour in (22, 23, 0, 3, 5):
        assert not ladder.in_call_window(ny(hour), AGENCY), f"{hour}:00 should be quiet"
    assert not ladder.in_call_window(ny(5, 59), AGENCY)


def test_quiet_check_converts_to_agency_timezone():
    # 02:00 UTC == 22:00 New York (Aug, UTC-4): quiet, even though 02 != NY hour.
    utc_2am = datetime(2026, 8, 20, 2, 0, tzinfo=ZoneInfo("UTC"))
    assert not ladder.in_call_window(utc_2am, AGENCY)


def test_next_call_window_is_now_when_open():
    now = ny(10)
    assert ladder.next_call_window(now, AGENCY) == now


def test_next_call_window_same_day_before_dawn():
    got = ladder.next_call_window(ny(3), AGENCY)
    assert (got.hour, got.minute, got.day) == (6, 0, 19)


def test_next_call_window_next_day_after_quiet_start():
    got = ladder.next_call_window(ny(23), AGENCY)
    assert (got.hour, got.minute, got.day) == (6, 0, 20)


def test_pick_plan_boundaries():
    assert ladder.pick_plan(4.0, AGENCY) is ladder.URGENT
    assert ladder.pick_plan(5.0, AGENCY) is ladder.URGENT      # <= urgent
    assert ladder.pick_plan(5.1, AGENCY) is ladder.NORMAL
    assert ladder.pick_plan(23.9, AGENCY) is ladder.NORMAL
    assert ladder.pick_plan(24.0, AGENCY) is ladder.RELAXED    # >= relaxed
    assert ladder.pick_plan(72.0, AGENCY) is ladder.RELAXED


def test_plans_end_in_voice_and_waits_are_positive():
    for plan in (ladder.RELAXED, ladder.NORMAL, ladder.URGENT):
        assert plan[-1].channels == ("voice",)
        assert all(rung.wait_minutes > 0 for rung in plan)
        assert [rung.number for rung in plan] == list(range(1, len(plan) + 1))
