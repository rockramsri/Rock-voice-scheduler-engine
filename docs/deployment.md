# Deployment

The deep version of the [README's "Three ways to run it"](../README.md#three-ways-to-run-it). Companions: [architecture](architecture.md), [decisions](decisions.md), [demo playbook](demo.md).

One idea makes all three configs possible: `voice/session_factory.py` is the only module that knows engine names, and `ENGINE_PROFILE` picks one adapter at startup. The agents, tools, dispatch worker, ladder, and schema are identical everywhere. You are choosing a topology, not a codebase.

## What every config shares

| Piece | Command | Notes |
| --- | --- | --- |
| Dispatch worker | `python -m workers.dispatch_worker` | Polls Postgres every `WORKER_POLL_SECONDS` (default 2). Stateless between bursts. |
| Voice worker | `python -m voice.entry dev` (or `start` in production) | Registers as `AGENT_NAME` with LiveKit; serves FrontDesk and OfferAgent. |
| SMS webhook | `python -m channels.cli serve` | aiohttp server on `SMS_WEBHOOK_PORT` (default 8787). Needs a public URL for replies. |
| Ops console | `cd ops-console && npm run dev` | Talks only to Supabase with the anon key. `http://localhost:8080` in dev. |
| Schema | `psql "$DB_URL" -f data/schema.sql` then `-f data/dashboard.sql` | Apply once per database. |

## Config 1 — Fully self-hosted, dockerized

Everything inside your VPC or on-prem host. The design goal: **the only traffic crossing the boundary is SIP signaling and PSTN audio to your telco trunk.** Topology diagram in the [README](../README.md#config-1--fully-self-hosted-dockerized).

### Component table

| Component | Software | Port (internal unless noted) |
| --- | --- | --- |
| Media server | LiveKit server, open source | ws/http 7880, rtc tcp 7881, rtc udp range |
| SIP gateway | livekit-sip, open source | **udp 5060 exposed to the telco**, plus an RTP udp range |
| Coordination | Redis (required by LiveKit + SIP) | 6379 |
| Data plane | Supabase docker stack, or plain Postgres 16 | 5432 (Kong gateway 8000 if full stack) |
| LLM | Ollama serving a Gemma-class model — e4b class for modest hardware, 12b for quality | 11434 |
| STT | speaches (faster-whisper server) | 8000 |
| TTS | Kokoro (FastAPI server) | 8880 |
| Voice worker | `rock-voice`, `ENGINE_PROFILE=gemma_phi` | none |
| Dispatch worker | `rock-worker`, 1–2 replicas | none |
| Webhook | `rock-webhook` | 8787, LAN-only unless you keep SMS |
| Console | `ops-console`, static SPA build | 8080, LAN-only or behind your SSO proxy |

### Honest status

`ENGINE_PROFILE=gemma_phi` is a **wired profile seam, not a working engine**: `voice/engines/gemma_phi.py` raises `NotImplementedError` today, and `shared/config.py` does not yet read Ollama/STT/TTS endpoint variables. Local model integration is on the roadmap. Everything else in this config — self-hosted LiveKit, self-hosted Supabase, the workers, the console — is ordinary deployment of code that already exists. The adapter is a small file: build an `AgentSession` from an OpenAI-compatible LLM client pointed at Ollama plus local STT/TTS plugins, mirroring `cascade_default.py`.

Two more honest caveats:

- **Messaging rungs are internet egress.** SMS and WhatsApp go to TextBelt and Twilio HTTPS APIs. A strict single-egress boundary means voice-only outreach until you swap in an SMS gateway you control; the ladder degrades gracefully because channels are per-nurse preferences and per-rung lists.
- **The console's live feed needs the Supabase stack** (Realtime + PostgREST), not bare Postgres. The engine itself is happy with any Postgres 16 with `btree_gist`.

### Reference docker-compose.yml

**Untested blueprint.** This sketch is a starting shape, not a tested artifact: image tags move, the repo does not ship Dockerfiles yet (the `build: .` services assume a simple `python:3.11-slim` image installing `requirements.txt`), and LiveKit/SIP configs need real keys and your RTP ranges. Treat it as the map of what talks to what.

```yaml
# REFERENCE BLUEPRINT — UNTESTED. Read the caveats above before using.
services:
  livekit:
    image: livekit/livekit-server:latest
    command: --config /etc/livekit.yaml
    volumes:
      - ./ops/livekit.yaml:/etc/livekit.yaml:ro   # keys, ws 7880, rtc ports
    depends_on: [redis]

  livekit-sip:
    image: livekit/sip:latest
    volumes:
      - ./ops/sip.yaml:/etc/sip.yaml:ro           # points at livekit + redis
    ports:
      - "5060:5060/udp"                 # THE exposed port: SIP from your telco trunk
      - "10000-10100:10000-10100/udp"   # RTP media range — size to concurrent calls
    depends_on: [livekit, redis]

  redis:
    image: redis:7-alpine

  # Data plane. For the console's realtime feed, run the official Supabase
  # docker stack (github.com/supabase/supabase, docker/) as a sibling compose
  # project and point SUPABASE_URL at its gateway. The engine alone is happy
  # with plain Postgres:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: change-me
    volumes:
      - pg-data:/var/lib/postgresql/data
      - ./data/schema.sql:/docker-entrypoint-initdb.d/01-schema.sql:ro
      - ./data/dashboard.sql:/docker-entrypoint-initdb.d/02-dashboard.sql:ro

  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama-models:/root/.ollama
    # first run: docker compose exec ollama ollama pull <your gemma tag>

  speaches-stt:
    image: ghcr.io/speaches-ai/speaches:latest-cpu   # faster-whisper server, http 8000
    volumes:
      - stt-models:/root/.cache/huggingface

  kokoro-tts:
    image: ghcr.io/remsky/kokoro-fastapi-cpu:latest  # http 8880

  rock-voice:
    build: .
    command: python -m voice.entry start
    env_file: .env.selfhosted   # ENGINE_PROFILE=gemma_phi, LIVEKIT_URL=ws://livekit:7880, ...
    depends_on: [livekit, postgres, ollama, speaches-stt, kokoro-tts]

  rock-worker:
    build: .
    command: python -m workers.dispatch_worker
    env_file: .env.selfhosted
    depends_on: [postgres]
    deploy:
      replicas: 2               # safe: claims use FOR UPDATE SKIP LOCKED

  rock-webhook:
    build: .
    command: python -m channels.cli serve
    env_file: .env.selfhosted   # :8787 — keep internal unless SMS channels stay on
    depends_on: [postgres]

  ops-console:
    build: ./ops-console        # vite build, serve static on :8080 LAN-only
    depends_on: [postgres]

volumes:
  pg-data:
  ollama-models:
  stt-models:
```

### Capacity planning

A dedicated deployment comfortably serves an agency of **roughly 1,000–2,000 nurses on one Postgres instance and 1–2 dispatch workers**. The arithmetic is forgiving: callouts are rare events per nurse, a worker burst is seconds of work, and the hot query is one partial-index poll.

Workers scale horizontally with zero coordination, because claiming uses `FOR UPDATE SKIP LOCKED` and **every wait is a row timestamp — there is no in-process state to migrate or drain.** Adding a replica is pre-allocating headroom, not re-architecting: you can raise `deploy.replicas` before a deploy and remove it after, and the only shared resource under pressure is Postgres itself. Size the RTP port range and LiveKit node for peak *concurrent calls* (the voice rung dials one prospect per shift at a time, so concurrency tracks simultaneous open shifts, not roster size).

## Config 2 — Hybrid hosted inference (current default)

`ENGINE_PROFILE=cascade`. Rooms, SIP, and optionally inference ride LiveKit Cloud; data rides Supabase cloud; the PSTN leg is a Twilio Elastic SIP trunk. Your own footprint is just the four processes, anywhere with outbound internet — a laptop is enough for a real phone demo. Topology diagram in the [README](../README.md#config-2--hybrid-hosted-inference-the-current-default).

| Component | Where | Notes |
| --- | --- | --- |
| Rooms + SIP | LiveKit Cloud | Inbound trunk + dispatch rule + outbound trunk; `python -m channels.cli status` audits them, `provision` creates them for a fresh number. |
| STT / LLM / TTS | Deepgram nova-3, OpenAI gpt-4.1-mini, Cartesia sonic-3 | Vendor plugin when its key is set; otherwise the same model through LiveKit Inference — one LiveKit key covers STT and TTS. |
| Data plane | Supabase cloud | Engine writes with the service role; console reads with the anon key. |
| PSTN | Twilio | Voice is unaffected by A2P; US SMS is TextBelt until 10DLC clears. |
| Your processes | Anywhere | Voice worker, dispatch worker, webhook (public via ngrok or a real URL), console. |

Compliance note: every vendor in this lane offers a BAA on its business or enterprise tier. Signing them, and keeping PHI out of logs you do not control, is your responsibility.

## Config 3 — Realtime speech-to-speech

`ENGINE_PROFILE=realtime`. One multimodal model — OpenAI Realtime — takes audio in and produces audio out in a shared latent space. There is no STT, no TTS, and no separate VAD or turn detector: the model owns turn-taking (`voice/engines/realtime_openai.py` configures nothing else on purpose).

**Why choose it:** the lowest latency of the three and the most natural, emotional prosody — the model hears tone, hesitation, and urgency rather than a transcript of them, which matters when a stressed nurse calls at 5am.

**The trade-off:** the highest per-minute cost and the tightest vendor coupling; the model choice and the voice are one knob (`REALTIME_MODEL`, `REALTIME_VOICE`, with `gpt-realtime-mini` as the cheap development setting).

**What does not change:** everything below the session. The same FrontDesk and OfferAgent, the same three tools, the same worker, ladder, and locks. Swapping config 2 for config 3 is one env var and a restart — that is the engine-agnostic design doing its job. Topology diagram in the [README](../README.md#config-3--realtime-speech-to-speech).

## Environment matrix

`shared/config.py` is the only module that reads the environment (start from `.env.example`). Per config:

| Variable | Config 1 self-hosted | Config 2 cascade | Config 3 realtime |
| --- | --- | --- | --- |
| `ENGINE_PROFILE` | `gemma_phi` (stub today) | `cascade` | `realtime` |
| `LIVEKIT_URL` | `ws://livekit:7880` (your server) | LiveKit Cloud `wss://` | LiveKit Cloud `wss://` |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | self-issued in `livekit.yaml` | cloud project keys | cloud project keys |
| `OPENAI_API_KEY` | not used (local LLM planned) | required — cascade LLM + work plane | required — realtime + work plane |
| `DEEPGRAM_API_KEY` / `CARTESIA_API_KEY` | not used | optional; empty routes via LiveKit Inference | not used |
| `LLM_MODEL` | n/a until the engine lands | `gpt-4.1-mini` default | n/a |
| `REALTIME_MODEL` / `REALTIME_VOICE` | n/a | n/a | `gpt-realtime` / `marin` (mini for dev) |
| `WORKPLANE_MODEL` | local model planned | `openai:gpt-4.1-mini` | `openai:gpt-4.1-mini` |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | your self-hosted stack | Supabase cloud | Supabase cloud |
| `AGENT_NAME` | `rock-agent` — must match the dispatch rule | same | same |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_PHONE_NUMBER` | your SIP provider's equivalents | required | required |
| `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` | trunk on your livekit-sip | cloud trunk id | cloud trunk id |
| `TEXTBELT_KEY` / `PUBLIC_BASE_URL` / `TWILIO_WHATSAPP_FROM` | only if you accept messaging egress | paid TextBelt key + ngrok URL | same as config 2 |
| `WORKER_POLL_SECONDS` / `SMS_WEBHOOK_PORT` | defaults `2` / `8787` everywhere | same | same |

Planned-but-not-implemented (listed so nobody hunts for them): Ollama, speaches, and Kokoro endpoint variables for `gemma_phi`. They do not exist in `shared/config.py` yet and will arrive with the engine adapter.

One quirk worth knowing: `shared/config.py` also falls back to two sibling `.env` files (`../Livekit-agents`, `../s2s-experiment`) for `OPENAI_API_KEY` only. Standalone checkouts should just set the key in `.env`.

## Choosing

| | Config 1 self-hosted | Config 2 cascade | Config 3 realtime |
| --- | --- | --- | --- |
| Data boundary | everything in your VPC; SIP audio is the only egress by design | PHI transits BAA-covered vendors | PHI transits BAA-covered vendors |
| Latency | local inference, no vendor round-trips | good — parallel pipelined stages | best — one model, no pipeline |
| Prosody | depends on local TTS | good | most natural and emotional |
| Cost shape | hardware capex, near-zero marginal | per-request vendor pricing | highest per-minute |
| Ops burden | highest — you run media, models, and data | lowest | low |
| Status | topology ready; engine profile is a stub seam | **default, tested end-to-end** | tested end-to-end |

Start on config 2. Flip to config 3 when call feel matters more than cost. Move to config 1 when a compliance boundary demands it — the schema, agents, and worker come with you unchanged.
