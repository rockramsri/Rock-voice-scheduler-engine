"""M2 — the 9 oracle checks against HAND-CRAFTED states, good and broken.

No agents, no DB, no network: every snapshot below is written by hand, which
is exactly what makes the oracle trustworthy before any runner exists. Each
broken fixture flips ONE thing and must trip exactly the check that owns it.
"""

import copy

from evals import oracle
from evals.contracts import (CallTranscript, DbSnapshot, EndState, RunArtifacts,
                             Scenario, Span, Turn)

# Stable fake uuids so fixtures read like the story they tell.
U = {"CG-101": "uuid-101", "CG-207": "uuid-207", "CG-330": "uuid-330",
     "SH-1": "uuid-sh1", "PT-1": "uuid-pt1", "AGENCY": "uuid-ag"}

AGENCY_ROW = {"id": U["AGENCY"], "name": "Eval Agency", "timezone": "America/New_York",
              "quiet_start": 22, "quiet_end": 6, "urgent_lead_hours": 5,
              "relaxed_lead_hours": 24}


def ts(i: int) -> str:
    return f"2026-08-19T14:{i // 60:02d}:{i % 60:02d}+00:00"


def ev(i: int, kind: str, *, nurse: str | None = None, channel: str | None = None,
       rung: int | None = None, outcome: str | None = None, payload: dict | None = None) -> dict:
    return {"id": i, "at": ts(i), "kind": kind, "shift_id": U["SH-1"],
            "nurse_id": U[nurse] if nurse else None, "channel": channel,
            "rung": rung, "outcome": outcome, "payload": payload or {}}


def golden() -> DbSnapshot:
    """Happy path: callout -> scored -> SMS rung -> CG-101 says YES -> filled."""
    return DbSnapshot(
        run_agency_id=U["AGENCY"],
        slug_map=dict(U),
        agencies=[AGENCY_ROW],
        nurses=[
            {"id": U["CG-101"], "name": "Ana Reyes", "phone": "555-9101"},
            {"id": U["CG-207"], "name": "Bruno Silva", "phone": "555-9207"},
            {"id": U["CG-330"], "name": "Carla Jones", "phone": "555-9330"},
        ],
        patients=[{"id": U["PT-1"], "name": "Dora Wexler", "area": "Jersey City"}],
        shifts=[{"id": U["SH-1"], "agency_id": U["AGENCY"], "patient_id": U["PT-1"],
                 "nurse_id": U["CG-101"], "status": "filled",
                 "callout_nurse_id": U["CG-330"], "next_action_at": None,
                 "starts_at": "2026-08-20T12:00:00+00:00",
                 "ends_at": "2026-08-20T20:00:00+00:00"}],
        offers=[{"id": "o-101", "shift_id": U["SH-1"], "nurse_id": U["CG-101"],
                 "score": 0.9, "state": "accepted", "rung": 1},
                {"id": "o-207", "shift_id": U["SH-1"], "nurse_id": U["CG-207"],
                 "score": 0.8, "state": "stood_down", "rung": 1}],
        events=[
            ev(1, "shift_status_changed", payload={"from": "scheduled", "to": "callout"}),
            ev(2, "callout_recorded", nurse="CG-330", payload={"reason": "sick"}),
            ev(3, "emr_writeback", nurse="CG-330", payload={"action": "callout_documented"}),
            ev(4, "shift_status_changed", payload={"from": "callout", "to": "offers_out"}),
            ev(5, "prospects_scored", payload={"prospects": "Ana, Bruno"}),
            ev(6, "offer_sent", nurse="CG-101", channel="sms", rung=1, outcome="sent"),
            ev(7, "offer_sent", nurse="CG-207", channel="sms", rung=1, outcome="sent"),
            ev(8, "offer_response", nurse="CG-101", outcome="yes"),
            ev(9, "shift_status_changed", payload={"from": "offers_out", "to": "filled"}),
            ev(10, "emr_writeback", nurse="CG-101", payload={"action": "shift_reassigned"}),
            ev(11, "stand_down", nurse="CG-207", outcome="sent"),
        ],
    )


def scenario(**over) -> Scenario:
    base = dict(scenario_id="test", channel="ladder",
                expected_rank_order=["CG-101", "CG-207"],
                expected_end_state=EndState(shift="SH-1", status="filled", winner="CG-101"),
                max_turn_budget=3,
                gates=["oracle_verdict"])
    base.update(over)
    return Scenario(**base)


def results(snap, scn, artifacts=None) -> dict[str, str]:
    return {c.name: c.status for c in oracle.run_oracle(snap, scn, artifacts)}


def one(check_fn, snap, scn, artifacts=None):
    return check_fn(snap, scn, artifacts)


# ---- golden path is green ----

def test_golden_snapshot_passes_everything():
    got = results(golden(), scenario())
    assert "fail" not in got.values(), got
    assert got["ranking_first_contact"] == "pass"
    assert got["single_winner_lock"] == "pass"
    assert got["no_double_text"] == "pass"
    assert got["turn_budget_endstate"] == "pass"
    assert got["audit_completeness"] == "pass"
    checks = oracle.run_oracle(golden(), scenario())
    assert oracle.verdict(checks, ["oracle_verdict", "single_winner_lock"]) == "CONFIRMED_CORRECT"


# ---- ranking_first_contact ----

def test_wrong_first_contact_fails_ranking():
    snap = golden()
    snap.events[5], snap.events[6] = (   # Bruno texted before Ana
        {**snap.events[6], "id": 6, "at": ts(6)},
        {**snap.events[5], "id": 7, "at": ts(7)})
    check = one(oracle.ranking_first_contact, snap, scenario())
    assert check.status == "fail" and "Bruno" in check.evidence


def test_scoreboard_disagreeing_with_rank_order_fails():
    snap = golden()
    snap.offers[0]["score"], snap.offers[1]["score"] = 0.5, 0.9   # scores now say Bruno first
    assert one(oracle.ranking_first_contact, snap, scenario()).status == "fail"


# ---- no_double_text ----

def test_duplicate_send_same_rung_and_channel_fails():
    snap = golden()
    snap.events.insert(7, ev(12, "offer_sent", nurse="CG-101", channel="sms",
                             rung=1, outcome="sent"))
    check = one(oracle.no_double_text, snap, scenario())
    assert check.status == "fail" and "CG-101" in check.evidence


def test_same_channel_on_a_later_rung_is_legitimate():
    snap = golden()   # RELAXED ladder really does SMS on rung 1 AND rung 2
    snap.events.append(ev(12, "offer_sent", nurse="CG-101", channel="sms",
                          rung=2, outcome="sent"))
    assert one(oracle.no_double_text, snap, scenario()).status == "pass"


# ---- single_winner_lock ----

def test_two_accepted_offers_fail():
    snap = golden()
    snap.offers[1]["state"] = "accepted"
    assert one(oracle.single_winner_lock, snap, scenario()).status == "fail"


def test_two_yes_events_fail():
    snap = golden()
    snap.events.append(ev(12, "offer_response", nurse="CG-207", outcome="yes"))
    assert one(oracle.single_winner_lock, snap, scenario()).status == "fail"


def test_unresolved_loser_offer_fails():
    snap = golden()
    snap.offers[1]["state"] = "messaged"   # loser never stood down
    assert one(oracle.single_winner_lock, snap, scenario()).status == "fail"


# ---- turn_budget_endstate ----

def test_wrong_winner_fails_endstate():
    snap = golden()
    snap.shifts[0]["nurse_id"] = U["CG-207"]
    check = one(oracle.turn_budget_endstate, snap, scenario())
    assert check.status == "fail" and "CG-207" in check.evidence


def test_turn_budget_exceeded_fails():
    turns = [Turn(role="user", text="hm")] + [Turn(role="agent", text=f"t{i}") for i in range(4)]
    artifacts = RunArtifacts(scenario_id="test", transcripts=[
        CallTranscript(prospect_id="CG-101", channel="voice", turns=turns)])
    check = one(oracle.turn_budget_endstate, golden(), scenario(), artifacts)
    assert check.status == "fail" and "4 agent turns" in check.evidence


# ---- audit_completeness ----

def test_missing_prospects_scored_fails_audit():
    snap = golden()
    snap.events = [e for e in snap.events if e["kind"] != "prospects_scored"]
    check = one(oracle.audit_completeness, snap, scenario())
    assert check.status == "fail" and "prospects_scored" in check.evidence


def test_stood_down_offer_without_event_fails_audit():
    snap = golden()
    snap.events = [e for e in snap.events if e["kind"] != "stand_down"]
    check = one(oracle.audit_completeness, snap, scenario())
    assert check.status == "fail" and "stand_down" in check.evidence


def test_filled_without_emr_writeback_fails_audit():
    snap = golden()
    snap.events = [e for e in snap.events
                   if (e.get("payload") or {}).get("action") != "shift_reassigned"]
    assert one(oracle.audit_completeness, snap, scenario()).status == "fail"


# ---- scope_two_tools ----

def test_out_of_scope_tool_fails_hard():
    artifacts = RunArtifacts(scenario_id="test", spans=[
        Span(span_id="s1", agent="offer_agent", tool="accept_this_shift"),
        Span(span_id="s2", agent="offer_agent", tool="find_nurse")])
    check = one(oracle.scope_two_tools, golden(), scenario(), artifacts)
    assert check.status == "fail" and "find_nurse" in check.evidence


def test_in_scope_tools_pass_and_no_spans_skip():
    ok = RunArtifacts(scenario_id="test", spans=[
        Span(span_id="s1", agent="offer_agent", tool="decline_this_shift"),
        Span(span_id="s2", agent="sms_agent", tool="get_my_next_shift")])
    assert one(oracle.scope_two_tools, golden(), scenario(), ok).status == "pass"
    assert one(oracle.scope_two_tools, golden(), scenario(), None).status == "skip"
    empty = RunArtifacts(scenario_id="test")
    assert one(oracle.scope_two_tools, golden(), scenario(), empty).status == "pass"


# ---- no_context_bleed ----

def _two_calls(second_call_text: str) -> RunArtifacts:
    return RunArtifacts(scenario_id="test", transcripts=[
        CallTranscript(prospect_id="CG-101", channel="voice",
                       turns=[Turn(role="agent", text="Hi Ana, a wound care shift...")]),
        CallTranscript(prospect_id="CG-207", channel="voice",
                       turns=[Turn(role="agent", text=second_call_text)])])


def test_prior_prospect_name_in_later_call_fails():
    artifacts = _two_calls("Hi Bruno — Ana passed on this, so it's yours if you want it.")
    check = one(oracle.no_context_bleed, golden(), scenario(), artifacts)
    assert check.status == "fail" and "ana" in check.evidence.lower()


def test_patient_name_spoken_fails():
    artifacts = _two_calls("This shift is caring for Dora Wexler in Jersey City.")
    assert one(oracle.no_context_bleed, golden(), scenario(), artifacts).status == "fail"


def test_clean_calls_pass_bleed():
    artifacts = _two_calls("Hi Bruno, a wound care shift tomorrow in Jersey City.")
    assert one(oracle.no_context_bleed, golden(), scenario(), artifacts).status == "pass"


# ---- human_fallback (escalation snapshot) ----

def escalated_snap() -> DbSnapshot:
    snap = golden()
    snap.shifts[0].update({"nurse_id": None, "status": "escalated", "next_action_at": None})
    snap.offers = [{"id": "o-101", "shift_id": U["SH-1"], "nurse_id": U["CG-101"],
                    "score": 0.9, "state": "declined", "rung": 1}]
    snap.events = [
        ev(1, "shift_status_changed", payload={"from": "scheduled", "to": "callout"}),
        ev(2, "callout_recorded", nurse="CG-330", payload={"reason": "sick"}),
        ev(4, "shift_status_changed", payload={"from": "callout", "to": "offers_out"}),
        ev(5, "prospects_scored"),
        ev(6, "offer_sent", nurse="CG-101", channel="sms", rung=1, outcome="sent"),
        ev(7, "offer_response", nurse="CG-101", outcome="no"),
        ev(8, "escalated", payload={"reason": "all prospects exhausted"}),
        ev(9, "shift_status_changed", payload={"from": "offers_out", "to": "escalated"}),
    ]
    return snap


def esc_scenario() -> Scenario:
    return scenario(expected_end_state=EndState(shift="SH-1", status="escalated", winner=None),
                    expected_rank_order=["CG-101"])


def test_escalation_snapshot_passes():
    got = results(escalated_snap(), esc_scenario())
    assert got["human_fallback"] == "pass" and got["turn_budget_endstate"] == "pass"
    assert "fail" not in got.values(), got


def test_missing_escalated_event_fails():
    snap = escalated_snap()
    snap.events = [e for e in snap.events if e["kind"] != "escalated"]
    assert one(oracle.human_fallback, snap, esc_scenario()).status == "fail"


def test_outreach_after_escalation_fails():
    snap = escalated_snap()
    snap.events.append(ev(30, "offer_sent", nurse="CG-101", channel="sms",
                          rung=2, outcome="sent"))
    check = one(oracle.human_fallback, snap, esc_scenario())
    assert check.status == "fail" and "AFTER escalation" in check.evidence


# ---- quiet_hours ----

def quiet_snap(next_action_at: str | None, status: str = "offers_out") -> DbSnapshot:
    snap = golden()
    snap.shifts[0].update({"nurse_id": None, "status": status,
                           "next_action_at": next_action_at})
    snap.offers[0]["state"] = "messaged"
    snap.offers[1]["state"] = "messaged"
    snap.events = [e for e in snap.events if e["kind"] in
                   ("shift_status_changed", "callout_recorded", "prospects_scored",
                    "offer_sent") and (e.get("payload") or {}).get("to") != "filled"]
    return snap


FROZEN = "2026-08-19T23:30:00-04:00"                 # 11:30pm New York: quiet
NEXT_OK = "2026-08-20T06:00:00-04:00"                # exactly quiet_end next day


def test_quiet_deferral_passes():
    scn = scenario(quiet_hours_expect="defer", frozen_now=FROZEN,
                   expected_end_state=EndState(shift="SH-1", status="offers_out", winner=None))
    assert one(oracle.quiet_hours, quiet_snap(NEXT_OK), scn).status == "pass"


def test_quiet_deferral_to_wrong_time_fails():
    scn = scenario(quiet_hours_expect="defer", frozen_now=FROZEN,
                   expected_end_state=EndState(shift="SH-1", status="offers_out", winner=None))
    check = one(oracle.quiet_hours, quiet_snap("2026-08-20T08:00:00-04:00"), scn)
    assert check.status == "fail" and "away from" in check.evidence


def test_call_dialed_in_quiet_window_fails():
    snap = quiet_snap(NEXT_OK)
    snap.events.append(ev(20, "offer_call", nurse="CG-101", channel="voice",
                          rung=3, outcome="dialing"))
    scn = scenario(quiet_hours_expect="defer", frozen_now=FROZEN,
                   expected_end_state=EndState(shift="SH-1", status="offers_out", winner=None))
    assert one(oracle.quiet_hours, snap, scn).status == "fail"


def test_urgent_quiet_escalation_passes():
    snap = quiet_snap(None, status="escalated")
    snap.events.append(ev(20, "escalated",
                          payload={"reason": "urgent shift inside quiet hours"}))
    scn = scenario(quiet_hours_expect="escalate", frozen_now=FROZEN,
                   expected_end_state=EndState(shift="SH-1", status="escalated", winner=None))
    assert one(oracle.quiet_hours, snap, scn).status == "pass"


# ---- verdict aggregation ----

def test_verdict_regression_on_gate_fail():
    snap = golden()
    snap.offers[1]["state"] = "accepted"
    checks = oracle.run_oracle(snap, scenario())
    assert oracle.verdict(checks, ["single_winner_lock"]) == "REGRESSION"


def test_verdict_unresolved_when_gate_check_skipped():
    checks = oracle.run_oracle(golden(), scenario(), artifacts=None)   # no spans
    assert oracle.verdict(checks, ["scope_two_tools"]) == "UNRESOLVED"


def test_verdict_ignores_nongated_failures_unless_oracle_verdict_gate():
    snap = golden()
    snap.events.insert(7, ev(12, "offer_sent", nurse="CG-101", channel="sms",
                             rung=1, outcome="sent"))   # no_double_text fails
    checks = oracle.run_oracle(snap, scenario())
    assert oracle.verdict(checks, ["single_winner_lock"]) == "CONFIRMED_CORRECT"
    assert oracle.verdict(checks, ["oracle_verdict"]) == "REGRESSION"
