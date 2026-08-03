"""Outbound calls — dispatch the agent into a room, then dial out via SIP.

Agent-first ordering so the callee never answers into an empty room. Phase 3
moves call placement behind pgmq workers and adds retry/answer tracking; the
function shape stays the same.
"""

from __future__ import annotations

import logging
import uuid

from livekit import api

from shared import config

log = logging.getLogger("channels.outbound")


async def place_call(to: str, room_name: str | None = None, metadata: str = "") -> dict:
    """Ring `to` (E.164) and connect an agent; metadata picks which agent.

    Never raises: missing config or any SIP/dispatch error comes back as
    {"ok": False, "error": ...} so the worker's dial_failed branch can run and
    one bad call never crashes the whole outreach burst.
    """
    if not config.SIP_OUTBOUND_TRUNK_ID:
        log.error("LIVEKIT_SIP_OUTBOUND_TRUNK_ID is not set — see `channels.cli status`")
        return {"ok": False, "to": to, "error": "outbound SIP trunk not configured"}
    room = room_name or f"call-out-{uuid.uuid4().hex[:8]}"

    lk = api.LiveKitAPI()
    try:
        # Named workers need an explicit dispatch; auto-dispatch workers
        # join the room on their own as soon as it is created.
        if config.AGENT_NAME:
            await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
                agent_name=config.AGENT_NAME, room=room, metadata=metadata,
            ))
        participant = await lk.sip.create_sip_participant(api.CreateSIPParticipantRequest(
            sip_trunk_id=config.SIP_OUTBOUND_TRUNK_ID,
            sip_call_to=to,
            sip_number=config.TWILIO_PHONE_NUMBER,
            room_name=room,
            participant_identity=f"phone-{to}",
            wait_until_answered=False,
        ))
        log.info("outbound call -> %s room=%s", to, room)
        return {"ok": True, "to": to, "room": room,
                "participant": participant.participant_identity}
    except Exception as exc:  # noqa: BLE001 — any SIP/dispatch failure becomes a result, not a crash
        log.error("outbound call -> %s FAILED: %s", to, exc)
        return {"ok": False, "to": to, "room": room, "error": str(exc)}
    finally:
        await lk.aclose()
