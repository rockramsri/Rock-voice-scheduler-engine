# Rock Scheduler — ops console

Part of [Rock Scheduler](../README.md). Run it with `npm install && npm run dev` (http://localhost:8080). Deep documentation: [architecture](../docs/architecture.md) · [deployment](../docs/deployment.md) · [design decisions](../docs/decisions.md) · [demo playbook](../docs/demo.md).

Everything below is a legacy working-context note, kept for history.

---

# Voice Shift Flow

Copy everything below the line — it's a complete re-entry context: paste it into any new chat and I (or anyone) can pick up exactly where we are.

---

# ROCK SCHEDULER — FULL PROJECT CONTEXT (handoff, Aug 2 2026)

## What this is

**Rock Scheduler** (`~/Documents/Voice agent- for health care/Rock-scheduler-voice-agent/`) is a voice-AI shift-scheduling platform for home health care agencies. Nurses call a real phone number, an AI front desk handles callouts, and a worker automatically backfills the shift: scores replacement nurses, texts → WhatsApps → calls them one by one (respecting per-nurse channel preferences and 6am–10pm quiet hours), first YES wins atomically, everything audited. A separate branched project (**All-Chain-admin / PulseOS**, own chat, own repo github.com/rockramsri/All-Chain-admin) extends a copy of this for demos + vendor procurement — **both currently share the SAME Supabase database** (caution: their demos overwrite each other's data; split projects when it matters). Rule from the owner: **never git commit/push — the owner does it manually**. Supabase MCP is read-only by rule; schema changes go through psql. Code style: simple, short files, module docstrings, guarded updates.

## Live infrastructure

- **LiveKit Cloud**: project `arya-hack` (`wss://arya-hack-dxngsucz.livekit.cloud`). SIP: inbound trunk `rock-inbound` (ST_XW4Qu3b4dNj7) for **+1 (929) 730-7867**, outbound trunk `rock-outbound` (ST_R9RHnytR7KKc), dispatch rule `rock-dispatch` → agent **`rock-agent`** → rooms `call-*`.
- **Twilio**: Full (paid) account AC6c11...; the number is voice+SMS. **Outbound US SMS blocked by A2P 10DLC (error 30034, unregistered)** — registration not started (brand: minutes w/ EIN; campaign review ~10–15 business days). **WhatsApp sandbox NOT activated** (needs one-time console visit + `join <code>` to +1 415 523 8886). **TextBelt** wired as instant no-A2P SMS but free key is US-blocked — needs paid key in `.env` `TEXTBELT_KEY`. **Voice calls work fine** (unaffected by A2P).
- **Supabase**: project `Rock-Scheduler` (`xzcpacifagkkxlplocgu`, us-east-1, in "Sriram-Madhiyalagan's Org"). Everything (LiveKit, Twilio, Supabase URL/service key, DB password) lives in the repo's `.env` (self-contained; OpenAI key falls back to sibling `.env`s).
- **Engines** (swap = `ENGINE_PROFILE` in `.env`, restart): `cascade` (Deepgram STT + gpt-4.1-mini + Cartesia TTS via LiveKit Inference — current default), `realtime` (OpenAI s2s, `gpt-realtime-mini`), `gemma_phi` (stub — future fully-local: Ollama gemma4:e4b + speaches whisper + kokoro; validated feasible on M3 16GB+).

## Repo layout

```
voice/      engines (realtime|cascade|gemma_phi stub), FrontDesk agent, OfferAgent,
            entry.py (dispatch metadata {"role":"offer","offer_id"} builds OfferAgent)
workplane/  facade tools (find_nurse, get_shift, report_callout), matching agent
            (pydantic-ai), sms_agent, offers.py (shared accept/decline + lock)
workers/    dispatch_worker.py (claim→burst→checkpoint→release loop),
            ladder.py (lead-time plans + quiet hours), scoring.py (weighted sum),
            rungs.py (message/voice rung execution, preference filtering, 555-fake guard)
channels/   telephony.py (SIP status/provision), outbound.py (calls+metadata),
            sms.py (Twilio SMS / WhatsApp / TextBelt), webhook.py (:8787, YES/NO
            fast-path then LLM reply), cli.py (status|call|sms|whatsapp|textbelt|serve|link-sms)
data/       schema.sql, dashboard.sql, db.py (ALL Postgres access, guarded updates),
            seed.py (--me +1XXX puts your phone on James Okafor)
dashboard/  Vite+React ops UI (independent; talks only to Supabase)
```

## Data model (6 tables; the shifts table IS the queue — no pgmq)

- `agencies` (quiet hours 6–22, urgent<5h/relaxed≥24h thresholds, tz) · `nurses` (phone UNIQUE = caller-ID key, specialties/areas arrays, `preferences.channels` obeyed by ladder, avatar_url) · `patients` · `shifts` (status machine: scheduled→callout→offers_out→filled/escalated; callout_* fields; `rung`, `next_action_at` = worker poll target; `claimed_by/at` stale >3min reclaimable; **EXCLUDE gist constraint = double-booking impossible**) · `offers` (UNIQUE(shift,nurse); state scored→messaged→calling→accepted/declined/no_answer; per-offer `rung` tick BEFORE send = no duplicate outreach) · `events` (append-only audit; status-change trigger writes it + pg_notify).
- SQL functions: `claim_shifts(worker, limit)` (SKIP LOCKED), `lock_shift(shift, nurse)` (atomic first-YES-wins), `ff_shifts()` (demo fast-forward; the ONLY anon mutation on shifts).
- Ladder: ≥24h RELAXED (sms →1h re-sms →5h whatsapp → calls in window) · 5–24h NORMAL · ≤5h URGENT (sms+wa now →10m calls). Decliners pruned forever; voice = one prospect per visit; fake `555` numbers never dialed/texted (demo-safe).

## Example scenario — exactly what happens when Fatima calls

Seeded world: Rockram Home Health Care, 10 nurses (555 fakes), Mrs. Chen (Jersey City, wound care, tomorrow 8a–4p, Maria assigned) and Robert Rivera (Hoboken, wound care, +4h, **Fatima** assigned).

1. Fatima dials +1 929 730-7867 → Twilio SIP → LiveKit `rock-dispatch` → room `call-*` → FrontDesk answers on the current engine.
2. "It's Fatima — I'm sick, can't make today's shift." Agent confirms shift out loud → `report_callout` tool → `shifts`: nurse_id=NULL, status=callout, next_action_at=now; `callouts` fields set; call ends ~45s.
3. Worker (2s poll) claims it → lead 4h → **URGENT** plan → scores: hard filters drop Fatima (caller), Tom (unlicensed), overlapping/busy nurses → James .77, Maria .57 → `offers` rows → status offers_out.
4. Rung 1: SMS+WhatsApp to both (per-offer rung tick first; channels filtered by each nurse's preferences) → `next_action_at=+10min`, claim released (worker never sleeps holding a shift).
5. **Best case**: James texts YES → webhook strict-parse → `lock_shift()` wins → shift filled, offer accepted, Maria's late YES would get "just filled, thanks"; confirmation SMS back. Dashboard graph turns his ring green → green check node.
6. **Worst case** (nobody replies): +10min → voice rung: OfferAgent (scope-locked: ONLY accept_this_shift/decline_this_shift tools, injection-proof) calls James… no answer → 3min → Maria… no answer → prospects exhausted → status **escalated**, event logged (coordinator dial-out = TODO). Quiet-hours: urgent+night → escalate immediately; relaxed → calls wait for 6am.

## Ops dashboard (dashboard/, http://localhost:5173)

Independent Vite+React SPA using Supabase anon key + RLS policies (`data/dashboard.sql`) + Realtime. Left: register **workflows** (real numbers → nurse profiles typed or mock-injected, per-nurse channel chips; upserts nurses by phone). Right top: live story graph (react-flow): round avatar/icon nodes, colored state rings, hover glass detail cards, smoothstep staggered lineage edges, zoom/minimap; follows newest story, click event to pin, "back to live". Right bottom: raised expandable event cards with filters **this story / live / all** (defaults scoped, starts clean). Header **fast-forward button** → `ff_shifts()` RPC. Current look: light glassmorphism per Synergy-Codes-style references. **Owner verdict: still not fully what they expect — keep iterating on smoothness/cleanliness of the graph (reference: white lineage diagrams with tidy non-crossing lines, minimal round nodes, growing animation).**

## Run commands

```
cd Rock-scheduler-voice-agent && source .venv/bin/activate
python -m workers.dispatch_worker          # scheduler
python -m voice.entry dev                  # FrontDesk + OfferAgent (rock-agent)
python -m channels.cli serve               # SMS/WA webhook :8787 (YES/NO)
cd dashboard && npm run dev                # ops UI :5173
python -m channels.cli status              # SIP sanity: should say "ok: dispatch targets rock-agent"
python -m data.seed [--me +1XXXXXXXXXX]    # seed; --me makes offer calls ring YOU
# demo reset (offers+shifts wiped, nurses kept):
python - <<'EOF'
from data.db import client
sb=client(); Z="00000000-0000-0000-0000-000000000000"
sb.table("offers").delete().neq("id",Z).execute(); sb.table("shifts").delete().neq("id",Z).execute()
EOF
python -m data.seed
# trigger callout without a phone call:
python - <<'EOF'
import asyncio; from data import db; from data.db import client
async def go():
    s=client().table("shifts").select("*").execute().data[0]
    await db.record_callout(s["id"], s["nurse_id"], "flu")
asyncio.run(go())
EOF
# skip ladder waits: dashboard FF button, or:
psql "$DB_URL" \
  -c "UPDATE shifts SET next_action_at=now() WHERE status IN ('callout','offers_out');"
```

## Verified working (tested end-to-end)

Both voice engines with identical tools · inbound/outbound SIP calls · full callout→scored→laddered→YES→locked→filled run against live Postgres · escalation path · quiet-hours clamp · preference filtering · dashboard realtime graph/log with both stories · anon RLS + ff RPC.


That's the whole state. Paste this back to me anytime and say which thread to pull — dashboard polish, nurse tools, the comparison harness, or the local build.

i wna tto make the first ops dasbrod better so take time and pls genrate the best image or mock fo rhte darbs show look liek growing graph and more like callign animationa dn more best ops layout for voice lineage graph

second get dartboard image that I have I wnat to each it the best its liek scrapped need more refinement so pls generate the perfect UX design foo I can give it so coding tool to make it correct

So, how to build, right? I want the nice UI, like the first one. For the second dashboard, I have to make a really good Figma kind of a mock dashboard. Use your best UI skills to do that. I can also search if you want. 

liek claymorisom and white skemorhspim thing


## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
