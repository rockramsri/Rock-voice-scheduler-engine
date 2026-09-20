"""Auth adapters for the FHIR driver. Headers only — no SDK.

HAPI uses `none`. Bearer is a static token from agencies.emr_secret_ref.
client_credentials and oauth2_password land with Medplum / OpenEMR.
"""

from __future__ import annotations

from workplane.emr.base import EmrPermanentError


class NoAuth:
    async def headers(self, secret: str | None) -> dict:
        return {}


class BearerAuth:
    async def headers(self, secret: str | None) -> dict:
        if not secret:
            raise EmrPermanentError("emr_secret_ref is empty for bearer auth")
        return {"Authorization": f"Bearer {secret}"}


def make_auth(kind: str | None):
    kind = (kind or "none").strip()
    if kind == "none":
        return NoAuth()
    if kind == "bearer":
        return BearerAuth()
    raise EmrPermanentError(f"unsupported emr_auth_kind: {kind!r}")
