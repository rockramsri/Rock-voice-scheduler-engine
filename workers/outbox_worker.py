"""Outbox drainer — ships queued EHR write-backs; retries; dead-letters.

Run: python -m workers.outbox_worker

Same design DNA as dispatch_worker: claim due rows with SKIP LOCKED, do a
short burst of work, write the checkpoint ON THE ROW (done_at /
next_attempt_at / dead_at), release, repeat. Waits are timestamps, never
sleeping state, so any drainer resumes any job after any crash — a claim
older than 5 minutes is fair game for takeover (data/emr.sql).

Evals never run this loop: they call drain_outbox_once(agency_id) so
write-backs land deterministically before the snapshot.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from data import db
from shared import config
from workplane.emr.base import EmrJob, EmrContext, EmrPermanentError, EmrTransientError
from workplane.emr.registry import build_client

log = logging.getLogger("worker.outbox")

# Retry waits by failure number (1-based). OUTBOX_MAX_ATTEMPTS caps the count.
BACKOFF_SECONDS = [30, 60, 300, 900, 3600, 3600, 3600, 3600]

# Which Rock row an external id belongs to, per job kind (for emr_links).
_LINK_ANCHOR = {
    "seed_agency": ("agency", "agency_id"),
    "upsert_practitioner": ("nurse", "nurse_id"),
    "upsert_patient": ("patient", "patient_id"),
}
_DEFAULT_ANCHOR = ("shift", "shift_id")


def backoff_seconds(attempt: int) -> int | None:
    """Wait before the retry after failure number `attempt`; None = dead-letter."""
    if attempt >= config.OUTBOX_MAX_ATTEMPTS:
        return None
    return BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS)) - 1]


async def _context_for(row: dict) -> EmrContext | None:
    """Fresh rows at execute time — the outbox carries ids, never data."""
    agency = await db.agency_by_id(row["agency_id"])
    if agency is None:
        return None
    shift = await db.get_shift(row["shift_id"]) if row.get("shift_id") else None
    nurse = await db.nurse_by_id(row["nurse_id"]) if row.get("nurse_id") else None
    patient = await db.patient_by_id(row["patient_id"]) if row.get("patient_id") else None
    rock_ids = [rid for rid in (row["agency_id"], row.get("shift_id"),
                                row.get("nurse_id"), row.get("patient_id")) if rid]
    links = {(link["rock_kind"], link["rock_id"], link["external_type"]): link["external_id"]
             for link in await db.emr_links_for(row["agency_id"], rock_ids)}
    return EmrContext(agency=agency, shift=shift, nurse=nurse, patient=patient,
                      links=links, secret=config.env_secret(agency.get("emr_secret_ref")))


async def _dead(row: dict, worker: str, attempts: int, error: str) -> None:
    await db.fail_outbox(row["id"], worker, attempts, error, None, dead=True)
    await db.log_event("emr", "emr_writeback_dead", agency_id=row["agency_id"],
                       shift_id=row.get("shift_id"), nurse_id=row.get("nurse_id"),
                       outcome=error[:80], payload={"kind": row["kind"], "attempt": attempts})
    log.warning("outbox %s DEAD after %d attempt(s): %s", row["id"], attempts, error[:80])


async def _process(row: dict, worker: str) -> None:
    """One row, one try. Success completes; failures park or dead-letter."""
    attempts = int(row.get("attempts") or 0) + 1
    kind = row["kind"]
    try:
        ctx = await _context_for(row)
        if ctx is None:
            raise EmrPermanentError("agency row missing")
        client = build_client(ctx.agency)
        job = EmrJob(kind=kind, agency_id=row["agency_id"], shift_id=row.get("shift_id"),
                     nurse_id=row.get("nurse_id"), patient_id=row.get("patient_id"),
                     idempotency_key=row["idempotency_key"], attempt=attempts)
        result = await client.execute(job, ctx)
        if not result.ok:
            error = EmrTransientError(result.detail or "driver returned ok=False")
            error.retry_after = result.retry_after_seconds  # type: ignore[attr-defined]
            raise error
    except EmrPermanentError as exc:
        await _dead(row, worker, attempts, f"permanent: {exc}")
        return
    except Exception as exc:  # EmrTransientError and anything unexpected: retry
        wait = getattr(exc, "retry_after", None) or backoff_seconds(attempts)
        if wait is None:
            await _dead(row, worker, attempts, str(exc))
            return
        next_at = (datetime.now(UTC) + timedelta(seconds=wait)).isoformat()
        await db.fail_outbox(row["id"], worker, attempts, str(exc), next_at)
        await db.log_event("emr", "emr_writeback_failed", agency_id=row["agency_id"],
                           shift_id=row.get("shift_id"), nurse_id=row.get("nurse_id"),
                           outcome=str(exc)[:80],
                           payload={"kind": kind, "attempt": attempts, "retry_in": wait})
        log.info("outbox %s attempt %d failed (%s); retry in %ds",
                 row["id"], attempts, str(exc)[:60], wait)
        return

    # Success: remember external ids, complete the row, audit for the console.
    anchor_kind, anchor_field = _LINK_ANCHOR.get(kind, _DEFAULT_ANCHOR)
    anchor_id = row.get(anchor_field) or row["agency_id"]
    for external_type, external_id in (result.external_ids or {}).items():
        await db.upsert_emr_link(row["agency_id"], anchor_kind, anchor_id,
                                 external_type, str(external_id), client.backend)
    await db.complete_outbox(row["id"], worker, attempts)
    # `action` stays for the oracle and console (the mock wrote it since day 1);
    # record_id/system keep the feed's old shape when a driver provides them.
    payload: dict = {"action": kind, "kind": kind, "backend": client.backend,
                     "attempt": attempts, "external_ids": result.external_ids}
    if "record_id" in (result.external_ids or {}):
        payload["record_id"] = result.external_ids["record_id"]
        payload["system"] = result.detail or client.backend
    await db.log_event("emr", "emr_writeback", agency_id=row["agency_id"],
                       shift_id=row.get("shift_id"), nurse_id=row.get("nurse_id"),
                       payload=payload)
    log.info("outbox %s done: %s via %s (attempt %d)", row["id"], kind,
             client.backend, attempts)


async def drain_outbox_once(agency_id: str | None = None, worker: str | None = None,
                            limit: int = 10) -> int:
    """Claim-and-process until nothing is due. Returns rows processed.

    The eval runners call this (with their run's agency_id) right before the
    snapshot, so write-backs land deterministically with no background task.
    """
    worker = worker or f"obx-{uuid.uuid4().hex[:6]}"
    processed = 0
    while True:
        rows = await db.claim_outbox(worker, limit, agency_id)
        if not rows:
            return processed
        for row in rows:
            try:
                await _process(row, worker)
            except Exception:  # one bad row must not stop the batch
                log.exception("outbox row %s burst failed", row.get("id"))
            processed += 1


async def run() -> None:
    worker_id = f"obx-{uuid.uuid4().hex[:6]}"
    log.info("%s draining outbox (poll %.0fs, max %d attempts)",
             worker_id, config.OUTBOX_POLL_SECONDS, config.OUTBOX_MAX_ATTEMPTS)
    while True:
        try:
            n = await drain_outbox_once(worker=worker_id)
        except Exception:  # a transient claim error must not kill the loop
            log.exception("outbox poll failed; backing off 5s")
            await asyncio.sleep(5)
            continue
        if n == 0:
            await asyncio.sleep(config.OUTBOX_POLL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)-18s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run())
