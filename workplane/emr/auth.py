"""Auth adapters for the FHIR driver. Headers only — no SDK.

HAPI uses `none`. Bearer is a static token from agencies.emr_secret_ref.
Medplum uses client_credentials (token cached until 60s before expiry).
"""

from __future__ import annotations

import time
from urllib.parse import urlencode

import aiohttp

from shared import config
from workplane.emr.base import EmrPermanentError, EmrTransientError

_TIMEOUT = aiohttp.ClientTimeout(total=15)

OPENEMR_SCOPES = (
    "openid offline_access api:oemr api:fhir "
    "user/Patient.cruds user/Practitioner.cruds user/Organization.cruds "
    "user/Patient.read user/Patient.write user/Practitioner.read "
    "user/Practitioner.write user/Organization.read user/Organization.write "
    "user/patient.read user/patient.write user/patient.crus user/patient.cruds "
    "user/patient.s user/appointment.read user/appointment.write "
    "user/appointment.cruds user/facility.read user/facility.write "
    "user/facility.crus user/practitioner.read user/practitioner.write "
    "user/practitioner.crus"
)


class NoAuth:
    async def headers(self, secret: str | None) -> dict:
        return {}


class BearerAuth:
    async def headers(self, secret: str | None) -> dict:
        if not secret:
            raise EmrPermanentError("emr_secret_ref is empty for bearer auth")
        return {"Authorization": f"Bearer {secret}"}


class ClientCredentialsAuth:
    """OAuth2 client_credentials. One token, refreshed 60s before it dies."""

    def __init__(self, token_url: str, client_id: str):
        self.token_url = token_url
        self.client_id = client_id
        self._token: str | None = None
        self._expires_at = 0.0

    async def headers(self, secret: str | None) -> dict:
        if not secret:
            raise EmrPermanentError("emr_secret_ref is empty for client_credentials")
        if not self._token or time.time() > self._expires_at - 60:
            await self._refresh(secret)
        return {"Authorization": f"Bearer {self._token}"}

    async def _refresh(self, secret: str) -> None:
        body = urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": secret,
        }).encode()
        try:
            async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
                async with session.post(
                    self.token_url, data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                ) as resp:
                    data = await resp.json(content_type=None)
                    status = resp.status
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise EmrTransientError(f"token endpoint: {exc}") from exc
        if status >= 400 or not data.get("access_token"):
            raise EmrPermanentError(f"client_credentials token {status}")
        self._token = data["access_token"]
        self._expires_at = time.time() + int(data.get("expires_in") or 3600)


class PasswordAuth:
    """OAuth2 password grant (OpenEMR lab). Client secret is emr_secret_ref."""

    def __init__(self, token_url: str, client_id: str, *, verify_tls: bool = True):
        self.token_url = token_url
        self.client_id = client_id
        self.verify_tls = verify_tls
        self._token: str | None = None
        self._expires_at = 0.0

    async def headers(self, secret: str | None) -> dict:
        if not secret:
            raise EmrPermanentError("emr_secret_ref is empty for oauth2_password")
        if not self._token or time.time() > self._expires_at - 60:
            await self._refresh(secret)
        return {"Authorization": f"Bearer {self._token}"}

    async def _refresh(self, secret: str) -> None:
        user = config.OPENEMR_USERNAME
        password = config.OPENEMR_PASSWORD
        if not user or not password:
            raise EmrPermanentError("OPENEMR_USERNAME / OPENEMR_PASSWORD empty")
        body = urlencode({
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": secret,
            "username": user,
            "password": password,
            "scope": OPENEMR_SCOPES,
            "user_role": "users",
        }).encode()
        ssl = False if not self.verify_tls else None
        try:
            async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
                async with session.post(
                    self.token_url, data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    ssl=ssl,
                ) as resp:
                    data = await resp.json(content_type=None)
                    status = resp.status
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise EmrTransientError(f"token endpoint: {exc}") from exc
        if status >= 400 or not data.get("access_token"):
            raise EmrPermanentError(f"password token {status}")
        self._token = data["access_token"]
        self._expires_at = time.time() + int(data.get("expires_in") or 3600)


_CC_CACHE: dict[tuple[str, str], ClientCredentialsAuth] = {}
_PW_CACHE: dict[tuple[str, str], PasswordAuth] = {}


def make_auth(kind: str | None, *, client_id: str | None = None,
              token_url: str | None = None, verify_tls: bool = True):
    kind = (kind or "none").strip()
    if kind == "none":
        return NoAuth()
    if kind == "bearer":
        return BearerAuth()
    if kind == "client_credentials":
        if not client_id or not token_url:
            raise EmrPermanentError("client_credentials needs emr_client_id")
        key = (token_url, client_id)
        cached = _CC_CACHE.get(key)
        if cached is None:
            cached = _CC_CACHE[key] = ClientCredentialsAuth(token_url, client_id)
        return cached
    if kind == "oauth2_password":
        if not client_id or not token_url:
            raise EmrPermanentError("oauth2_password needs emr_client_id")
        key = (token_url, client_id)
        cached = _PW_CACHE.get(key)
        if cached is None:
            cached = _PW_CACHE[key] = PasswordAuth(
                token_url, client_id, verify_tls=verify_tls)
        return cached
    raise EmrPermanentError(f"unsupported emr_auth_kind: {kind!r}")
