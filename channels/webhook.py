"""Inbound SMS webhook — TextBelt replies (and legacy Twilio) land here.

Run `python -m channels.cli serve` behind an ngrok tunnel and set
PUBLIC_BASE_URL; every outbound TextBelt SMS then carries a replyWebhookUrl
pointing at /textbelt-reply, so YES/NO answers flow back with no number
linking. The Twilio /sms route stays for the day A2P clears. Replies come
from the work plane's sms_agent, capped well inside webhook budgets.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time

from aiohttp import web

from channels import sms
from data import db
from shared import config
from shared.spoken import spoken_when
from workplane.agents.sms_agent import reply_to_sms
from workplane.offers import accept_offer, decline_offer

log = logging.getLogger("channels.webhook")

FALLBACK_REPLY = (
    "Sorry, our assistant is having trouble right now. "
    "Please call the Rockram Home Health Care office."
)


def _twiml(message: str) -> web.Response:
    from twilio.twiml.messaging_response import MessagingResponse

    response = MessagingResponse()
    response.message(message)
    return web.Response(text=str(response), content_type="text/xml")


def _signature_ok(request: web.Request, form: dict[str, str]) -> bool:
    """Validate X-Twilio-Signature. Needs PUBLIC_BASE_URL (the URL Twilio signed)."""
    if not config.PUBLIC_BASE_URL:
        return True  # local dev / curl testing: nothing to validate against
    from twilio.request_validator import RequestValidator

    validator = RequestValidator(config.TWILIO_AUTH_TOKEN)
    signed_url = f"{config.PUBLIC_BASE_URL}/sms"
    return validator.validate(signed_url, form, request.headers.get("X-Twilio-Signature", ""))


async def handle_sms(request: web.Request) -> web.Response:
    form = {key: str(value) for key, value in (await request.post()).items()}
    if not _signature_ok(request, form):
        log.warning("rejected SMS webhook with bad signature")
        return web.Response(status=403, text="forbidden")

    sender, body = form.get("From", ""), form.get("Body", "")
    log.info("SMS <- %s: %s", sender, body)
    # Log the bare number so history (recent_sms_events keys off the stripped
    # number) stays visible for WhatsApp too, where From is "whatsapp:+1...".
    log_phone = sender.removeprefix("whatsapp:")
    await db.log_event("webhook", "sms_in", payload={"phone": log_phone, "text": body})
    reply = await _offer_reply(sender, body)  # YES/NO to a pending offer?
    if reply is None:
        try:
            reply = await asyncio.wait_for(reply_to_sms(sender, body), timeout=12)
        except Exception as exc:  # noqa: BLE001 — always answer Twilio inside its 15s budget
            log.error("sms_agent failed: %s", exc)
            reply = FALLBACK_REPLY
    log.info("SMS -> %s: %s", sender, reply)
    await db.log_event("webhook", "sms_out", payload={"phone": log_phone, "text": reply})
    return _twiml(reply)


def _textbelt_signature_ok(request: web.Request, raw_body: bytes) -> bool:
    """HMAC-SHA256(key, timestamp + raw JSON) must match X-textbelt-signature."""
    if not config.PUBLIC_BASE_URL:
        return True  # local dev / curl testing: nothing to validate against
    timestamp = request.headers.get("X-textbelt-timestamp", "")
    signature = request.headers.get("X-textbelt-signature", "")
    if not timestamp or not signature:
        return False
    try:
        skew = abs(time.time() - float(timestamp))
    except ValueError:
        return False  # non-numeric timestamp header -> reject, don't 500
    if skew > 15 * 60:
        return False  # stale or replayed
    expected = hmac.new(config.TEXTBELT_KEY.encode(),
                        (timestamp + raw_body.decode()).encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


async def handle_textbelt_reply(request: web.Request) -> web.Response:
    """TextBelt reply webhook: JSON {textId, fromNumber, text} — answer by sending back."""
    raw = await request.read()
    if not _textbelt_signature_ok(request, raw):
        log.warning("rejected TextBelt webhook with bad signature")
        return web.Response(status=403, text="forbidden")
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 — malformed body is a 400, not a crash
        return web.Response(status=400, text="bad json")

    sender, body = payload.get("fromNumber", ""), payload.get("text", "")
    log.info("SMS <- %s (textbelt): %s", sender, body)
    log_phone = sender.removeprefix("whatsapp:")  # no-op for SMS; keeps parity
    await db.log_event("webhook", "sms_in", payload={"phone": log_phone, "text": body})
    reply = await _offer_reply(sender, body)  # YES/NO to a pending offer?
    if reply is None:
        try:
            reply = await asyncio.wait_for(reply_to_sms(sender, body), timeout=12)
        except Exception as exc:  # noqa: BLE001 — always answer something
            log.error("sms_agent failed: %s", exc)
            reply = FALLBACK_REPLY
    log.info("SMS -> %s (textbelt): %s", sender, reply)
    await db.log_event("webhook", "sms_out", payload={"phone": log_phone, "text": reply})
    # Unlike TwiML, the webhook response body is not delivered — send explicitly.
    await sms.send_textbelt(sender, reply)
    return web.json_response({"ok": True})


async def _offer_reply(sender: str, body: str) -> str | None:
    """Strict YES/NO handling for pending shift offers; None = not an offer reply."""
    answer = body.strip().lower().rstrip(".!")
    if answer not in {"yes", "y", "no", "n"}:
        return None
    offer = await db.pending_offer_for_phone(sender)
    if offer is None:
        return None
    first = offer["nurses"]["name"].split()[0]
    if answer in {"no", "n"}:
        await decline_offer(offer)
        return f"No problem, {first} — thanks for letting us know. Rockram Home Health Care"
    when = spoken_when(offer["shifts"]["starts_at"], offer["shifts"]["ends_at"])
    if await accept_offer(offer):
        return (f"Confirmed, {first}! The {when} shift in {offer['shifts']['area']} "
                "is yours. Details to follow. Rockram Home Health Care")
    return (f"So sorry, {first} — that shift was just filled. "
            "We'll reach out next time. Rockram Home Health Care")


async def handle_health(_: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "rock-sms-webhook"})


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/sms", handle_sms)
    app.router.add_post("/textbelt-reply", handle_textbelt_reply)
    app.router.add_get("/health", handle_health)
    return app


def serve() -> None:
    """Blocking: run the webhook server on SMS_WEBHOOK_PORT."""
    log.info("SMS webhook on http://localhost:%d (/textbelt-reply, /sms, /health)",
             config.SMS_WEBHOOK_PORT)
    if not config.PUBLIC_BASE_URL:
        log.warning("PUBLIC_BASE_URL empty — signature validation OFF and "
                    "TextBelt replies cannot reach us; start `ngrok http %d` "
                    "and set PUBLIC_BASE_URL to go live",
                    config.SMS_WEBHOOK_PORT)
    web.run_app(build_app(), port=config.SMS_WEBHOOK_PORT)
