"""Pydantic AI SMS responder — answers inbound texts using the work plane.

The messaging channel's brain. Inbound message text is untrusted: it travels
only in the user turn, never in instructions. Each reply is grounded in a
context block built from what we KNOW about the sender's phone: which nurses
it backs, any pending shift offer, their own next shifts, and the recent SMS
back-and-forth.

The agent is built per text as a closure over the sender's OWN roster rows,
so its one tool can only read a shift for a nurse who shares this phone — a
prompt injection cannot reach another nurse's record.
"""

from pydantic_ai import Agent

from data import db
from shared.config import WORKPLANE_MODEL
from shared.spoken import spoken_when

SMS_INSTRUCTIONS = (
    "You are Rock, answering SMS messages for Rockram Home Health Care, "
    "a home health agency. Reply in plain text: one to three short sentences, under "
    "300 characters, no markdown, no emojis. A trusted CONTEXT block "
    "from our database precedes each message — prefer it over tools, "
    "address the nurse by first name when the context identifies them, "
    "and answer questions about a pending offer from its details. If "
    "several nurses share the phone and it matters, ask which one is "
    "texting. Only look up the texter's own shift; never discuss other "
    "nurses. If the message describes an emergency, tell them to call "
    "911 now. For anything else, ask them to call the office."
)


def _build_sms_agent(allowed: list[dict]) -> Agent:
    """An agent whose only tool is scoped to the nurses on THIS phone."""
    names = {n["name"]: n for n in allowed}
    agent = Agent(WORKPLANE_MODEL, output_type=str, instructions=SMS_INSTRUCTIONS)

    @agent.tool_plain
    async def get_my_next_shift(nurse_name: str = "") -> str:
        """Look up the texter's own next scheduled shift."""
        nurse = (next(iter(names.values())) if len(names) == 1
                 else names.get(nurse_name))
        if nurse is None:
            return ("I can only look up your own shift. Which name on this "
                    "number are you?")
        shift = await db.next_shift_for(nurse["id"])
        if shift is None:
            return f"{nurse['name']}, you have no upcoming shift scheduled."
        return (f"{nurse['name']}, your next shift is "
                f"{spoken_when(shift['starts_at'], shift['ends_at'])} "
                f"in {shift['area']}.")

    return agent


async def reply_to_sms(from_number: str, body: str) -> str:
    """One inbound text in, one context-grounded, phone-scoped reply out."""
    allowed = await db.find_nurses_by_phone(from_number)
    context = await _context_for(from_number, allowed)
    agent = _build_sms_agent(allowed)
    result = await agent.run(f"{context}\n\nNew SMS from {from_number}: {body}")
    return result.output


async def _context_for(phone: str, nurses: list[dict]) -> str:
    """Everything we know about this phone, as trusted prompt context."""
    lines: list[str] = []
    if nurses:
        lines.append("This phone belongs to roster nurse(s): "
                     + ", ".join(n["name"] for n in nurses) + ".")
    offer = await db.pending_offer_for_phone(phone)
    if offer:
        s = offer["shifts"]
        pay = f", ${s['pay_rate']}/hr" if s.get("pay_rate") else ""
        lines.append(
            f"PENDING OFFER for {offer['nurses']['name']}: a {s['specialty']} "
            f"shift {spoken_when(s['starts_at'], s['ends_at'])} in {s['area']}"
            f"{pay}. They can reply YES to take it or NO to pass.")
    for nurse in nurses[:3]:
        shift = await db.next_shift_for(nurse["id"])
        if shift:
            lines.append(f"{nurse['name']}'s own next shift: "
                         f"{spoken_when(shift['starts_at'], shift['ends_at'])} "
                         f"in {shift['area']}.")
    history = await db.recent_sms_events(phone)
    if history:
        convo = " | ".join(
            f"{'them' if e['kind'] == 'sms_in' else 'us'}: {(e['payload'] or {}).get('text', '')[:90]}"
            for e in reversed(history))
        lines.append(f"Recent conversation (oldest first): {convo}")
    if not lines:
        return "CONTEXT: number not on the roster."
    return "CONTEXT (trusted, from our database):\n" + "\n".join(f"- {line}" for line in lines)
