# Eval system — full context handoff

Written Aug 23, 2026, at the end of the build chat. This is the one document to
read before touching `evals/` or the ops console's Eval Lab. Everything below
was measured on this machine — no estimated numbers. Companion deep-dive:
`evals/ARCHITECTURE.md` (design + amendments log).

## 1. What exists

A layered eval harness for the Rock Scheduler voice/SMS engine, plus a web
Eval Lab inside the ops console. It grades REAL engine code (agents, worker
rungs, scoring, webhook routing) against an isolated Supabase project, with a
deterministic oracle owning verdicts and an LLM judge in a subordinate,
transcript-only role.

```
evals/
  ARCHITECTURE.md   design (approved), discrepancies D1–D11, risks
  CONTEXT.md        this file
  contracts.py      RunArtifacts, DbSnapshot, Scenario, CheckResult, EndState
  seed.py           env swap → eval DB (hard-refuses prod), namespaced seeding,
                    snapshot, cleanup; reads .env.eval OR process env
  oracle.py         9 deterministic checks + verdict aggregation
  judge.py          transcript-only LLM judge + judge-vs-oracle calibration
  scorecard.py      MetricSpec CATALOG, Metric/Scorecard/SuiteReport,
                    assemble (pass^k), diff/gate (baseline), compare (bench),
                    render (scorecard.md), promote (baseline), write_suite
  run_sms.py        SMS persona loop — mirrors channels/webhook.py exactly
  run_voice.py      L2 helpers + in-process L3 voice runner (persona ↔ OfferAgent)
  sim_gen.py        scenario.yaml → LiveKit scenarios.yaml (cloud sim lane)
  sim_entry.py      `lk agent simulate` entrypoint; rebuilds artifacts from
                    session history; oracle veto via ctx.fail
  suite.py          CLI: pytest L1/L2 → SMS → voice → scorecards → gate
  bus.py            25-line event tap; runners emit turns/tools/results
  server.py         aiohttp API for the Eval Lab (port 8321) + SSE streaming
  scenarios/        co-0001, 0002, 0003, 0006, 0014 (*.scenario.yaml = truth)
  tests/            L1 ladder/scoring/db-guards, oracle, scorecard, L2 agent
  baselines/current/  promoted green suite (gitignored; promote via UI/make)
  artifacts/        per-trial evidence + suites/<id>/ scorecard folders
ops-console/src/
  routes/evals.tsx                     the Eval Lab page (/evals)
  components/ops/evals/                ScorecardCard, ScenarioDeck, SuitePopup,
                                       TranscriptModal, LiveRun, BenchmarkForm,
                                       CompareSuites, MetricBits, cardStyle
  lib/evals-api.ts                     typed client + bearer-token helper
```

## 2. The grading model (locked decisions)

- **scenario.yaml is the single source of truth** — fixtures, persona, rubric,
  gates, budgets, expected end state (structured, machine-checkable).
- **Oracle owns verdicts.** 9 checks over DbSnapshot + RunArtifacts:
  ranking_first_contact, quiet_hours, single_winner_lock, no_double_text,
  scope_two_tools, human_fallback, turn_budget_endstate, audit_completeness,
  no_context_bleed. Gate list per scenario. A check that cannot run → verdict
  UNRESOLVED (never counts as pass).
- **pass^k**: k trials per scenario; ONE regression in k fails the scenario.
- **Judge** (default `anthropic:claude-sonnet-4-6`) reads only transcripts,
  answers the rubric yes/no with verbatim quotes. Judge flips across k or ≥2
  disagreements with the oracle → UNSTABLE → quarantined from averages.
- **Metric catalog** (`scorecard.py CATALOG`) — every number has one name and
  a role: gate (blocks merges), track (trended), compare (benchmark columns).
  New metrics get a catalog entry first so future benches compare same keys.
- Isolation: every run seeds a fresh agency (new UUIDs); cleanup deletes by
  agency. Fake 555 numbers are never dialed; nothing leaves the machine in
  SMS/voice text lanes.

## 3. Current measured state (Aug 23)

Latest full suite `20260824T000825Z` (run through the API as a regression):
**5 scenarios, pass^5 on 5/5, 0 regressions, judge-oracle agreement 100%,
zero UNSTABLE.** 66 pytest tests green. livekit-agents upgraded 1.6.7 → 1.7.0
(all plugins lockstep); expressive mode auto-enables in the cascade engine
(prod TTS routes through LiveKit Inference cartesia/sonic-3, supported).

Engine fixes that came out of eval findings this session:
- OfferAgent decline now **verbally acknowledges** saved preferences
  ("noted — no weekends going forward"); took co-0002's judge from 0%
  UNSTABLE to 100% stable. SMS agent got the same memory-aware tone and the
  saved-preference context line.
- Memory pipeline confirmed end-to-end: decline reason → learn_nurse_preference
  → scoring soft gate (avoid_dows → fallback tier) / hard gate
  (hard_avoid_dows) → exhaustion-only override call with apologetic
  OVERRIDE_BLOCK → record_override_outcome (2 declines promote soft → hard).
- `sim_entry.py` (cloud sim) no longer self-vetoes UNRESOLVED: it rebuilds
  RunArtifacts from session history so gated `scope_two_tools` can run.
  Verified `lk agent simulate`: 1 total, 1 passed.
- run_voice span capture deduped (function_call vs its output item).

## 4. Eval Lab (ops console /evals)

Two tabs + overlays, calm clay theme (pastel accents; saturated color only for
semantic status). All data from the eval server — production untouched.

- **Scorecards**: headline banner (merge ok / gate blocked), "check regression"
  button, "promote to baseline" (refuses regressing suites), current-suite
  card grid (the reference the gate compares against), suite history as
  fanned card decks → click pops a SuitePopup grid.
- **Cards**: pastel accent strip, verdict chip, pass dots, gradient bars WITH
  numbers (trials passed, judge match, turns vs budget, first answer, slowest
  turn), ⓘ hover help per metric (full name + meaning + example), all-metrics
  table with baseline delta arrows, per-card quick run + transcripts.
- **Transcripts**: persisted per trial on disk (artifacts + result + judge
  JSON per folder), served by `/api/transcripts` — chat bubbles, tool chips,
  judge answers with quotes, verdict. Works forever, not just live.
- **Benchmark**: per-run model overrides (voice LLM, SMS model, persona,
  judge) + scenario picker + k + label; compare any two suites side by side
  (`Scorecard.compare`); runs-this-session decks.
- **Live view**: SSE stream of any run — turns, tool calls, pytest stages,
  trial dots filling, verdict banner. Click dots to replay any trial.

### Server API (evals/server.py)

| Endpoint | What |
|---|---|
| GET /api/health | ok/busy/defaults/eval-db host |
| GET /api/scenarios | parsed scenario.yaml list |
| GET /api/suites, /api/suites/{id} | history; detail incl. baseline deltas + gate blocks |
| GET /api/latest | newest FULL suite (kind suite/regression only) |
| GET /api/baseline | promoted cards |
| GET /api/transcripts?suite&scenario | every trial's turns/tools/judge/verdict |
| GET /api/compare?left&right | two suites side by side |
| POST /api/runs | start {kind: scenario\|regression\|benchmark, scenarios, k, overrides} — 409 if busy |
| GET /api/runs, /api/runs/{id}, /api/runs/{id}/stream | history, detail, SSE |
| POST /api/baseline/promote | copy green suite to baselines/current |

Runs are serialized (model overrides are process-wide env; restored in
finally). Suites started via the server carry `meta.json` (kind/run_id/
overrides) so quick runs never hijack the overview.

## 5. Security posture

- Local: server binds **127.0.0.1 only** (verified LAN-refused).
- Hosted: binds 0.0.0.0 when `RAILWAY_ENVIRONMENT` or `EVALS_SERVER_HOST`
  set; honors Railway's `$PORT`. If `EVALS_API_TOKEN` is set, **all POSTs
  require `Authorization: Bearer <token>`** (verified: 401 without, works
  with; GETs stay public — they're just scorecards). The console has a small
  "api token" field in the Eval Lab header (stored in localStorage, never in
  the bundle).
- `seed.load_eval_env()` hard-refuses if the eval URL equals prod's, and
  accepts creds from `evals/.env.eval` OR process env (hosted).
- The deployed UI without `VITE_EVALS_API_URL` shows a clean "server offline"
  state — visitors can't reach your laptop.

## 6. How to run locally

```bash
# eval API (terminal 1) — http://localhost:8321
make eval-server
# console (terminal 2) — http://localhost:8080/evals
cd ops-console && npm run dev
# CLI equivalents
.venv/bin/python -m evals.suite                 # full suite + scorecard.md
make eval-one ID=co-0006 K=5                    # one SMS scenario
.venv/bin/python -m evals.run_voice evals/scenarios/co-0001-*.yaml --k 5
.venv/bin/python -m pytest -c evals/pytest.ini evals/tests/   # 66 tests
```

## 7. Deploying (UI on Vercel, eval API on Railway)

### Railway — the eval API (does the actual running; spends LLM credits)

1. Push this repo to GitHub. Railway → New Project → Deploy from GitHub repo.
2. Service settings — mostly automatic, because the repo root already carries:
   - **`.python-version`** (`3.13`) — Nixpacks picks the Python version from it.
   - **`railway.json`** — build command
     (`pip install -r requirements.txt pytest pytest-asyncio`; pytest is
     needed for the regression kind's L1/L2 stages) and start command
     (`python -m evals.server`), restart-on-failure.
   - Keep **Root directory = repo root** (`Rock-voice-scheduler-engine`) —
     the server imports workers/workplane/voice/data/shared, so the whole
     engine must be present. Do NOT point it at `evals/` alone.
3. Variables (Railway → service → Variables):

   | Variable | Value |
   |---|---|
   | EVAL_SUPABASE_URL | https://iaaztsqzoxpkqyczutzw.supabase.co (the EVAL project — never prod) |
   | EVAL_SUPABASE_SERVICE_ROLE_KEY | from evals/.env.eval |
   | OPENAI_API_KEY | generator + persona models |
   | ANTHROPIC_API_KEY | judge |
   | EVALS_API_TOKEN | any long random string — gates the run buttons |
   | JUDGE_MODEL | optional, default anthropic:claude-sonnet-4-6 |

   (`PORT` and `RAILWAY_ENVIRONMENT` are injected by Railway; the server
   auto-binds 0.0.0.0:$PORT there.)
4. Settings → Networking → **Generate Domain** → copy
   `https://<something>.up.railway.app`. Check `/api/health` returns ok.

### Vercel — the ops console UI

1. Vercel → Add New Project → import the same GitHub repo.
2. **Root Directory: `ops-console`.** Framework: Vite/TanStack Start
   (build `npm run build`; nitro auto-targets Vercel on their CI — if the
   output isn't detected, set env `NITRO_PRESET=vercel` and redeploy).
3. Environment variables (baked at build time — redeploy after changes):

   | Variable | Value |
   |---|---|
   | VITE_EVALS_API_URL | the Railway domain from step 4 above |
   | VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY | optional (safe fallbacks are baked in) |
   | VITE_AGENCY_PHONE | optional |

4. Open `https://<your-app>.vercel.app/evals` → scorecards, decks and
   transcripts are public read-only; type the `EVALS_API_TOKEN` into the
   "api token" field in the header to unlock check-regression / quick-run /
   benchmark / promote from anywhere.

Notes: one run at a time by design; a regression run ≈ 5 minutes and spends
OpenAI + Anthropic credits. The `lk agent simulate` cloud lane stays a local
lane (needs the lk CLI); everything else works hosted.

## 8. What remains (open, in priority order)

1. **M7 benchmark**: cascade vs realtime engine profiles through
   `Scorecard.compare()` — the UI compare + catalog are ready; needs the
   realtime text-mode verification run (ARCHITECTURE R4).
2. **Ladder e2e scenarios** co-0004 (double-YES race), co-0005 (quiet-hours
   defer), co-0020 — via a `run_ladder.py` with the frozen-clock seam
   (`workers.rungs.now`), per ARCHITECTURE §4.3.
3. **CI**: `evals/ci-workflow.yaml` stub exists; wire secrets
   (EVAL_SUPABASE_*, OPENAI, ANTHROPIC) and make `make eval` blocking; cloud
   sim as a non-blocking job first.
4. Baselines are promoted locally (UI button / `make baseline-promote`) but
   never git-committed — commit policy stays "only on explicit ask".

## 9. Integrity rules (unchanged, non-negotiable)

Every number reported anywhere must come from a command actually run. If it
wasn't measured, it prints MISSING — never an estimate. Evals never touch the
production database; `gemma_phi` is never evaluated; production code changes
only happen on explicit request.
