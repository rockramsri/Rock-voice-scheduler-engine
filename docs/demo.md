# The solo one-phone demo

A full callout-to-covered run — voice callout, SMS decline, a context-aware pay question, a live AI offer call, an atomic lock, stand-downs — performed by one person with one phone. It works because the schema deliberately allows several nurse rows to share one phone number, and conversation identity is by name ([why](decisions.md#identity-design)).

You play every role: the nurse who calls out, the prospect who declines by text, and the prospect who takes the shift on a live call.

## What you need

- The stack configured for config 2 (see [deployment](deployment.md)): LiveKit Cloud with the SIP trunk and dispatch rule wired, Supabase, Twilio number, and `AGENT_NAME` matching the dispatch rule. `python -m channels.cli status` should print `ok: dispatch targets 'rock-agent'`.
- A **paid TextBelt key** in `TEXTBELT_KEY` — the free key is capped at one message a day, and US delivery plus reply webhooks need a paid key.
- A tunnel for replies: `ngrok http 8787`, its https URL in `PUBLIC_BASE_URL`. Without it, your YES/NO texts never reach the webhook.
- Daylight, or patience: the voice rung only fires between 06:00 and 22:00 agency-local. See the caveats at the end.

## Start the stack

Four terminals:

```bash
python -m workers.dispatch_worker          # 1. the scheduler
python -m voice.entry dev                  # 2. FrontDesk + OfferAgent
python -m channels.cli serve               # 3. SMS webhook on :8787
cd ops-console && npm run dev              # 4. console on http://localhost:8080
```

Keep the console visible on a second screen. Everything below appears there live — no refreshing.

## Register the workflow — three nurses, one phone

In the console's left rail, create a workflow and add three nurses. The fastest path is the mock inject cards (Maria Alvarez, James Okafor, Fatima Diallo — all wound care, so they compete for the same shifts), then type **your real phone number in E.164 on all three**. Duplicate phones are allowed on purpose; the validator only insists on E.164 and distinct names.

Notice the channel-preference chips on each card — sms, whatsapp, voice. The outreach ladder obeys them, so leave all three on for the full show.

Saving does three things: upserts the nurse rows, saves the workflow card, and seeds a `scheduled` shift for every nurse who lacks one. Today-nurses get staggered non-overlapping blocks, because the scorer excludes anyone already booked during the callout window — overlapping demo shifts would leave a callout with zero prospects.

If you seeded the demo world earlier (`python -m data.seed`), the ten 555-number nurses are also in the roster. Good: they show up as extra prospects in the graph, their sends are marked `skipped_fake_number`, and they make the final stand-down wave visible. Fake numbers are never actually dialed or texted.

## Act 1 — the callout call

Call the agency line (the reference deployment answers on +1 929 730-7867) from your phone. Rock answers on whatever `ENGINE_PROFILE` is set.

Your number backs three roster names, so Rock asks which of them is calling. Say "This is Maria." Then: "I'm sick — I can't make my shift." Rock confirms the shift out loud, asks briefly why, records the callout, and tells you replacement outreach has already started. Hang up. The call takes well under a minute.

On the console: Maria's puck turns callout, the outreach router appears, and within a worker poll (2 seconds) the event log shows `claim_shifts`, scoring, and the prospect lineup — James and Fatima with their match scores, plus any seeded wound-care nurses.

## Act 2 — the texts arrive, decline as one

Rung 1 fires and your phone receives the offer SMS — once per real-numbered prospect, so expect two: one for James, one for Fatima. Each says the shift, the area, and "Reply YES to take it or NO to pass."

Reply **NO**. The webhook's strict YES/NO parser resolves your phone to its most recently touched pending offer and declines it — that prospect's branch caps with "replied NO" in the graph, and the reply text thanks the right nurse by first name. Decliners are pruned forever; that nurse gets no further rungs and no stand-down later.

## Act 3 — ask what it pays

Now text a real question: **"what does it pay?"**

This does not match YES/NO, so it goes to the work-plane SMS agent. The agent's prompt carries a trusted context block built from your phone number: which nurses share it, the still-pending offer with its shift details and hourly rate, and the recent back-and-forth. It answers with the actual pay from the offer, addressed to the right nurse. Ask a follow-up — "where is it again?" — and the conversation memory (recent `sms_in`/`sms_out` events) keeps it coherent.

Both messages and both replies appear in the console's event log as `sms_in` / `sms_out`.

## Act 4 — fast-forward to the voice call, accept

The ladder now waits (10–60 minutes depending on the plan). Do not wait: press **fast-forward** in the console header. It calls the `ff_shifts` RPC, which sets `next_action_at = now()` on active shifts — it skips waits, it never invents state. The worker advances a rung on its next poll. Press it until the ladder reaches the voice rung.

Your phone rings. It is Rock again — this time the OfferAgent, dialing the best remaining prospect, one call at a time. It greets that nurse by first name, presents the shift and pay, and asks. Try to derail it — ask about other nurses, patients, anything: it politely refuses, because this agent's only tools accept or decline this one offer.

Say **yes**. The agent runs `lock_shift` — first YES wins, atomically — confirms the shift is yours, and says details will arrive by text.

## Act 5 — stand-downs and the filled story

The moment the lock lands: the shift flips to `filled`, the winning branch caps with a green check, and every still-open prospect is stood down — state change plus a courtesy "shift has been covered" text (real numbers only; the 555 nurses just flip state in the graph). The event log shows `offer_response yes`, `shift_status_changed offers_out to filled`, and one `stand_down` per loser.

That is the whole story: callout, scoring, ladder, YES, lock, stand-downs, audit — and you played all three humans.

## Console controls worth showing

- **Detailed vs normal** toggle in the story header. Detailed draws every outreach attempt as its own pip growing rightwards — sms, whatsapp, call, outcome. Normal is the classic one-puck-per-prospect view.
- **Event log filters**: this story, live, all. Scoped to the current story by default so demos start clean.
- **Fast-forward** in the header, as used above. It only skips waits; it never invents state.
- **Live / paused and back-to-live**: click any event to pin its story; return to following the newest.

## Caveats

- **Quiet hours are real.** Voice calls fire only between 06:00 and 22:00 agency-local (default `America/New_York`). At night, a relaxed shift just waits for 06:00 — and an urgent one escalates to a human instead of calling. If you must demo at night, widen `quiet_start`/`quiet_end` on the `agencies` row first (via psql), or expect the escalated ending.
- **Shared-phone YES/NO routing.** With one phone backing several prospects, a bare YES or NO applies to the most recently touched pending offer. In practice the flow above is unambiguous; if you want per-nurse precision, give the nurses different real numbers.
- **Twilio SMS stays blocked** in the US until A2P 10DLC registration clears (error 30034) — which is exactly why the demo ships on TextBelt. WhatsApp works instantly once you join the sandbox (`join <code>` texted to +1 415 523 8886) and point the sandbox inbound URL at `PUBLIC_BASE_URL/sms`.
- **The escalation ending is a feature.** Decline everything, or let calls ring out (a live call goes stale after 3 minutes, then the next prospect is dialed): when prospects are exhausted the shift lands `escalated`, with the reason in the event log. Today escalation is an audited event; the coordinator dial-out is on the roadmap.

## Reset between runs

`python -m data.seed` is idempotent and will not duplicate anything. For a truly clean slate, clear the two moving tables and re-seed:

```bash
psql "$DB_URL" -c "delete from offers; delete from shifts;"
python -m data.seed
```

Workflow-registered nurses survive (they are roster rows); saving the workflow again re-seeds their demo shifts.
