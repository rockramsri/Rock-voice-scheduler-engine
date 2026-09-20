"""Outbox retry policy — pure: schedule shape and the dead-letter threshold.

No DB, no network. The drainer's classification (transient retries,
permanent dead-letters, crash resume) is exercised for real against the
eval DB in test_emr_contract.py.
"""

from shared import config
from workers.outbox_worker import BACKOFF_SECONDS, backoff_seconds


def test_schedule_is_the_spec():
    assert BACKOFF_SECONDS == [30, 60, 300, 900, 3600, 3600, 3600, 3600]


def test_waits_climb_then_plateau():
    waits = [backoff_seconds(a) for a in range(1, config.OUTBOX_MAX_ATTEMPTS)]
    assert waits == [30, 60, 300, 900, 3600, 3600, 3600]


def test_max_attempts_dead_letters():
    assert backoff_seconds(config.OUTBOX_MAX_ATTEMPTS) is None


def test_beyond_max_stays_dead():
    assert backoff_seconds(config.OUTBOX_MAX_ATTEMPTS + 5) is None


def test_first_retry_is_quick():
    # A blip (one 503) must retry within a minute, not an hour.
    assert backoff_seconds(1) == 30
