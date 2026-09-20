"""Partner-API placeholders. Interface-ready; not wired.

Selecting `axiscare` or `wellsky` on an agency dead-letters immediately
with a visible `emr_writeback_dead` event instead of hanging the drainer.
"""

from workplane.emr.base import EmrContext, EmrJob, EmrPermanentError, EmrResult


class _Stub:
    def __init__(self, backend: str):
        self.backend = backend

    async def capabilities(self) -> dict:
        return {"writes": False, "sync": "none", "stub": True}

    async def execute(self, job: EmrJob, ctx: EmrContext) -> EmrResult:
        raise EmrPermanentError(f"{self.backend} driver is not wired")

    async def pull_changes(self, since_iso: str | None,
                           ctx: EmrContext) -> list[dict]:
        return []


class AxisCareDriver(_Stub):
    def __init__(self):
        super().__init__("axiscare")


class WellSkyDriver(_Stub):
    def __init__(self):
        super().__init__("wellsky")
