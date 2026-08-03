"""Central configuration for ROCK Scheduler — the single place reading env vars.

Nothing else in the codebase touches os.environ. Lookup order for a key
(first hit wins): shell environment, this project's .env (which carries
everything the project needs), then two sibling .env files as a fallback
for the OpenAI key only. Phase 3 adds Supabase/Gemma settings here.
"""

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

_ROOT = Path(__file__).parent.parent

# This project's own .env carries everything the project needs.
load_dotenv(_ROOT / ".env")


def _sibling_openai_key() -> str:
    """Borrow ONLY OPENAI_API_KEY from sibling projects — never their full env.

    dotenv_values reads the file into a dict without mutating os.environ, so a
    sibling's TWILIO_*, SUPABASE_*, etc. can never silently leak into ours.
    """
    for _sibling in (
        _ROOT.parent / "Livekit-agents" / ".env",
        _ROOT.parent / "s2s-experiment" / ".env",
    ):
        value = dotenv_values(_sibling).get("OPENAI_API_KEY")
        if value:
            return value
    return ""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

# --- LiveKit: transport (dev/playground) + Inference fallback models ---
LIVEKIT_URL: str = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY: str = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET: str = os.getenv("LIVEKIT_API_SECRET", "")

# --- Engine selection: swapping this is the whole point of Phase 1 ---
ENGINE_PROFILE: str = os.getenv("ENGINE_PROFILE", "cascade")

# --- Realtime engine (OpenAI speech-to-speech) ---
REALTIME_MODEL: str = os.getenv("REALTIME_MODEL", "gpt-realtime")
REALTIME_VOICE: str = os.getenv("REALTIME_VOICE", "marin")

# --- Cascade engine (Deepgram STT -> OpenAI LLM -> Cartesia TTS) ---
LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4.1-mini")
CARTESIA_VOICE: str = os.getenv(
    "CARTESIA_VOICE", "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
)

# --- Provider keys. Deepgram/Cartesia may be empty: the cascade engine ---
# --- then routes those models through LiveKit Inference instead.       ---
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "") or _sibling_openai_key()
DEEPGRAM_API_KEY: str = os.getenv("DEEPGRAM_API_KEY", "")
CARTESIA_API_KEY: str = os.getenv("CARTESIA_API_KEY", "")

# --- Work plane (Pydantic AI backend agents) ---
WORKPLANE_MODEL: str = os.getenv("WORKPLANE_MODEL", "openai:gpt-4.1-mini")

# --- Data plane (Supabase Postgres; the app writes with the service role) ---
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
WORKER_POLL_SECONDS: float = float(os.getenv("WORKER_POLL_SECONDS", "2"))

# --- Observability / PHI posture ---
# Demo default (True) records verbatim SMS bodies + callout reasons in the
# events table so the ops console can show them. Set False in production to
# scrub free text and mask phones at a single choke point (data.db.log_event);
# see shared/redact.py. Flipping this one flag makes events PHI-free.
LOG_MESSAGE_CONTENT: bool = _env_bool("LOG_MESSAGE_CONTENT", True)
# Verbose per-utterance transcript logging in voice/entry.py. Off by default so
# live-call PHI never lands in stdout; committed-item + latency logs stay on.
DEBUG_TRANSCRIPTS: bool = _env_bool("DEBUG_TRANSCRIPTS", False)

# --- Channels (channels/): Twilio <-> LiveKit SIP voice + Twilio SMS ---
# Worker agent name. Must match the SIP dispatch rule's agent for inbound
# calls to reach this worker; empty = auto-dispatch (playground-style).
AGENT_NAME: str = os.getenv("AGENT_NAME", "")
TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
# Some older env files spell this TWILIO_VOICE_NUMBER; accept both.
TWILIO_PHONE_NUMBER: str = (
    os.getenv("TWILIO_PHONE_NUMBER", "") or os.getenv("TWILIO_VOICE_NUMBER", "")
)
SIP_OUTBOUND_TRUNK_ID: str = os.getenv("LIVEKIT_SIP_OUTBOUND_TRUNK_ID", "")
# Only used by `channels.cli provision` when creating a fresh outbound trunk.
TWILIO_TERMINATION_URI: str = os.getenv("TWILIO_TERMINATION_URI", "")
TWILIO_SIP_USERNAME: str = os.getenv("TWILIO_SIP_USERNAME", "")
TWILIO_SIP_PASSWORD: str = os.getenv("TWILIO_SIP_PASSWORD", "")
# Inbound-SMS webhook server; PUBLIC_BASE_URL is the ngrok https URL.
SMS_WEBHOOK_PORT: int = int(os.getenv("SMS_WEBHOOK_PORT", "8787"))
PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
# WhatsApp sender. Default is Twilio's shared sandbox number: recipients
# must first join the sandbox with the code shown in the Twilio console.
TWILIO_WHATSAPP_FROM: str = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
# TextBelt: instant capped SMS with no A2P wait. "textbelt" = 1 free/day;
# a paid key from textbelt.com removes the cap.
TEXTBELT_KEY: str = os.getenv("TEXTBELT_KEY", "textbelt")


def startup_summary() -> str:
    """One honest line per subsystem so you instantly see what will run."""
    def _key(name: str, value: str) -> str:
        return f"{name}=set" if value else f"{name}=MISSING"

    stt = "deepgram plugin" if DEEPGRAM_API_KEY else "livekit inference (deepgram/nova-3)"
    tts = "cartesia plugin" if CARTESIA_API_KEY else "livekit inference (cartesia/sonic-3)"
    return "\n".join([
        f"  engine    : {ENGINE_PROFILE}",
        f"  livekit   : {LIVEKIT_URL or 'MISSING (console still works for realtime)'}",
        f"  cascade   : stt={stt} | llm={LLM_MODEL} | tts={tts}",
        f"  realtime  : {REALTIME_MODEL} voice={REALTIME_VOICE}",
        f"  workplane : {WORKPLANE_MODEL} ({_key('OPENAI_API_KEY', OPENAI_API_KEY)})",
        (
            f"  telephony : agent={AGENT_NAME or '(auto-dispatch)'} | "
            f"number={TWILIO_PHONE_NUMBER or 'MISSING'} | "
            f"out-trunk={SIP_OUTBOUND_TRUNK_ID or 'MISSING'}"
        ),
    ])
