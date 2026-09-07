"""S2 — webhook signatures fail closed; textId replays do not double-apply."""

from unittest.mock import AsyncMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from evals import seed


@pytest.mark.parametrize("flag", [False, None])
def test_unsigned_rejected_when_url_missing(flag, monkeypatch):
    from channels import webhook
    from shared import config

    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(config, "WEBHOOK_INSECURE_DEV", bool(flag))
    class _Req:
        headers = {}
    assert webhook._textbelt_signature_ok(_Req(), b"{}") is False
    assert webhook._signature_ok(_Req(), {}) is False


def test_unsigned_allowed_only_when_insecure_flag(monkeypatch):
    from channels import webhook
    from shared import config

    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(config, "WEBHOOK_INSECURE_DEV", True)
    class _Req:
        headers = {}
    assert webhook._textbelt_signature_ok(_Req(), b"{}") is True
    assert webhook._signature_ok(_Req(), {}) is True


async def test_unsigned_post_returns_403(eval_db, monkeypatch):
    from channels.webhook import build_app
    from shared import config

    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(config, "WEBHOOK_INSECURE_DEV", False)
    app = build_app()
    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/textbelt-reply", json={
            "textId": "s2-unsigned",
            "fromNumber": "555-0101",
            "text": "yes",
        })
        assert resp.status == 403


async def test_replayed_textid_does_not_double_log(eval_db, monkeypatch):
    """Same textId → 200 both times, but only one sms_in event."""
    from channels.webhook import build_app
    from data import db
    from shared import config

    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(config, "WEBHOOK_INSECURE_DEV", True)
    run = seed.seed_run(roster=[{"slug": "CG-A"}])
    phone = f"555-{run.agency_id[0:4]}"
    seed.client().table("nurses").update({"phone": phone}).eq(
        "id", run.uuid("CG-A")).execute()
    text_id = f"s2-replay-{run.agency_id}"
    body_text = f"what time is the shift {run.agency_id[:8]}?"
    try:
        with patch("channels.sms.send_textbelt", new_callable=AsyncMock,
                   return_value={"ok": True}):
            app = build_app()
            async with TestClient(TestServer(app)) as client:
                body = {"textId": text_id, "fromNumber": phone, "text": body_text}
                first = await client.post("/textbelt-reply", json=body)
                second = await client.post("/textbelt-reply", json=body)
                assert first.status == 200
                assert second.status == 200
        inbound = seed.client().table("events").select("kind, payload")
        inbound = inbound.eq("kind", "sms_in").eq("payload->>phone", phone).execute().data
        assert len(inbound) == 1
        assert inbound[0]["payload"]["text"] == body_text
        assert await db.record_webhook_receipt("textbelt", text_id) is False
    finally:
        seed.client().table("webhook_receipts").delete().eq(
            "provider", "textbelt").eq("external_id", text_id).execute()
        seed.cleanup(run)
