"""Partner stubs dead-letter instead of hanging."""

import pytest

from workplane.emr.base import EmrJob, EmrPermanentError
from workplane.emr.registry import build_client


async def test_axiscare_and_wellsky_are_wired_stubs():
    for name in ("axiscare", "wellsky"):
        client = build_client({"emr_backend": name})
        assert client.backend == name
        with pytest.raises(EmrPermanentError, match="not wired"):
            await client.execute(
                EmrJob(kind="escalated", agency_id="x"), None)  # type: ignore[arg-type]
