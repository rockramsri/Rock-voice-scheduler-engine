"""Default cascade engine — Deepgram STT -> OpenAI LLM -> Cartesia TTS.

Each stage uses the vendor plugin when its API key is set, and otherwise
routes the SAME model through LiveKit Inference, so one LiveKit key is
enough to run this whole pipeline. Phase 3 adds gemma_phi as the
PHI-safe, fully self-hosted sibling of this cascade.
"""

import inspect

from livekit.agents import AgentSession, TurnHandlingOptions, inference, llm, stt, tts
from livekit.plugins import cartesia, deepgram, openai, silero

from shared import config


def _stt() -> stt.STT:
    if config.DEEPGRAM_API_KEY:
        return deepgram.STT(model="nova-3")
    return inference.STT(model="deepgram/nova-3", language="multi")


def _llm() -> llm.LLM:
    if config.OPENAI_API_KEY:
        return openai.LLM(model=config.LLM_MODEL)
    return inference.LLM(model=f"openai/{config.LLM_MODEL}")


def _tts() -> tts.TTS:
    if config.CARTESIA_API_KEY:
        return cartesia.TTS(model="sonic-3", voice=config.CARTESIA_VOICE)
    return inference.TTS(model=f"cartesia/sonic-3:{config.CARTESIA_VOICE}")


def build_session() -> AgentSession:
    """Cascade session: separate best-of-breed models per pipeline stage."""
    extras = {}
    # Expressive mode (LLM-steered emotion/pacing) needs a newer SDK and the
    # inference TTS route; the flag turns itself on once the SDK supports it.
    if "expressive" in inspect.signature(AgentSession.__init__).parameters:
        extras["expressive"] = True
    return AgentSession(
        stt=_stt(),
        llm=_llm(),
        tts=_tts(),
        vad=silero.VAD.load(),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
        ),
        **extras,
    )
