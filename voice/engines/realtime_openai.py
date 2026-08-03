"""OpenAI Realtime engine — one speech-to-speech model does it all.

Lowest latency and most natural prosody, at higher cost. The realtime model
handles its own VAD and turn detection, so no Silero or turn detector is
configured here — adding them would fight the model's built-ins.
"""

from livekit.agents import AgentSession
from livekit.plugins import openai

from shared.config import REALTIME_MODEL, REALTIME_VOICE


def build_session() -> AgentSession:
    """Session where the realtime model owns audio in both directions."""
    return AgentSession(
        llm=openai.realtime.RealtimeModel(
            model=REALTIME_MODEL,
            voice=REALTIME_VOICE,
        ),
    )
