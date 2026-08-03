"""LiveKit worker entrypoint — wires engine, agent, and event logging.

Run `python -m voice.entry console` (terminal mic) or `dev` (hosted
playground). The event subscriptions below are Phase 1's observability AND
the seam where Phase 2 passive listeners (emergency watcher, speculative
executor) attach to the live transcript stream.
"""

import json
import logging

from livekit import rtc
from livekit.agents import (
    AgentServer,
    AgentSession,
    ConversationItemAddedEvent,
    JobContext,
    UserInputTranscribedEvent,
    cli,
)
from livekit.agents.llm import ChatMessage

from data import db
from shared import config
from voice.agents.front_desk import FrontDesk, inbound_greeting
from voice.agents.offer_agent import build_offer_agent
from voice.session_factory import build_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-16s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rock.entry")

server = AgentServer()


def wire_logging(session: AgentSession) -> None:
    """Log committed items and per-turn latency; verbose transcripts are gated.

    Raw per-utterance transcripts are PHI, so they only log when
    DEBUG_TRANSCRIPTS is on; the committed-item and latency lines always run.
    """

    # TODO(Phase 2): passive listeners attach here — the emergency watcher
    # and speculative executor consume this same transcript event stream.
    if config.DEBUG_TRANSCRIPTS:
        @session.on("user_input_transcribed")
        def _on_transcript(ev: UserInputTranscribedEvent) -> None:
            marker = "FINAL  " if ev.is_final else "interim"
            log.info("transcript [%s] %s", marker, ev.transcript)

    @session.on("conversation_item_added")
    def _on_item(ev: ConversationItemAddedEvent) -> None:
        if not isinstance(ev.item, ChatMessage):
            return
        log.info("committed  [%s] %s", ev.item.role, ev.item.text_content)
        _log_turn_latency(ev.item)


def _log_turn_latency(item: ChatMessage) -> None:
    """Per-turn latency line. Cascade fills every field; realtime only e2e."""
    metrics = item.metrics or {}
    wanted = (
        ("transcription_delay", "stt_delay"),
        ("end_of_turn_delay", "eou_delay"),
        ("llm_node_ttft", "llm_ttft"),
        ("tts_node_ttfb", "tts_ttfb"),
        ("e2e_latency", "e2e"),
    )
    parts = [
        f"{label}={metrics[key]:.3f}s"
        for key, label in wanted
        if metrics.get(key) is not None
    ]
    if parts:
        log.info("latency    [%s] %s", item.role, " ".join(parts))


async def _resolve_sip_caller(ctx: JobContext) -> tuple[str | None, list[dict]]:
    """SIP caller phone → roster matches (0 / 1 / many). Non-SIP → (None, [])."""
    participant = await ctx.wait_for_participant()
    if participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
        log.info("participant %r is not SIP — no caller-ID lookup", participant.identity)
        return None, []
    phone = (participant.attributes or {}).get("sip.phoneNumber")
    if not phone:
        log.warning("SIP participant %r has no sip.phoneNumber", participant.identity)
        return None, []
    matches = await db.find_nurses_by_phone(phone)
    names = [m["name"] for m in matches]
    log.info("caller-ID phone=%s matches=%s", phone, names)
    return phone, matches


# agent_name matches the SIP dispatch rule so inbound phone calls land here;
# when AGENT_NAME is empty the worker auto-dispatches into every new room.
# Dispatch metadata decides WHICH agent gets built: the worker dispatches
# outbound offer calls with {"role": "offer", "offer_id": ...}.
@server.rtc_session(agent_name=config.AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    meta = json.loads(ctx.job.metadata) if ctx.job.metadata else {}
    session = build_session()
    wire_logging(session)

    if meta.get("role") == "offer":
        offer = await db.get_offer_full(meta["offer_id"])
        if offer is None:
            log.error("offer %s not found, dropping call", meta.get("offer_id"))
            return
        agent = build_offer_agent(offer)
        first_name = offer["nurses"]["name"].split()[0]
        greeting = (f"Greet {first_name} by name, say you are Rock calling from "
                    "Rockram Home Health Care about an open shift, and present it.")
        log.info("starting OfferAgent for offer %s on %r",
                 meta["offer_id"][:8], config.ENGINE_PROFILE)
    else:
        phone, matches = await _resolve_sip_caller(ctx)
        agent = FrontDesk(caller_phone=phone, matches=matches)
        greeting = inbound_greeting(matches)
        log.info("starting FrontDesk on engine profile %r (phone=%s, n=%d)",
                 config.ENGINE_PROFILE, phone, len(matches))

    # record=False keeps PHI audio/transcripts off LiveKit Cloud by default;
    # enable recording deliberately (with a signed BAA) for production.
    await session.start(agent=agent, room=ctx.room, record=False)
    await session.generate_reply(instructions=greeting)


if __name__ == "__main__":
    print("ROCK Scheduler — FrontDesk voice agent\n" + config.startup_summary())
    cli.run_app(server)

