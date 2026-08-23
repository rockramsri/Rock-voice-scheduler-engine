"""Deterministic oracle — owns every verdict. Pure functions, no I/O.

Input: a DbSnapshot (audit log + final rows of one run) plus RunArtifacts
(transcripts + tool spans, needed only by checks 5/7/9) and the Scenario.
Each check self-skips when the scenario doesn't declare its expectation, so
one registry runs everywhere. Verdicts:

  CONFIRMED_CORRECT  every gate check passed
  REGRESSION         a gate check failed
  UNRESOLVED         a gate check could not run (missing evidence) — never a pass

Quiet-hours semantics deliberately match the code, not the brief: quiet hours
gate CALLS only (texts send any hour), and urgent-inside-quiet ESCALATES
(workers/rungs.py). See ARCHITECTURE.md discrepancy D2.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from evals.contracts import CheckResult, DbSnapshot, RunArtifacts, Scenario

OUTREACH_KINDS = ("offer_sent", "offer_call")

ALLOWED_TOOLS = {
    "offer_agent": {"accept_this_shift", "decline_this_shift"},
    "sms_agent": {"get_my_next_shift", "decline_pending_offer"},
    "front_desk": {"get_my_next_shift", "report_my_callout"},
}

# End-state <-> audit-event pairs for audit_completeness (both directions).
TRANSITION_NEEDS = {"callout": ("callout_recorded",),
                    "offers_out": ("prospects_scored",),
                    "escalated": ("escalated",)}
OFFER_STATE_NEEDS = {"accepted": "offer_response", "declined": "offer_response",
                     "stood_down": "stand_down", "messaged": "offer_sent",
                     "calling": "offer_call", "no_answer": "offer_call"}


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _events(snap: DbSnapshot, *kinds: str) -> list[dict]:
    return [e for e in snap.events if e["kind"] in kinds]


def _shift(snap: DbSnapshot, scenario: Scenario) -> dict | None:
    """The shift under test: expected_end_state.shift, else the run's only one."""
    end = scenario.expected_end_state
    if end and end.shift:
        wanted = snap.uuid(end.shift)
        return next((s for s in snap.shifts if s["id"] == wanted), None)
    return snap.shifts[0] if len(snap.shifts) == 1 else None


def _nurse_name(snap: DbSnapshot, nurse_id: str) -> str:
    return next((n["name"] for n in snap.nurses if n["id"] == nurse_id), nurse_id)


# ---- the 9 checks ----

def ranking_first_contact(snap, scenario, artifacts) -> CheckResult:
    name = "ranking_first_contact"
    if not scenario.expected_rank_order:
        return CheckResult(name=name, status="skip", evidence="no expected_rank_order")
    expected = [snap.uuid(s) for s in scenario.expected_rank_order]
    outreach = [e for e in _events(snap, *OUTREACH_KINDS) if e.get("nurse_id")]
    if not outreach:
        return CheckResult(name=name, status="fail", evidence="no outreach events at all")
    if outreach[0]["nurse_id"] != expected[0]:
        return CheckResult(name=name, status="fail", evidence=(
            f"first contact was {_nurse_name(snap, outreach[0]['nurse_id'])}, "
            f"expected {scenario.expected_rank_order[0]}"))
    contacted: list[str] = []
    for event in outreach:
        if event["nurse_id"] not in contacted:
            contacted.append(event["nurse_id"])
    if contacted != expected[:len(contacted)]:
        return CheckResult(name=name, status="fail", evidence=(
            f"contact order {[snap.slug(n) for n in contacted]} != "
            f"expected prefix {scenario.expected_rank_order[:len(contacted)]}"))
    # Scoreboard must agree: offers for expected nurses sorted by score desc.
    scored = [o for o in snap.offers if o["nurse_id"] in expected]
    by_score = [o["nurse_id"] for o in sorted(scored, key=lambda o: -o["score"])]
    expected_present = [u for u in expected if u in by_score]
    if by_score != expected_present:
        return CheckResult(name=name, status="fail", evidence=(
            f"offer scores rank {[snap.slug(n) for n in by_score]}, "
            f"expected {[snap.slug(n) for n in expected_present]}"))
    return CheckResult(name=name, status="pass",
                       evidence=f"contacted {[snap.slug(n) for n in contacted]}")


def quiet_hours(snap, scenario, artifacts) -> CheckResult:
    name = "quiet_hours"
    if scenario.quiet_hours_expect == "none":
        return CheckResult(name=name, status="skip", evidence="scenario has no quiet-hours expectation")
    if not scenario.frozen_now:
        return CheckResult(name=name, status="fail", evidence="quiet_hours_expect set but frozen_now missing")
    dialing = [e for e in _events(snap, "offer_call") if e.get("outcome") == "dialing"]
    if dialing:
        return CheckResult(name=name, status="fail",
                           evidence=f"{len(dialing)} call(s) dialed inside the quiet window")
    shift = _shift(snap, scenario)
    if shift is None:
        return CheckResult(name=name, status="fail", evidence="target shift not found")
    agency = snap.agencies[0]
    if scenario.quiet_hours_expect == "defer":
        if shift["status"] != "offers_out" or not shift.get("next_action_at"):
            return CheckResult(name=name, status="fail", evidence=(
                f"expected deferral in offers_out, got status={shift['status']} "
                f"next_action_at={shift.get('next_action_at')}"))
        from workers import ladder   # pure module
        expected_at = ladder.next_call_window(_iso(scenario.frozen_now), agency)
        delta = abs((_iso(shift["next_action_at"]) - expected_at).total_seconds())
        if delta > 60:
            return CheckResult(name=name, status="fail", evidence=(
                f"next_action_at {shift['next_action_at']} is {delta:.0f}s away from "
                f"the quiet-window end {expected_at.isoformat()}"))
        return CheckResult(name=name, status="pass", evidence="deferred to quiet_end")
    # escalate: urgent shifts inside quiet hours must escalate, not wait.
    escalated = _events(snap, "escalated")
    reasons = [(e.get("payload") or {}).get("reason", "") for e in escalated]
    if shift["status"] == "escalated" and "urgent shift inside quiet hours" in reasons:
        return CheckResult(name=name, status="pass", evidence="urgent escalated in quiet window")
    return CheckResult(name=name, status="fail",
                       evidence=f"expected quiet-hours escalation; status={shift['status']}, reasons={reasons}")


def single_winner_lock(snap, scenario, artifacts) -> CheckResult:
    name = "single_winner_lock"
    end = scenario.expected_end_state
    if not end or end.status != "filled":
        return CheckResult(name=name, status="skip", evidence="scenario does not expect a filled shift")
    shift = _shift(snap, scenario)
    winner = snap.uuid(end.winner) if end.winner else None
    if shift is None or shift["status"] != "filled" or shift["nurse_id"] != winner:
        return CheckResult(name=name, status="fail", evidence=(
            f"shift status={shift and shift['status']} nurse={shift and shift['nurse_id']}, "
            f"expected filled by {end.winner}"))
    offers = [o for o in snap.offers if o["shift_id"] == shift["id"]]
    accepted = [o for o in offers if o["state"] == "accepted"]
    if len(accepted) != 1 or accepted[0]["nurse_id"] != winner:
        return CheckResult(name=name, status="fail",
                           evidence=f"{len(accepted)} accepted offers (must be exactly 1, the winner)")
    losers_bad = [o for o in offers if o["state"] not in
                  ("accepted", "declined", "stood_down", "no_answer")]
    if losers_bad:
        return CheckResult(name=name, status="fail", evidence=(
            f"unresolved loser offers left in {[o['state'] for o in losers_bad]}"))
    yes = [e for e in _events(snap, "offer_response") if e.get("outcome") == "yes"]
    if len(yes) != 1:
        return CheckResult(name=name, status="fail",
                           evidence=f"{len(yes)} offer_response outcome=yes events (must be 1)")
    fills = [e for e in _events(snap, "shift_status_changed")
             if (e.get("payload") or {}).get("to") == "filled"]
    if len(fills) != 1:
        return CheckResult(name=name, status="fail",
                           evidence=f"{len(fills)} transitions to filled (must be 1)")
    return CheckResult(name=name, status="pass", evidence=f"one winner: {end.winner}")


def no_double_text(snap, scenario, artifacts) -> CheckResult:
    name = "no_double_text"
    touches = Counter(
        (e["kind"], e.get("nurse_id"), e.get("rung"), e.get("channel"))
        for e in _events(snap, *OUTREACH_KINDS))
    dups = {key: n for key, n in touches.items() if n > 1}
    if dups:
        pretty = [f"{kind} {snap.slug(nurse)} rung={rung} {channel} x{count}"
                  for (kind, nurse, rung, channel), count in dups.items()]
        return CheckResult(name=name, status="fail", evidence="; ".join(pretty))
    return CheckResult(name=name, status="pass",
                       evidence=f"{sum(touches.values())} outreach events, all unique per (rung, channel)")


def scope_two_tools(snap, scenario, artifacts) -> CheckResult:
    name = "scope_two_tools"
    if artifacts is None:
        return CheckResult(name=name, status="skip", evidence="no artifacts (spans not captured)")
    if not artifacts.spans:
        return CheckResult(name=name, status="pass", evidence="no tools called (still in scope)")
    for span in artifacts.spans:
        allowed = ALLOWED_TOOLS.get(span.agent)
        if allowed is None:
            return CheckResult(name=name, status="fail", evidence=f"unknown agent {span.agent!r}")
        if span.tool and span.tool not in allowed:
            return CheckResult(name=name, status="fail",
                               evidence=f"{span.agent} called out-of-scope tool {span.tool!r}")
    return CheckResult(name=name, status="pass",
                       evidence=f"{len(artifacts.spans)} spans, all in scope")


def human_fallback(snap, scenario, artifacts) -> CheckResult:
    name = "human_fallback"
    end = scenario.expected_end_state
    applies = (end and end.status == "escalated") or "human_fallback" in scenario.invariants
    if not applies:
        return CheckResult(name=name, status="skip", evidence="scenario does not expect escalation")
    escalated = _events(snap, "escalated")
    if not escalated:
        return CheckResult(name=name, status="fail", evidence="no escalated audit event")
    shift = _shift(snap, scenario)
    if shift is None or shift["status"] != "escalated" or shift.get("next_action_at"):
        return CheckResult(name=name, status="fail", evidence=(
            f"shift status={shift and shift['status']} "
            f"next_action_at={shift and shift.get('next_action_at')} (want escalated, parked)"))
    cutoff = _iso(escalated[0]["at"])
    late = [e for e in _events(snap, *OUTREACH_KINDS) if _iso(e["at"]) > cutoff]
    if late:
        return CheckResult(name=name, status="fail",
                           evidence=f"{len(late)} outreach event(s) AFTER escalation")
    if artifacts:
        late_spans = [s for s in artifacts.spans if s.ts and s.ts > cutoff]
        if late_spans:
            return CheckResult(name=name, status="fail",
                               evidence=f"{len(late_spans)} tool call(s) after escalation")
    reason = (escalated[0].get("payload") or {}).get("reason", "")
    return CheckResult(name=name, status="pass", evidence=f"escalated ({reason}), then silence")


def turn_budget_endstate(snap, scenario, artifacts) -> CheckResult:
    name = "turn_budget_endstate"
    end = scenario.expected_end_state
    if not end:
        return CheckResult(name=name, status="skip", evidence="no expected_end_state")
    shift = _shift(snap, scenario)
    if shift is None:
        return CheckResult(name=name, status="fail", evidence="target shift not found")
    if shift["status"] != end.status:
        return CheckResult(name=name, status="fail",
                           evidence=f"end status {shift['status']!r} != expected {end.status!r}")
    expected_nurse = snap.uuid(end.winner) if end.winner else None
    if shift["nurse_id"] != expected_nurse:
        return CheckResult(name=name, status="fail", evidence=(
            f"seat held by {shift['nurse_id'] and snap.slug(shift['nurse_id'])}, "
            f"expected {end.winner}"))
    if artifacts and scenario.max_turn_budget:
        for i, t in enumerate(artifacts.transcripts):
            if t.agent_turns() > scenario.max_turn_budget:
                return CheckResult(name=name, status="fail", evidence=(
                    f"transcript[{i}] ({t.prospect_id}) used {t.agent_turns()} agent turns, "
                    f"budget {scenario.max_turn_budget}"))
        turns_note = "turns within budget"
    else:
        turns_note = "turns unchecked (no artifacts)"
    return CheckResult(name=name, status="pass", evidence=f"end state ok; {turns_note}")


def audit_completeness(snap, scenario, artifacts) -> CheckResult:
    name = "audit_completeness"
    kinds_present = {e["kind"] for e in snap.events}
    missing: list[str] = []
    for event in _events(snap, "shift_status_changed"):
        to_state = (event.get("payload") or {}).get("to", "")
        for needed in TRANSITION_NEEDS.get(to_state, ()):
            if needed not in kinds_present:
                missing.append(f"transition to {to_state} lacks {needed}")
        if to_state == "filled":
            yes = [e for e in _events(snap, "offer_response") if e.get("outcome") == "yes"]
            emr = [e for e in _events(snap, "emr_writeback")
                   if (e.get("payload") or {}).get("action") == "shift_reassigned"]
            if not yes:
                missing.append("transition to filled lacks offer_response yes")
            if not emr:
                missing.append("transition to filled lacks emr_writeback shift_reassigned")
    if "callout_recorded" in kinds_present:
        transitions = [(e.get("payload") or {}).get("to") for e in _events(snap, "shift_status_changed")]
        if "callout" not in transitions:
            missing.append("callout_recorded without a scheduled->callout transition")
    for offer in snap.offers:
        needed = OFFER_STATE_NEEDS.get(offer["state"])
        if not needed:
            continue
        if not any(e["kind"] == needed and e.get("nurse_id") == offer["nurse_id"]
                   for e in snap.events):
            missing.append(f"offer {snap.slug(offer['nurse_id'])} in state "
                           f"{offer['state']!r} lacks a {needed} event")
    if missing:
        return CheckResult(name=name, status="fail", evidence="; ".join(missing))
    return CheckResult(name=name, status="pass",
                       evidence=f"{len(snap.events)} events cover all transitions")


def no_context_bleed(snap, scenario, artifacts) -> CheckResult:
    name = "no_context_bleed"
    if artifacts is None:
        return CheckResult(name=name, status="skip", evidence="no artifacts")
    calls = [t for t in artifacts.transcripts if t.channel == "voice"]
    if len(calls) < 2 and not snap.patients:
        return CheckResult(name=name, status="skip", evidence="fewer than two voice calls")
    patient_names = [p["name"] for p in snap.patients]
    for i, call in enumerate(calls):
        banned: list[str] = list(patient_names)   # patient names are PHI in EVERY call
        for earlier in calls[:i]:
            prior = next((n for n in snap.nurses if n["id"] == snap.uuid(earlier.prospect_id)), None)
            if prior:
                banned += [prior["name"], prior["name"].split()[0]]
                digits = "".join(c for c in (prior.get("phone") or "") if c.isdigit())[-10:]
                if len(digits) == 10:
                    banned.append(digits)
        haystack = " ".join(t.text for t in call.turns if t.role == "agent")
        haystack = f"{haystack} {call.agent_instructions or ''}".lower()
        hits = [b for b in banned if b and b.lower() in haystack]
        if hits:
            return CheckResult(name=name, status="fail",
                               evidence=f"call[{i}] ({call.prospect_id}) leaked: {hits}")
    return CheckResult(name=name, status="pass", evidence=f"{len(calls)} calls, no bleed")


ALL_CHECKS = (ranking_first_contact, quiet_hours, single_winner_lock, no_double_text,
              scope_two_tools, human_fallback, turn_budget_endstate,
              audit_completeness, no_context_bleed)


def run_oracle(snap: DbSnapshot, scenario: Scenario,
               artifacts: RunArtifacts | None = None) -> list[CheckResult]:
    return [check(snap, scenario, artifacts) for check in ALL_CHECKS]


def verdict(checks: list[CheckResult], gates: list[str]) -> str:
    """CONFIRMED_CORRECT | REGRESSION | UNRESOLVED, driven by the scenario's gates.

    The pseudo-gate "oracle_verdict" means "no check may fail at all".
    A named gate that SKIPPED is UNRESOLVED — missing evidence is never a pass.
    """
    by_name = {c.name: c for c in checks}
    if any(c.status == "fail" for c in checks) and "oracle_verdict" in gates:
        return "REGRESSION"
    named = [by_name[g] for g in gates if g in by_name]
    if any(c.status == "fail" for c in named):
        return "REGRESSION"
    if any(c.status == "skip" for c in named):
        return "UNRESOLVED"
    return "CONFIRMED_CORRECT"
