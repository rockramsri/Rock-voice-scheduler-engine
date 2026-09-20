"""Mock EMR driver — today's WellSky-style write-back, through the outbox.

Keeps the demo and every eval working with agencies.emr_backend='mock':
no network, a fake WSK-… record id, and the drainer turns the result into
the same emr_writeback event the console has always streamed.
"""

from __future__ import annotations

import time

from workplane.emr.base import EmrContext, EmrJob, EmrResult

EMR_SYSTEM = "WellSky (mock)"


class MockDriver:
    backend = "mock"

    async def capabilities(self) -> dict:
        return {"resources": {}, "sync": "none", "writes": True}

    async def execute(self, job: EmrJob, ctx: EmrContext) -> EmrResult:
        anchor = job.shift_id or job.nurse_id or job.patient_id or job.agency_id
        record_id = f"WSK-{anchor[:8]}-{int(time.time())}"
        return EmrResult(ok=True, external_ids={"record_id": record_id},
                         detail=EMR_SYSTEM)

    async def pull_changes(self, since_iso: str | None,
                           ctx: EmrContext) -> list[dict]:
        return []
