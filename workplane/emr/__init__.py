"""EMR seam — the work plane's only door to a system of record.

This package replaced the old workplane/emr.py mock; `from workplane import
emr` keeps working. The hot-path callers moved into single-transaction RPCs
(db.record_callout_with_outbox, db.lock_shift_with_outbox); post_chart_event
stays for every other caller with its legacy signature, but now ENQUEUES an
outbox row instead of writing anything itself. The outbox drainer
(workers/outbox_worker.py) does the actual writing, retrying, and auditing.
"""

from __future__ import annotations

from datetime import UTC, datetime

from data import db
from workplane.emr.base import (  # noqa: F401 — re-exported for drivers/tests
    EMR_KINDS, EmrClient, EmrContext, EmrJob, EmrPermanentError, EmrResult,
    EmrTransientError,
)


async def post_chart_event(action: str, shift: dict, *, nurse_id: str | None = None,
                           details: dict | None = None) -> str:
    """Legacy entry point: queue one chart update; returns the idempotency key.

    `details` is accepted for signature compatibility but never queued —
    outbox payloads carry ids only (the drainer re-reads live rows).
    """
    if action not in EMR_KINDS:
        raise ValueError(f"unknown EMR action: {action!r}")
    row = shift if shift.get("agency_id") else (await db.get_shift(shift["id"]) or shift)
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    key = f"{action}:{row['id']}:{stamp}"
    await db.enqueue_emr(row["agency_id"], action, row["id"], nurse_id,
                         row.get("patient_id"), key)
    return key
