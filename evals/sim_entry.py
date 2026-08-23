"""LiveKit `lk agent simulate` entrypoint — OfferAgent + eval-DB seed + oracle veto.

Run from the repo root:
  lk agent simulate evals/sim_entry.py --scenarios evals/artifacts/lk-scenarios.yaml

This file is never imported by production. The CLI starts it as a temporary
local worker. Seeding uses the isolated eval project (load_eval_env first).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals import seed
seed.load_eval_env()

from livekit.agents import AgentServer, JobContext, SimulationContext, cli  # noqa: E402

from evals.contracts import (CallTranscript, RunArtifacts, Scenario, Span,  # noqa: E402
                             Turn)
from evals.run_voice import build_text_llm, seed_offer_world  # noqa: E402
from evals.seed import ARTIFACTS_DIR, EVALS_DIR  # noqa: E402

_runs: dict[str, dict] = {}
server = AgentServer()


def _scenario(scenario_id: str) -> Scenario:
    matches = list((EVALS_DIR / "scenarios").glob(f"{scenario_id}*.scenario.yaml"))
    if not matches:
        raise FileNotFoundError(f"no scenario file for {scenario_id}")
    return Scenario.load(matches[0])


def _artifacts_from_session(session, scenario: Scenario, entry: dict,
                            run_idx: int) -> RunArtifacts:
    """Rebuild transcript + tool spans from the session history (sim lane)."""
    from uuid import uuid4

    transcript = CallTranscript(prospect_id=entry["prospect"], channel="voice",
                                agent_instructions=entry["instructions"])
    spans: list[Span] = []
    for item in session.history.items:
        kind = getattr(item, "type", None)
        if kind == "function_call":
            spans.append(Span(span_id=uuid4().hex[:8], agent="offer_agent",
                              tool=getattr(item, "name", None)))
        elif kind == "message" and getattr(item, "role", None) in ("user", "assistant"):
            text = getattr(item, "text_content", None) or ""
            if text:
                role = "agent" if item.role == "assistant" else "user"
                transcript.turns.append(Turn(role=role, text=str(text)))
    return RunArtifacts(scenario_id=scenario.scenario_id, run_idx=run_idx,
                        transcripts=[transcript], spans=spans)


async def on_simulation_end(ctx: SimulationContext) -> None:
    from datetime import UTC, datetime

    from evals import oracle
    from evals.run_voice import _after_call

    data = ctx.userdata()
    run_idx = data.get("run_idx", 0)
    key = f"{data.get('scenario_id')}:{run_idx}"
    entry = _runs.pop(key, None)
    if entry is None:
        ctx.fail("eval run handle missing — seed never ran")
        return
    run = entry["run"]
    scenario = _scenario(data["scenario_id"])
    agency = seed.client().table("agencies").select("*").eq(
        "id", run.agency_id).limit(1).execute().data[0]
    if run.shift_ids:
        await _after_call(run.shift_ids[0], agency)
    session = getattr(ctx.job_context, "primary_session", None)
    artifacts = (_artifacts_from_session(session, scenario, entry, run_idx)
                 if session else None)
    out_dir = (ARTIFACTS_DIR / scenario.scenario_id /
               f"{datetime.now(UTC):%Y%m%dT%H%M%S}-sim{run_idx}")
    snap = seed.snapshot(run, save_to=out_dir / "snapshot.json")
    if artifacts:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "artifacts.json").write_text(artifacts.model_dump_json(indent=1))
    checks = oracle.run_oracle(snap, scenario, artifacts)
    verdict = oracle.verdict(checks, scenario.gates)
    failed = [f"{c.name}: {c.evidence}" for c in checks if c.status == "fail"]
    unresolved = [c.name for c in checks
                  if c.name in scenario.gates and c.status == "skip"]
    seed.cleanup(run)
    if verdict != "CONFIRMED_CORRECT":
        detail = "; ".join(failed) or f"gates skipped: {', '.join(unresolved)}"
        ctx.fail(f"{verdict}: {detail} (evidence: {out_dir})")


@server.rtc_session(agent_name="", on_simulation_end=on_simulation_end)
async def entrypoint(ctx: JobContext) -> None:
    from livekit.agents import AgentSession

    from voice.agents.offer_agent import build_offer_agent

    await ctx.connect()
    sim = ctx.simulation_context()
    if sim is None:
        return   # production path never uses this file
    data = sim.userdata()
    scenario = _scenario(data["scenario_id"])
    run, offer = await seed_offer_world(scenario)
    agent = build_offer_agent(offer)
    _runs[f"{data['scenario_id']}:{data.get('run_idx', 0)}"] = {
        "run": run, "instructions": agent.instructions,
        "prospect": (scenario.expected_rank_order[0]
                     if scenario.expected_rank_order else "CG-101"),
    }
    first = offer["nurses"]["name"].split()[0]
    session = AgentSession(llm=build_text_llm())
    await session.start(agent=agent, room=ctx.room, record=False)
    await session.generate_reply(
        instructions=(f"Greet {first} by name, say you are Rock calling from "
                      "Rockram Home Health Care about an open shift, and present it."))


if __name__ == "__main__":
    cli.run_app(server)
