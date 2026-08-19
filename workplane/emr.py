"""Mock EMR write-back — the system-of-record seam.

post_chart_event shapes a WellSky/HCHB-style visit-record update and lands it
in the audit stream as an `emr_writeback` event, which the ops console shows
live. Swapping this mock for a real vendor client changes only this module;
every caller and the payload contract stay identical.
"""

from __future__ import annotations

import time

from data import db

EMR_SYSTEM = "WellSky (mock)"


async def post_chart_event(action: str, shift: dict, *, nurse_id: str | None = None,
                           details: dict | None = None) -> str:
    """Write one chart update to the (mock) EMR; returns the record id."""
    record_id = f"WSK-{shift['id'][:8]}-{int(time.time())}"
    await db.log_event("emr", "emr_writeback", shift_id=shift.get("id"),
                       nurse_id=nurse_id,
                       payload={"system": EMR_SYSTEM, "record_id": record_id,
                                "action": action, **(details or {})})
    return record_id
