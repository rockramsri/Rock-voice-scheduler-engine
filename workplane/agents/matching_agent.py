"""Pydantic AI matching agent — ranks nurses for a conversational request.

The find_nurse facade tool delegates here for spoken, explainable answers.
Nurses now come from the database; the list still travels in the prompt
because an agency roster is small. The dispatch worker uses the
deterministic scorer in workers/scoring.py instead — same table, no LLM.
"""

from pydantic import BaseModel
from pydantic_ai import Agent

from data import db
from shared.config import WORKPLANE_MODEL


class NurseMatch(BaseModel):
    name: str
    reason: str  # one short spoken-friendly clause, e.g. "wound care, based in Jersey City"
    score: float  # 0..1, higher is better


matching_agent = Agent(
    WORKPLANE_MODEL,
    output_type=list[NurseMatch],
    instructions=(
        "You rank nurses from a home-care roster for a requested specialty "
        "and area. Rules: exclude nurses whose license is not ok; prefer "
        "exact specialty matches, then closer areas (same town beats "
        "neighboring towns, which beat far ones); use pay level as a "
        "tiebreaker (lower is cheaper, slightly preferred). Return AT MOST "
        "3 matches, best first. Each reason must be one short clause that "
        "sounds natural when spoken aloud, mentioning specialty and area."
    ),
)


async def rank_nurses(specialty: str, area: str) -> list[NurseMatch]:
    """Run the matching agent over the live roster; best match first."""
    nurses = await db.fetch_active_nurses()
    roster = "\n".join(
        f"- {n['name']} | specialty: {', '.join(n['specialties'])} | "
        f"area: {', '.join(n['areas'])} | "
        f"licensed: {'yes' if n['license_ok'] else 'NO'} | pay level: {n['pay_level']}"
        for n in nurses
    )
    prompt = (
        f"Requested specialty: {specialty}\n"
        f"Requested area: {area}\n\n"
        f"Roster:\n{roster}"
    )
    result = await matching_agent.run(prompt)
    return result.output
