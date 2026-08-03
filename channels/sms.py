"""Outbound messaging — TextBelt SMS and Twilio WhatsApp.

Senders share one shape: every function returns an ok/error dict and never
raises, because messaging must not take down a live call. SMS goes through
TextBelt exclusively (Twilio US SMS is A2P-blocked: it returns 201 then the
carrier drops the message). Replies ride TextBelt's replyWebhookUrl back to
our webhook. WhatsApp still rides Twilio's Messages API with a `whatsapp:`
prefix. Phase 3 puts pgmq workers in front of all of these.
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from shared import config

log = logging.getLogger("channels.sms")

TEXTBELT_URL = "https://textbelt.com/text"


async def _twilio_send(to: str, from_: str, body: str) -> dict:
    """Shared Twilio Messages call (sync SDK, so it runs in a thread).

    Missing config returns a normal error result — never SystemExit, which as a
    BaseException would escape the dispatch worker's `except Exception` and kill
    outreach for every shift over one misconfigured channel.
    """
    if not (config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN and from_):
        log.error("Twilio credentials or sender missing — see .env.example")
        return {"ok": False, "to": to, "error": "Twilio credentials or sender missing"}

    def _send() -> str:
        from twilio.rest import Client

        client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
        return client.messages.create(to=to, from_=from_, body=body).sid

    try:
        sid = await asyncio.to_thread(_send)
    except Exception as exc:  # noqa: BLE001 — any send failure becomes a result, not a crash
        log.error("%s -> %s FAILED: %s", from_, to, exc)
        return {"ok": False, "to": to, "error": str(exc)}
    log.info("%s -> %s sid=%s", from_, to, sid)
    return {"ok": True, "to": to, "sid": sid}


async def send_sms(to: str, body: str) -> dict:
    """Send one SMS via TextBelt (needs a paid key for US delivery + replies)."""
    return await send_textbelt(to, body)


async def send_whatsapp(to: str, body: str) -> dict:
    """Send a WhatsApp message; recipient must have joined the sandbox first."""
    if not to.startswith("whatsapp:"):
        to = f"whatsapp:{to}"
    return await _twilio_send(to, config.TWILIO_WHATSAPP_FROM, body)


async def send_textbelt(to: str, body: str) -> dict:
    """Send an instant SMS via TextBelt (free key = 1/day; paid key = capped only by credit).

    When PUBLIC_BASE_URL is set, each send carries replyWebhookUrl so the
    nurse's YES/NO comes back to our webhook (paid keys only).
    """
    payload = {"phone": to, "message": body, "key": config.TEXTBELT_KEY}
    if config.PUBLIC_BASE_URL:
        payload["replyWebhookUrl"] = f"{config.PUBLIC_BASE_URL}/textbelt-reply"
    try:
        async with aiohttp.ClientSession() as session, session.post(
            TEXTBELT_URL, data=payload, timeout=aiohttp.ClientTimeout(total=15)
        ) as response:
            result = await response.json()
    except Exception as exc:  # noqa: BLE001 — any send failure becomes a result, not a crash
        log.error("textbelt -> %s FAILED: %s", to, exc)
        return {"ok": False, "to": to, "error": str(exc)}

    ok = bool(result.get("success"))
    detail = {"ok": ok, "to": to, "quota_remaining": result.get("quotaRemaining")}
    if ok:
        detail["text_id"] = result.get("textId")
        log.info("textbelt -> %s id=%s quota_left=%s", to, result.get("textId"),
                 result.get("quotaRemaining"))
    else:
        detail["error"] = result.get("error", "unknown textbelt error")
        log.error("textbelt -> %s FAILED: %s", to, detail["error"])
    return detail
