"""PHI cascade engine — Phase 3 stub, intentionally not implemented.

Will be a fully self-hosted cascade for PHI-sensitive conversations: Gemma 4
served locally via Ollama for the LLM plus local STT/TTS, so patient
identifying audio and text never leave the machine. Selected with
ENGINE_PROFILE=gemma_phi once Phase 3 lands; until then it fails loudly.
"""

from livekit.agents import AgentSession


def build_session() -> AgentSession:
    """Unavailable until Phase 3 ships the self-hosted PHI engine."""
    raise NotImplementedError(
        "The gemma_phi engine arrives in Phase 3 (self-hosted Gemma 4 via "
        "Ollama with local STT/TTS). Set ENGINE_PROFILE=cascade or realtime."
    )
