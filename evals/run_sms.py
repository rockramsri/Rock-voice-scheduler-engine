"""SMS runner — a persona texts the REAL work plane; the oracle grades the DB.

The loop mirrors channels/webhook.py exactly (strict YES/NO fast path first,
then the scoped SMS agent), but in-process: no aiohttp, no TextBelt, nothing
leaves the machine. The persona LLM only ever sees what a nurse would see —
the offer text and replies — while the harness stays omniscient via the DB.

Run one scenario:  .venv/bin/python -m evals.run_sms evals/scenarios/co-0006-*.yaml --k 5
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid as uuidlib
from datetime import UTC, datetime
from pathlib import Path

from evals import oracle, seed
from evals.contracts import (CallTranscript, RunArtifacts, Scenario, Span,
                             Timings, Turn)

seed.load_eval_env()   # BEFORE any production import freezes SUPABASE_*

from pydantic_ai import Agent  # noqa: E402
from pydantic_ai.messages import ToolCallPart  # noqa: E402

PERSONA_MODEL = "openai:gpt-4.1-mini"
TURN_MARGIN = 2   # loop cap = max_turn_budget + margin


def _persona_agent(scenario: Scenario) -> Agent:
    persona = scenario.persona or {}
    policy = "\n".join(f"- {rule}" for rule in persona.get("policy", []))
    return Agent(PERSONA_MODEL, output_type=str, instructions=(
        f"You are a home-health nurse texting with your agency. "
        f"Style: {persona.get('style', 'cooperative')}. You write exactly one SMS "
        f"per turn: short, informal, no quotes around it. HARD RULES you must "
        f"never break:\n{policy}"))


async def _seed_world(scenario: Scenario) -> tuple[seed.Run, str, dict]:
    """Seed roster + an offers_out shift with a pending (messaged) offer."""
    from data import db

    fx = scenario.callout_fixture
    run = seed.seed_run(
        roster=scenario.roster_fixture,
        shifts=[{"slug": fx.get("shift", "SH-1"),
                 "specialty": fx.get("specialty", "wound care"),
                 "area": fx.get("area", "Jersey City"),
                 "starts_in_hours": fx.get("starts_in_hours", 26),
                 "status": "offers_out", "rung": 1,
                 "callout_nurse": fx.get("callout_nurse")}],
    )
    shift_id = run.uuid(fx.get("shift", "SH-1"))
    prospect_slug = scenario.expected_rank_order[0]
    nurse_id = run.uuid(prospect_slug)

    # Mirror what the SMS rung does: offer row -> bump to messaged -> audit it.
    await db.insert_offers([{"shift_id": shift_id, "nurse_id": nurse_id,
                             "score": 0.9, "reason": "eval fixture"}])
    offer = (await db.offers_for_shift(shift_id))[0]
    await db.bump_offer_rung(offer["id"], 1, "sms")
    await db.log_event("worker", "offer_sent", shift_id=shift_id, nurse_id=nurse_id,
                       channel="sms", rung=1, outcome="seeded")

    shift_row = await db.get_shift(shift_id)
    agency_row = seed.client().table("agencies").select("*").eq(
        "id", run.agency_id).limit(1).execute().data[0]
    from workers.rungs import _offer_text
    return run, _offer_text(shift_row, agency_row), {"offer_id": offer["id"],
                                                     "prospect": prospect_slug}


async def _reply_like_the_webhook(phone: str, body: str,
                                  spans: list[Span]) -> str:
    """channels/webhook.py routing, in-process, with tool spans captured.

    Mirrors reply_to_sms's four lines so we can read tool calls off
    result.all_messages(); the agent builder and context builder are the
    REAL production functions.
    """
    from channels.webhook import _offer_reply
    from data import db
    from workplane.agents import sms_agent

    await db.log_event("webhook", "sms_in", payload={"phone": phone, "text": body})
    reply = await _offer_reply(phone, body)
    if reply is None:
        allowed = await db.find_nurses_by_phone(phone)
        context = await sms_agent._context_for(phone, allowed)
        agent = sms_agent._build_sms_agent(allowed, phone)
        result = await agent.run(f"{context}\n\nNew SMS from {phone}: {body}")
        for part in (p for m in result.all_messages() for p in m.parts
                     if isinstance(p, ToolCallPart)):
            spans.append(Span(span_id=uuidlib.uuid4().hex[:8], agent="sms_agent",
                              tool=part.tool_name, args=part.args_as_dict(),
                              ts=datetime.now(UTC)))
        reply = result.output
    await db.log_event("webhook", "sms_out", payload={"phone": phone, "text": reply})
    return reply


async def run_once(scenario: Scenario, run_idx: int) -> dict:
    """One trial: seed -> converse -> snapshot -> oracle -> judge -> cleanup."""
    from data import db
    from evals import judge as judge_mod

    run, offer_text, meta = await _seed_world(scenario)
    prospect = meta["prospect"]
    phone = next(n["phone"] for n in scenario.roster_fixture if n["slug"] == prospect)

    artifacts_dir = (seed.ARTIFACTS_DIR / scenario.scenario_id /
                     f"{datetime.now(UTC):%Y%m%dT%H%M%S}-run{run_idx}")
    transcript = CallTranscript(prospect_id=prospect, channel="sms")
    spans: list[Span] = []
    per_turn_ms: list[float] = []

    try:
        persona = _persona_agent(scenario)
        history = None
        inbound = offer_text                    # the nurse reacts to the offer SMS
        for _ in range((scenario.max_turn_budget or 3) + TURN_MARGIN):
            persona_result = await persona.run(inbound, message_history=history)
            history = persona_result.all_messages()
            nurse_text = persona_result.output.strip()
            transcript.turns.append(Turn(role="user", text=nurse_text, ts=datetime.now(UTC)))

            started = time.monotonic()
            reply = await _reply_like_the_webhook(phone, nurse_text, spans)
            per_turn_ms.append((time.monotonic() - started) * 1000)
            transcript.turns.append(Turn(role="agent", text=reply, ts=datetime.now(UTC)))

            state = seed.client().table("offers").select("state").eq(
                "id", meta["offer_id"]).execute().data[0]["state"]
            if state not in ("scored", "messaged", "calling", "fallback"):
                break                            # offer resolved: conversation over
            inbound = reply

        await asyncio.sleep(1.0)                 # let stand-down background tasks land

        artifacts = RunArtifacts(
            scenario_id=scenario.scenario_id, run_idx=run_idx,
            engine_profile=scenario.engine_profile,
            transcripts=[transcript], spans=spans,
            timings=Timings(ttfa_ms=per_turn_ms[0] if per_turn_ms else None,
                            per_turn_ms=per_turn_ms,
                            total_ms=sum(per_turn_ms) if per_turn_ms else None,
                            stage_ms=None),      # no STT/TTS stages on SMS: MISSING
            db_ref=str(artifacts_dir / "snapshot.json"))
        snap = seed.snapshot(run, save_to=artifacts_dir / "snapshot.json")
        (artifacts_dir / "artifacts.json").write_text(artifacts.model_dump_json(indent=1))

        checks = oracle.run_oracle(snap, scenario, artifacts)
        oracle_verdict = oracle.verdict(checks, scenario.gates)
        judged = None
        if scenario.judge_rubric:
            judged = await judge_mod.judge_transcript(transcript, scenario.judge_rubric)
            (artifacts_dir / "judge.json").write_text(judged.model_dump_json(indent=1))
        return {"run_idx": run_idx, "verdict": oracle_verdict,
                "checks": {c.name: c.status for c in checks},
                "failed": [f"{c.name}: {c.evidence}" for c in checks if c.status == "fail"],
                "judge_all_yes": judged.all_yes if judged else None,
                "judge_model": judged.model if judged else None,
                "turns": transcript.agent_turns(),
                "ttfa_ms": round(per_turn_ms[0], 1) if per_turn_ms else None,
                "per_turn_ms": per_turn_ms,
                "artifacts": str(artifacts_dir)}
    finally:
        seed.cleanup(run)


async def run_scenario(path: str | Path, k: int | None = None) -> list[dict]:
    scenario = Scenario.load(path)
    trials = k or scenario.k_trials
    results = []
    for i in range(trials):
        result = await run_once(scenario, i)
        flag = "PASS" if result["verdict"] == "CONFIRMED_CORRECT" else result["verdict"]
        judge_note = ("" if result["judge_all_yes"] is None
                      else f" judge={'yes' if result['judge_all_yes'] else 'NO'}")
        print(f"  run {i}: {flag} turns={result['turns']} "
              f"ttfa={result['ttfa_ms']}ms{judge_note}")
        for line in result["failed"]:
            print(f"         FAIL {line}")
        results.append(result)
    return results


def main() -> int:
    from evals import judge as judge_mod
    path = sys.argv[1]
    k = int(sys.argv[sys.argv.index("--k") + 1]) if "--k" in sys.argv else None
    scenario = Scenario.load(path)
    print(f"{scenario.scenario_id} (channel={scenario.channel}, k={k or scenario.k_trials})")
    results = asyncio.run(run_scenario(path, k))

    oracle_ok = [r["verdict"] == "CONFIRMED_CORRECT" for r in results]
    pass_k = all(oracle_ok)
    print(f"pass^{len(results)}: {'PASS' if pass_k else 'FAIL'} "
          f"({sum(oracle_ok)}/{len(results)} runs confirmed)")
    judged = [r["judge_all_yes"] for r in results if r["judge_all_yes"] is not None]
    if judged:
        calibration = judge_mod.agreement(judged, oracle_ok[:len(judged)])
        print(f"judge-oracle agreement: {calibration['agreement_pct']}% "
              f"({calibration['stability']}) model={results[0]['judge_model']}")
    return 0 if pass_k else 1


if __name__ == "__main__":
    raise SystemExit(main())
