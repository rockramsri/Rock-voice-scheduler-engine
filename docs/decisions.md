# Design decisions

The "why" behind Rock Scheduler, grounded in the commented schema (`data/schema.sql`) and the code. Companions: [architecture](architecture.md) for the what, [deployment](deployment.md) for the where, the [README](../README.md) for the overview.

## Why Supabase Postgres

The whole system coordinates through one Postgres database, and Supabase was chosen because it adds exactly the four things this design needs without changing what Postgres is:

- **Realtime is the console's entire backend.** The status-change trigger plus the `supabase_realtime` publication mean the ops console subscribes to row changes and redraws. No websocket server, no event bus, no API layer between the engine and the UI. This is what makes "the UI is a window" literally true.
- **RLS splits the two trust levels cleanly.** The engine writes with the service role, which bypasses RLS. The console uses the anon key, which can only do what `data/dashboard.sql` policies allow: read everything, manage nurses and workflows, and call exactly two RPCs (`ff_shifts`, `sync_demo_shifts`). The anon key can never touch an offer state or lock a shift.
- **The hard guarantees are Postgres guarantees.** The exclusion constraint, `FOR UPDATE SKIP LOCKED`, and plpgsql functions are plain Postgres. Nothing here is Supabase-proprietary.
- **Which is why config 1 works.** Supabase ships an official docker stack, so the same schema, policies, and realtime feed run self-hosted inside your boundary. Worst case, the engine runs on any vanilla Postgres — only the console's live feed needs the Supabase layer. See [deployment](deployment.md).

## Why so few tables

Six domain tables plus one console table, on purpose. Each one is a distinct answer to a distinct question, and nothing else exists:

- **`shifts` is the single contested row.** One row is simultaneously the calendar fact (who works when, for whom), the callout record (`callout_nurse_id`, `callout_reason`, `callout_at`), the scheduler checkpoint (`status`, `rung`, `next_action_at`, `claimed_by`), and the lock target (`nurse_id` NULL means open seat). Every race in the system — worker pickup, first YES, double-booking — is a race over this one row, so Postgres row locking resolves all of them.
- **`offers` is the per-prospect scoreboard.** Current state only; history lives in events. `UNIQUE(shift_id, nurse_id)` means rescoring after a crash upserts into the same rows — retries can never create a second offer and therefore can never double-text a nurse.
- **`events` is append-only audit.** Every actor writes to it, a trigger covers status changes, and nobody ever updates or deletes. Fat payloads (transcripts, recordings) belong in object storage; events carry URLs.
- **`nurses`, `patients`, `agencies` are world state.** Agencies carry quiet hours and ladder thresholds as *data*, not code, so per-agency policy needs no deploy.
- **`workflows` is console roster cards.** Which nurse profiles a demo or ops scenario groups together. The engine never reads it.

There is no queue table, no jobs table, no sessions table, no outbox. Their responsibilities all collapsed into columns on `shifts` and `offers`.

## The shifts table IS the queue

A callout sets `status='callout', next_action_at=now()`. Workers poll the partial index over `(next_action_at) WHERE status IN ('callout','offers_out')` and claim rows via `claim_shifts()` — an UPDATE wrapped around `SELECT ... FOR UPDATE SKIP LOCKED`. Claims go stale after 3 minutes, so a crashed worker's shifts are automatically fair game.

Why not pgmq or a broker? One sequential-ish flow per callout does not need one. The row itself is the job, the checkpoint, and the schedule: a worker does a short burst, writes `rung` and `next_action_at`, and releases. **Waits are timestamps on the row, never sleeping workers.** Any worker resumes any shift after any crash, and workers scale horizontally with zero coordination because SKIP LOCKED partitions the work for free.

## Safety lives in the database

- **`no_double_booking`** — a btree_gist exclusion constraint: no nurse can hold two overlapping shifts, enforced by storage. Code that tries gets an exclusion violation, which `lock_shift` converts into a clean `false`.
- **`lock_shift(shift, nurse)`** — first YES wins, atomically. A guarded UPDATE (`status IN ('callout','offers_out') AND nurse_id IS NULL`) plus the constraint. Two simultaneous YESes: one returns true, one returns false, and the loser is told "just filled" gracefully.
- **The audit trigger** — every status change writes an event row and fires `pg_notify`. The audit cannot be forgotten because it is not the application's job.

## The discipline rules

Two rules are enforced in `data/db.py`, the only module that talks to Postgres:

1. **Every state transition is a guarded UPDATE carrying the expected previous state.** `record_callout` requires `status='scheduled'`. `set_offer_state` requires the offer to be in a caller-supplied `from_states` list. `release_shift` refuses to overwrite a shift that got filled mid-burst. When two writers race, one matches zero rows and loses cleanly — no lost updates, no corrupted states, no exceptions.
2. **Rungs bump BEFORE sending.** `bump_offer_rung` ticks the offer's rung and only if that guarded write succeeds does the SMS go out. If the worker crashes between the tick and the send, resume skips that offer for that rung. The failure mode is one missed message, never a duplicate contact — the right trade for messages that reach humans.

## Ladder design

Lead time picks the plan, re-evaluated on every rung so a shift drifting closer automatically escalates (`workers/ladder.py`, pure functions, trivially testable):

| Plan | When | Rungs and waits |
| --- | --- | --- |
| RELAXED | 24h or more of lead | SMS, wait 60m; SMS again, wait 300m; WhatsApp, wait 120m; then voice |
| NORMAL | between 5h and 24h | SMS, wait 30m; WhatsApp, wait 120m; then voice |
| URGENT | 5h or less | SMS and WhatsApp together, wait 10m; then voice |

The thresholds (5h, 24h) and quiet hours are columns on `agencies` — data, not code. The voice rung repeats, one prospect per visit, so at most one call is live per shift at a time. Decliners are pruned forever; only silent prospects get called. **Quiet hours gate calls: none at or after 22:00, none before 06:00, agency-local.** A relaxed shift waits for the window to reopen; an urgent shift inside quiet hours escalates to a human instead, because texting someone at 3am about a 6am shift is a decision a person should make.

Each nurse also carries `preferences.channels` (editable in the console); the ladder skips any channel a nurse is not comfortable with.

## Identity design

- **Callers are resolved by phone number.** The SIP participant's number is looked up against `nurses.phone`; the match count (0, 1, many) shapes how FrontDesk greets and whether it asks for a name.
- **Phone is deliberately NOT unique.** Solo testing puts one real number on several nurses — the schema comment says so, and the console's validation explicitly allows it. This is what makes the [one-phone demo](demo.md) possible.
- **Conversation identity is by name.** Tools take roster names; offers always carry their own `nurse_id`. A shared phone can never confuse the state machine, only the greeting.

## Channel design

- **TextBelt is the primary US SMS sender.** US carriers block application SMS from unregistered local numbers (A2P 10DLC — a carrier rule, not Twilio's; Twilio returns error 30034). Brand registration is quick with an EIN, but campaign review takes around two weeks. TextBelt delivers immediately with a paid key, so `send_sms` routes through it exclusively, and replies ride TextBelt's `replyWebhookUrl` back to the webhook (HMAC-validated). The Twilio `/sms` route stays wired for the day A2P clears.
- **WhatsApp rides Twilio's sandbox** — instant two-way messaging once the recipient joins, same webhook, no code changes.
- **Voice is LiveKit SIP.** Inbound: Twilio trunk, LiveKit dispatch rule, named agent. Outbound: agent-first ordering — dispatch the agent into the room, then dial, so the callee never answers into silence.
- **Every sender returns an ok/error dict and never raises.** Messaging must not take down a live call. Fake 555 numbers are filtered by one shared guard before any provider is touched.

## Scoring design

Two scorers on purpose:

- **The worker's scorer (`workers/scoring.py`) is deterministic.** Hard filters that never bend: right specialty, license ok, active, not already booked in the window, not the nurse who called out. Then a weighted soft score — specialty 0.30, area 0.25 (same area 1.0, else 0.4), availability 0.20 (a weekly window covering the shift 1.0, else 0.3), reliability 0.15, cost 0.10 (cheaper pay level preferred). Fast, free, explainable — the `reason` string is spoken to prospects verbatim.
- **The conversational `find_nurse` tool keeps a Pydantic AI ranker**, because a spoken answer benefits from language-model judgment about "near Jersey City". Both read the same table.

Weights are module constants until real outcome data earns them a home in the `agencies` table.

## Agent security design

The OfferAgent is **scope-locked by construction**: built per call as a closure over one offer row, its only tools accept or decline that single offer. The callee is untrusted audio — a prompt injection can at most accept or decline the very offer the callee was already asked about, and both actions are guarded and audited. There is no roster tool, no patient tool, nothing else to reach. The SMS agent applies the same posture to text: untrusted message bodies travel only in the user turn, never in instructions, and the trusted context block comes from the database.

## Engine-agnostic by construction

`voice/session_factory.py` is the only module that knows engine names. Swapping OpenAI Realtime for the cascade — or eventually for the self-hosted `gemma_phi` profile — changes one env var. The agents, tools, worker, and schema do not change, which is what makes the three [deployment topologies](deployment.md) configuration rather than forks.
