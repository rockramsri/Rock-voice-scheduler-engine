"""Voice L2 toolkit — text-mode sessions + tool recorders for component tests.

L2 tests the OfferAgent/FrontDesk conversation logic with the REAL prompts
and REAL tool schemas, but mocked tool execution (mock_tools) so nothing
touches the database. The recorders below capture the arguments the LLM
chose, which is exactly what L2 asserts on: right tool, right args, in scope.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")   # OPENAI_API_KEY


def build_text_llm():
    """The generator model for text-mode sessions (same family as production)."""
    from livekit.plugins import openai
    return openai.LLM(model=os.getenv("LLM_MODEL", "gpt-4.1-mini"))


# A complete offer row as data.db.get_offer_full would return it — no DB.
FAKE_OFFER = {
    "id": "offer-1", "shift_id": "shift-1", "nurse_id": "nurse-1", "state": "calling",
    "shifts": {"id": "shift-1", "specialty": "wound care", "area": "Jersey City",
               "starts_at": "2026-08-25T16:00:00+00:00",
               "ends_at": "2026-08-26T00:00:00+00:00", "pay_rate": 42},
    "nurses": {"id": "nurse-1", "name": "Ana Reyes", "phone": "555-9101",
               "preferences": {}},
}

FAKE_NURSE_MATCH = {"id": "nurse-1", "name": "Ana Reyes", "phone": "+15551239101",
                    "active": True, "preferences": {}}


def record_accept(calls: list[dict]):
    def accept_this_shift() -> str:
        calls.append({})
        return ("Confirmed — the shift is theirs. Say the schedule and area "
                "will arrive by text, and thank them.")
    return accept_this_shift


def record_decline(calls: list[dict]):
    def decline_this_shift(reason: str = "", avoid_weekends: bool = False) -> str:
        calls.append({"reason": reason, "avoid_weekends": avoid_weekends})
        return "Noted. Thank them for their time and end the call politely."
    return decline_this_shift


def record_callout(calls: list[dict]):
    def report_my_callout(reason: str, nurse_name: str = "") -> str:
        calls.append({"reason": reason, "nurse_name": nurse_name})
        return ("Callout recorded for your Tuesday shift. Replacement outreach "
                "has already started — nothing else is needed from you.")
    return report_my_callout


# ---- L3 in-process: persona talks to the REAL OfferAgent against the eval DB ----

TURN_MARGIN = 2
PERSONA_MODEL = "openai:gpt-4.1-mini"


def _persona(scenario):
    from pydantic_ai import Agent
    persona = scenario.persona or {}
    policy = "\n".join(f"- {rule}" for rule in persona.get("policy", []))
    return Agent(PERSONA_MODEL, output_type=str, instructions=(
        f"You are a home-health nurse on a phone call with the agency. "
        f"Style: {persona.get('style', 'cooperative')}. Speak one short turn "
        f"at a time, no quotes. HARD RULES:\n{policy}"))


async def seed_offer_world(scenario):
    """Roster + offers_out shift + rank-ordered offers; top pick is `calling`."""
    from data import db
    from evals import seed

    fx = scenario.callout_fixture
    run = seed.seed_run(
        roster=scenario.roster_fixture,
        shifts=[{"slug": fx.get("shift", "SH-1"),
                 "specialty": fx.get("specialty", "wound care"),
                 "area": fx.get("area", "Jersey City"),
                 "starts_in_hours": fx.get("starts_in_hours", 26),
                 "status": "offers_out", "rung": 3,
                 "callout_nurse": fx.get("callout_nurse")}],
    )
    shift_id = run.uuid(fx.get("shift", "SH-1"))
    rows = []
    for i, slug in enumerate(scenario.expected_rank_order):
        rows.append({"shift_id": shift_id, "nurse_id": run.uuid(slug),
                     "score": 0.9 - i * 0.1, "reason": "eval fixture"})
    await db.insert_offers(rows)
    offers = await db.offers_for_shift(shift_id)
    by_nurse = {o["nurse_id"]: o for o in offers}
    top = by_nurse[run.uuid(scenario.expected_rank_order[0])]
    await db.set_offer_state(top["id"], "calling", ["scored"])
    await db.log_event("worker", "offer_call", shift_id=shift_id,
                       nurse_id=top["nurse_id"], channel="voice",
                       rung=3, outcome="dialing")
    offer = await db.get_offer_full(top["id"])
    return run, offer


async def _after_call(shift_id: str, agency: dict) -> None:
    """One worker burst so a lone decline / no-intent can escalate or advance.

    Outbound SMS/calls are patched to no-ops so nothing leaves the machine.
    """
    from unittest.mock import AsyncMock, patch

    from data import db
    from workers import dispatch_worker

    shift = await db.get_shift(shift_id)
    if not shift or shift["status"] not in ("callout", "offers_out"):
        return
    # Stale any live 'calling' row so voice_rung re-evaluates instead of waiting.
    for offer in await db.offers_for_shift(shift_id, states=["calling"]):
        await db.set_offer_state(offer["id"], "no_answer", ["calling"])
    with (patch("channels.sms.send_sms", new_callable=AsyncMock,
                return_value={"ok": True}),
          patch("channels.sms.send_whatsapp", new_callable=AsyncMock,
                return_value={"ok": True}),
          patch("channels.outbound.place_call", new_callable=AsyncMock,
                return_value={"ok": True})):
        await dispatch_worker._handle(await db.get_shift(shift_id), agency)


async def run_once(scenario, run_idx: int) -> dict:
    """One L3 trial: seed → persona ↔ OfferAgent → worker burst → oracle → judge."""
    import time
    import uuid as uuidlib
    from datetime import UTC, datetime

    from livekit.agents import AgentSession

    from evals import bus
    from evals import judge as judge_mod
    from evals import oracle, seed
    from evals.contracts import CallTranscript, RunArtifacts, Span, Timings, Turn
    from voice.agents.offer_agent import build_offer_agent

    run, offer = await seed_offer_world(scenario)
    prospect = scenario.expected_rank_order[0]
    agency = seed.client().table("agencies").select("*").eq(
        "id", run.agency_id).limit(1).execute().data[0]
    artifacts_dir = (seed.ARTIFACTS_DIR / scenario.scenario_id /
                     f"{datetime.now(UTC):%Y%m%dT%H%M%S}-run{run_idx}")
    transcript = CallTranscript(prospect_id=prospect, channel="voice",
                                agent_instructions=None)
    spans: list[Span] = []
    per_turn_ms: list[float] = []

    try:
        agent = build_offer_agent(offer, override=bool(
            (scenario.callout_fixture or {}).get("override")))
        transcript.agent_instructions = agent.instructions
        persona = _persona(scenario)
        history = None
        inbound = ("Rock from Rockram Home Health Care is calling you about "
                   "an open shift. Answer the phone.")

        async with build_text_llm() as llm, AgentSession(llm=llm) as session:
            await session.start(agent)
            for _ in range((scenario.max_turn_budget or 3) + TURN_MARGIN):
                persona_result = await persona.run(inbound, message_history=history)
                history = persona_result.all_messages()
                nurse_text = persona_result.output.strip()
                transcript.turns.append(Turn(role="user", text=nurse_text,
                                             ts=datetime.now(UTC)))
                bus.emit("turn", scenario=scenario.scenario_id, run_idx=run_idx,
                         role="user", text=nurse_text)
                started = time.monotonic()
                result = await session.run(user_input=nurse_text)
                per_turn_ms.append((time.monotonic() - started) * 1000)
                # Capture tool names from this turn as spans.
                for ev in result.events:
                    item = getattr(ev, "item", ev)
                    name = getattr(item, "name", None)
                    # function_call only — the function_call_output item carries
                    # the same name and would double-count the span.
                    if (name in {"accept_this_shift", "decline_this_shift"}
                            and getattr(item, "type", "function_call") == "function_call"):
                        args = getattr(item, "arguments", None)
                        if isinstance(args, str):
                            import json
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {"raw": args}
                        spans.append(Span(span_id=uuidlib.uuid4().hex[:8],
                                          agent="offer_agent", tool=name,
                                          args=args if isinstance(args, dict) else None,
                                          ts=datetime.now(UTC)))
                        bus.emit("tool", scenario=scenario.scenario_id,
                                 run_idx=run_idx, name=name,
                                 args=args if isinstance(args, dict) else None)
                    role = getattr(item, "role", None)
                    text = getattr(item, "text_content", None) or getattr(item, "content", None)
                    if role == "assistant" and text:
                        if isinstance(text, list):
                            text = " ".join(str(x) for x in text)
                        transcript.turns.append(Turn(role="agent", text=str(text),
                                                     ts=datetime.now(UTC)))
                        bus.emit("turn", scenario=scenario.scenario_id,
                                 run_idx=run_idx, role="agent", text=str(text))
                from data import db
                fresh = await db.get_offer_full(offer["id"])
                if fresh and fresh["state"] not in ("scored", "messaged", "calling", "fallback"):
                    break
                inbound = transcript.turns[-1].text if transcript.turns else ""

        await _after_call(offer["shift_id"], agency)
        import asyncio
        await asyncio.sleep(1.0)

        artifacts = RunArtifacts(
            scenario_id=scenario.scenario_id, run_idx=run_idx,
            engine_profile=scenario.engine_profile,
            transcripts=[transcript], spans=spans,
            timings=Timings(ttfa_ms=per_turn_ms[0] if per_turn_ms else None,
                            per_turn_ms=per_turn_ms,
                            total_ms=sum(per_turn_ms) if per_turn_ms else None,
                            stage_ms=None),
            db_ref=str(artifacts_dir / "snapshot.json"))
        snap = seed.snapshot(run, save_to=artifacts_dir / "snapshot.json")
        (artifacts_dir / "artifacts.json").write_text(artifacts.model_dump_json(indent=1))
        checks = oracle.run_oracle(snap, scenario, artifacts)
        judged = None
        if scenario.judge_rubric:
            judged = await judge_mod.judge_transcript(transcript, scenario.judge_rubric)
            (artifacts_dir / "judge.json").write_text(judged.model_dump_json(indent=1))
        import json as jsonlib
        result = {"run_idx": run_idx,
                  "verdict": oracle.verdict(checks, scenario.gates),
                  "checks": {c.name: c.status for c in checks},
                  "failed": [f"{c.name}: {c.evidence}" for c in checks if c.status == "fail"],
                  "judge_all_yes": judged.all_yes if judged else None,
                  "judge_model": judged.model if judged else None,
                  "turns": transcript.agent_turns(),
                  "ttfa_ms": round(per_turn_ms[0], 1) if per_turn_ms else None,
                  "per_turn_ms": per_turn_ms,
                  "artifacts": str(artifacts_dir)}
        (artifacts_dir / "result.json").write_text(jsonlib.dumps(result, indent=1))
        return result
    finally:
        seed.cleanup(run)


async def run_scenario(path, k: int | None = None) -> list[dict]:
    from evals import bus
    from evals.contracts import Scenario
    scenario = Scenario.load(path)
    trials = k or scenario.k_trials
    results = []
    for i in range(trials):
        bus.emit("run_start", scenario=scenario.scenario_id, run_idx=i, k=trials)
        result = await run_once(scenario, i)
        flag = "PASS" if result["verdict"] == "CONFIRMED_CORRECT" else result["verdict"]
        judge_note = ("" if result["judge_all_yes"] is None
                      else f" judge={'yes' if result['judge_all_yes'] else 'NO'}")
        print(f"  run {i}: {flag} turns={result['turns']} "
              f"ttfa={result['ttfa_ms']}ms{judge_note}")
        for line in result["failed"]:
            print(f"         FAIL {line}")
        bus.emit("run_result", scenario=scenario.scenario_id, run_idx=i,
                 verdict=result["verdict"], turns=result["turns"],
                 ttfa_ms=result["ttfa_ms"], judge_all_yes=result["judge_all_yes"],
                 failed=result["failed"])
        results.append(result)
    return results


def main() -> int:
    import asyncio
    import sys

    from evals import judge as judge_mod
    from evals.contracts import Scenario
    from evals import seed
    seed.load_eval_env()

    path = sys.argv[1]
    k = int(sys.argv[sys.argv.index("--k") + 1]) if "--k" in sys.argv else None
    scenario = Scenario.load(path)
    print(f"{scenario.scenario_id} (channel={scenario.channel}, k={k or scenario.k_trials})")
    results = asyncio.run(run_scenario(path, k))
    oracle_ok = [r["verdict"] == "CONFIRMED_CORRECT" for r in results]
    print(f"pass^{len(results)}: {'PASS' if all(oracle_ok) else 'FAIL'} "
          f"({sum(oracle_ok)}/{len(results)} runs confirmed)")
    judged = [r["judge_all_yes"] for r in results if r["judge_all_yes"] is not None]
    if judged:
        cal = judge_mod.agreement(judged, oracle_ok[:len(judged)])
        print(f"judge-oracle agreement: {cal['agreement_pct']}% "
              f"({cal['stability']})")
    return 0 if all(oracle_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())

