"""Eval API server — the ops console's window into the harness.

  .venv/bin/python -m evals.server          # http://localhost:8321

Read endpoints serve scorecards straight from evals/artifacts + baselines.
Write endpoints start runs (one at a time — model overrides are process
env) and stream live turns/tools/verdicts over SSE via evals.bus.

This is a local testing tool: it talks ONLY to the eval Supabase project
(seed.load_eval_env refuses the prod URL) and never touches production.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals import seed  # noqa: E402

seed.load_eval_env()   # BEFORE any production import freezes SUPABASE_*

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import uuid  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

from aiohttp import web  # noqa: E402

from evals import bus  # noqa: E402
from evals.contracts import Scenario  # noqa: E402
from evals.scorecard import (Scorecard, assemble, compare, diff, git_sha,  # noqa: E402
                             load_baseline, new_suite_id, promote, write_suite)
from evals.seed import ARTIFACTS_DIR, EVALS_DIR, REPO_ROOT  # noqa: E402

PORT = int(os.getenv("EVALS_SERVER_PORT", "8321"))
PY = str(REPO_ROOT / ".venv" / "bin" / "python")
SUITES_DIR = ARTIFACTS_DIR / "suites"

PYTEST_L1 = ["evals/tests/test_l1_ladder.py", "evals/tests/test_l1_scoring.py",
             "evals/tests/test_l1_db_guards.py", "evals/tests/test_oracle.py",
             "evals/tests/test_scorecard.py"]
PYTEST_L2 = ["evals/tests/test_l2_offer_agent.py"]

# ---- run registry (in-memory; suites persist on disk) ----

RUNS: dict[str, dict] = {}          # run_id -> record (events included)
SUBSCRIBERS: dict[str, list[asyncio.Queue]] = {}
RUN_LOCK = asyncio.Lock()           # overrides are process env: one run at a time
MAX_RUNS_KEPT = 20


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _push(run_id: str, kind: str, **data) -> None:
    event = {"kind": kind, "ts": _now(), **data}
    run = RUNS.get(run_id)
    if run is not None:
        run["events"].append(event)
    for queue in SUBSCRIBERS.get(run_id, []):
        queue.put_nowait(event)


def _scenario_paths(ids: list[str] | None) -> list[Path]:
    every = sorted((EVALS_DIR / "scenarios").glob("*.scenario.yaml"))
    if not ids:
        return every
    picked = []
    for path in every:
        sid = Scenario.load(path).scenario_id
        if sid in ids or path.stem in ids:
            picked.append(path)
    return picked


# ---- model overrides (testing only; restored after every run) ----

OVERRIDABLE_ENV = {"llm_model": "LLM_MODEL", "judge_model": "JUDGE_MODEL"}


def _apply_overrides(overrides: dict) -> dict:
    """Set env + patch module constants. Returns what restore() needs."""
    from evals import run_sms, run_voice
    from workplane.agents import sms_agent

    saved = {"env": {}, "attrs": []}
    for key, env_name in OVERRIDABLE_ENV.items():
        value = overrides.get(key)
        if value:
            saved["env"][env_name] = os.environ.get(env_name)
            os.environ[env_name] = value
    persona = overrides.get("persona_model")
    if persona:
        for mod in (run_voice, run_sms):
            saved["attrs"].append((mod, "PERSONA_MODEL", mod.PERSONA_MODEL))
            mod.PERSONA_MODEL = persona
    workplane = overrides.get("workplane_model")
    if workplane:
        saved["attrs"].append((sms_agent, "WORKPLANE_MODEL", sms_agent.WORKPLANE_MODEL))
        sms_agent.WORKPLANE_MODEL = workplane
    return saved


def _restore_overrides(saved: dict) -> None:
    for env_name, old in saved["env"].items():
        if old is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = old
    for mod, attr, old in saved["attrs"]:
        setattr(mod, attr, old)


# ---- run execution ----

async def _pytest_stage(run_id: str, label: str, paths: list[str]) -> bool:
    _push(run_id, "stage", name=f"pytest {label}", status="running")
    proc = await asyncio.create_subprocess_exec(
        PY, "-m", "pytest", "-c", "evals/pytest.ini", "-q", *paths,
        cwd=str(REPO_ROOT), stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT)
    last = ""
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").rstrip()
        if line and not line.startswith(("=", "platform", "rootdir", "plugins",
                                         "configfile", "asyncio")):
            last = line
            _push(run_id, "log", stage=label, line=line)
    code = await proc.wait()
    _push(run_id, "stage", name=f"pytest {label}",
          status="passed" if code == 0 else "failed", summary=last)
    return code == 0


async def _execute(run_id: str) -> None:
    from evals import run_sms, run_voice

    run = RUNS[run_id]
    cfg = run["config"]
    saved = _apply_overrides(cfg.get("overrides") or {})
    bus.listen(lambda kind, data: _push(run_id, kind, **data))
    try:
        run["status"] = "running"
        _push(run_id, "run_status", status="running")

        if cfg["kind"] == "regression":
            if not await _pytest_stage(run_id, "L1+oracle+scorecard", PYTEST_L1):
                raise RuntimeError("L1/oracle/scorecard tests failed")
            if not await _pytest_stage(run_id, "L2 components", PYTEST_L2):
                raise RuntimeError("L2 component tests failed")

        suite_id = new_suite_id()
        sha = git_sha()
        label = (cfg.get("overrides") or {}).get("label")
        cards: list[Scorecard] = []
        for path in _scenario_paths(cfg.get("scenarios")):
            scenario = Scenario.load(path)
            k = cfg.get("k") or scenario.k_trials
            _push(run_id, "scenario_start", scenario=scenario.scenario_id,
                  channel=scenario.channel, k=k)
            runner = run_sms if scenario.channel == "sms" else run_voice
            results = await runner.run_scenario(path, k)
            card = assemble(scenario, results, suite_run_id=suite_id,
                            engine_profile=label, git=sha)
            cards.append(card)
            _push(run_id, "scenario_done", scenario=scenario.scenario_id,
                  card=json.loads(card.model_dump_json()))

        folder = write_suite(cards)
        (folder / "meta.json").write_text(json.dumps({
            "kind": cfg["kind"], "run_id": run_id, "k": cfg.get("k"),
            "overrides": cfg.get("overrides") or {},
            "scenarios": [c.scenario_id for c in cards]}))
        gate_blocks = []
        for card in cards:
            prior = load_baseline(card.scenario_id)
            if prior:
                gate_blocks += [
                    {"scenario": card.scenario_id, "metric": d.name,
                     "baseline": d.baseline, "current": d.current}
                    for d in diff(card, prior) if d.blocks]
        verdict = ("BLOCKED" if gate_blocks else
                   "REGRESSION" if any(c.deterministic.get("oracle_verdict") ==
                                       "REGRESSION" for c in cards) else "GREEN")
        run.update(status="done", suite_id=suite_id, verdict=verdict,
                   gate_blocks=gate_blocks, finished_at=_now())
        _push(run_id, "run_done", suite_id=suite_id, verdict=verdict,
              gate_blocks=gate_blocks, folder=str(folder))
    except Exception as err:  # noqa: BLE001 — surfaced to the UI, never silent
        run.update(status="error", error=str(err), finished_at=_now())
        _push(run_id, "run_error", error=str(err))
    finally:
        bus.unlisten()
        _restore_overrides(saved)
        RUN_LOCK.release()


# ---- read endpoints ----

async def health(_req: web.Request) -> web.Response:
    active = next((r["id"] for r in RUNS.values() if r["status"] == "running"), None)
    return web.json_response({
        "ok": True, "busy": active is not None, "active_run": active,
        "eval_db": os.environ.get("SUPABASE_URL", ""),
        "defaults": {"llm_model": os.getenv("LLM_MODEL", "gpt-4.1-mini"),
                     "judge_model": os.getenv("JUDGE_MODEL",
                                              "anthropic:claude-sonnet-4-6"),
                     "persona_model": "openai:gpt-4.1-mini",
                     "workplane_model": os.getenv("WORKPLANE_MODEL",
                                                  "openai:gpt-4.1-mini")},
    })


async def scenarios(_req: web.Request) -> web.Response:
    out = []
    for path in sorted((EVALS_DIR / "scenarios").glob("*.scenario.yaml")):
        sc = Scenario.load(path)
        out.append({"file": path.name, **json.loads(sc.model_dump_json())})
    return web.json_response(out)


def _suite_meta(folder: Path) -> dict:
    meta_file = folder / "meta.json"
    if meta_file.exists():
        return json.loads(meta_file.read_text())
    return {"kind": "suite"}   # legacy CLI `python -m evals.suite` folders


def _suite_summary(folder: Path) -> dict | None:
    suite_file = folder / "suite.json"
    if not suite_file.exists():
        return None
    data = json.loads(suite_file.read_text())
    cards = data.get("scorecards", [])
    meta = _suite_meta(folder)
    return {
        "suite_run_id": data.get("suite_run_id"),
        "ts": data.get("ts"), "git_sha": data.get("git_sha"),
        "engine_profile": data.get("engine_profile"),
        "headline": data.get("headline"),
        "kind": meta.get("kind", "suite"),
        "label": (meta.get("overrides") or {}).get("label"),
        "n_scenarios": len(cards),
        "regressions": sum(1 for c in cards
                           if c.get("deterministic", {}).get("oracle_verdict")
                           == "REGRESSION"),
        "pass_k": sum(1 for c in cards
                      if c.get("nondeterministic", {}).get("pass_k")),
    }


async def suites(_req: web.Request) -> web.Response:
    out = []
    if SUITES_DIR.exists():
        for folder in sorted(SUITES_DIR.iterdir(), reverse=True):
            summary = _suite_summary(folder)
            if summary:
                out.append(summary)
    return web.json_response(out)


def _suite_detail(folder: Path) -> dict | None:
    suite_file = folder / "suite.json"
    if not suite_file.exists():
        return None
    data = json.loads(suite_file.read_text())
    deltas: dict[str, list[dict]] = {}
    for card_data in data.get("scorecards", []):
        card = Scorecard.model_validate(card_data)
        prior = load_baseline(card.scenario_id)
        if prior:
            deltas[card.scenario_id] = [json.loads(d.model_dump_json())
                                        for d in diff(card, prior)]
    data["baseline_deltas"] = deltas
    data["gate_blocks"] = [
        {"scenario": sid, "metric": d["name"],
         "baseline": d["baseline"], "current": d["current"]}
        for sid, ds in deltas.items() for d in ds if d["blocks"]]
    data["meta"] = _suite_meta(folder)
    return data


async def suite_detail(req: web.Request) -> web.Response:
    data = _suite_detail(SUITES_DIR / req.match_info["sid"])
    if data is None:
        return web.json_response({"error": "suite not found"}, status=404)
    return web.json_response(data)


async def latest(_req: web.Request) -> web.Response:
    """Newest FULL suite (CLI suite or regression run) — quick scenario and
    benchmark runs never hijack the overview."""
    if SUITES_DIR.exists():
        for folder in sorted(SUITES_DIR.iterdir(), reverse=True):
            if _suite_meta(folder).get("kind", "suite") not in ("suite", "regression"):
                continue
            data = _suite_detail(folder)
            if data:
                return web.json_response(data)
    return web.json_response({"error": "no suites yet"}, status=404)


async def baseline(_req: web.Request) -> web.Response:
    folder = EVALS_DIR / "baselines" / "current"
    cards = []
    if folder.exists():
        for path in sorted(folder.glob("*.json")):
            if path.name != "suite.json":
                cards.append(json.loads(path.read_text()))
    return web.json_response({"scorecards": cards})


async def compare_suites(req: web.Request) -> web.Response:
    left = _suite_detail(SUITES_DIR / req.query.get("left", ""))
    right = _suite_detail(SUITES_DIR / req.query.get("right", ""))
    if not left or not right:
        return web.json_response({"error": "left/right suite not found"}, status=404)
    left_cards = {c["scenario_id"]: Scorecard.model_validate(c)
                  for c in left["scorecards"]}
    right_cards = {c["scenario_id"]: Scorecard.model_validate(c)
                   for c in right["scorecards"]}
    rows = []
    for sid in sorted(set(left_cards) & set(right_cards)):
        deltas = compare(left_cards[sid], right_cards[sid])
        rows.append({"scenario_id": sid,
                     "deltas": [json.loads(d.model_dump_json()) for d in deltas]})
    return web.json_response({
        "left": {"suite_run_id": left["suite_run_id"],
                 "engine_profile": left["engine_profile"]},
        "right": {"suite_run_id": right["suite_run_id"],
                  "engine_profile": right["engine_profile"]},
        "scenarios": rows,
    })


# ---- write endpoints ----

async def start_run(req: web.Request) -> web.Response:
    body = await req.json()
    kind = body.get("kind", "scenario")
    if kind not in ("scenario", "regression", "benchmark"):
        return web.json_response({"error": f"unknown kind {kind!r}"}, status=400)
    if RUN_LOCK.locked():
        return web.json_response({"error": "a run is already in progress"}, status=409)
    await RUN_LOCK.acquire()   # released by _execute's finally

    run_id = uuid.uuid4().hex[:12]
    RUNS[run_id] = {"id": run_id, "kind": kind, "status": "queued",
                    "started_at": _now(), "config": {
                        "kind": kind,
                        "scenarios": body.get("scenarios"),
                        "k": body.get("k"),
                        "overrides": body.get("overrides") or {}},
                    "events": []}
    SUBSCRIBERS[run_id] = []
    while len(RUNS) > MAX_RUNS_KEPT:
        oldest = next(iter(RUNS))
        RUNS.pop(oldest)
        SUBSCRIBERS.pop(oldest, None)
    asyncio.get_event_loop().create_task(_execute(run_id))
    return web.json_response({"run_id": run_id}, status=201)


async def list_runs(_req: web.Request) -> web.Response:
    out = [{key: r[key] for key in r if key != "events"}
           for r in reversed(RUNS.values())]
    return web.json_response(out)


async def run_detail(req: web.Request) -> web.Response:
    run = RUNS.get(req.match_info["rid"])
    if run is None:
        return web.json_response({"error": "run not found"}, status=404)
    return web.json_response(run)


async def run_stream(req: web.Request) -> web.StreamResponse:
    run = RUNS.get(req.match_info["rid"])
    if run is None:
        return web.json_response({"error": "run not found"}, status=404)
    resp = web.StreamResponse(headers={
        "Content-Type": "text/event-stream", "Cache-Control": "no-cache",
        "Access-Control-Allow-Origin": "*"})
    await resp.prepare(req)

    async def send(event: dict) -> None:
        await resp.write(f"data: {json.dumps(event)}\n\n".encode())

    for event in list(run["events"]):     # catch up, then go live
        await send(event)
    if run["status"] in ("done", "error"):
        await resp.write(b"event: end\ndata: {}\n\n")
        return resp
    queue: asyncio.Queue = asyncio.Queue()
    SUBSCRIBERS[run["id"]].append(queue)
    try:
        while True:
            event = await queue.get()
            await send(event)
            if event["kind"] in ("run_done", "run_error"):
                await resp.write(b"event: end\ndata: {}\n\n")
                break
    finally:
        SUBSCRIBERS.get(run["id"], []).remove(queue)
    return resp


async def promote_baseline(req: web.Request) -> web.Response:
    body = await req.json()
    folder = SUITES_DIR / body.get("suite_id", "")
    data = _suite_summary(folder)
    if data is None:
        return web.json_response({"error": "suite not found"}, status=404)
    if data["regressions"]:
        return web.json_response(
            {"error": f"refusing: suite has {data['regressions']} regression(s)"},
            status=400)
    dest = promote(folder)
    return web.json_response({"promoted": data["suite_run_id"], "to": str(dest)})


# ---- app wiring ----

@web.middleware
async def cors(req: web.Request, handler):
    if req.method == "OPTIONS":
        resp = web.Response()
    else:
        resp = await handler(req)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def build_app() -> web.Application:
    app = web.Application(middlewares=[cors])
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/scenarios", scenarios)
    app.router.add_get("/api/suites", suites)
    app.router.add_get("/api/suites/{sid}", suite_detail)
    app.router.add_get("/api/latest", latest)
    app.router.add_get("/api/baseline", baseline)
    app.router.add_get("/api/compare", compare_suites)
    app.router.add_post("/api/runs", start_run)
    app.router.add_get("/api/runs", list_runs)
    app.router.add_get("/api/runs/{rid}", run_detail)
    app.router.add_get("/api/runs/{rid}/stream", run_stream)
    app.router.add_post("/api/baseline/promote", promote_baseline)
    app.router.add_route("OPTIONS", "/api/{tail:.*}",
                         lambda _r: web.Response())
    return app


def main() -> None:
    print(f"eval server on http://localhost:{PORT}  (eval DB only — never prod)")
    web.run_app(build_app(), port=PORT, print=None)


if __name__ == "__main__":
    main()
