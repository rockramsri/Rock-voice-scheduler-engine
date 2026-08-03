"""Engine selection — ENGINE_PROFILE decides which adapter builds the session.

The only module that knows engine names. Agents and tools never import
engines, which is exactly what makes swapping engines a config change
instead of a code change. Phase 3 extends this to per-agent profiles
(e.g. the PHI intake agent always gets gemma_phi).
"""

from collections.abc import Callable

from livekit.agents import AgentSession

from shared.config import ENGINE_PROFILE
from voice.engines import cascade_default, gemma_phi, realtime_openai

_ENGINES: dict[str, Callable[[], AgentSession]] = {
    "cascade": cascade_default.build_session,
    "realtime": realtime_openai.build_session,
    "gemma_phi": gemma_phi.build_session,  # Phase 3 stub — raises for now
}


def build_session() -> AgentSession:
    """Build the AgentSession for the configured ENGINE_PROFILE."""
    builder = _ENGINES.get(ENGINE_PROFILE)
    if builder is None:
        valid = ", ".join(sorted(_ENGINES))
        raise ValueError(
            f"Unknown ENGINE_PROFILE={ENGINE_PROFILE!r}. Valid options: {valid}"
        )
    return builder()
