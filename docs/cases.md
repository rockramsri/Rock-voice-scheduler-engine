# Use cases — the four stories the engine tells

Each case below is a real path through the code, with the exact audit events to watch in the console's live feed. They compose: one messy afternoon can walk through all four.

## 1. The golden path — first YES wins

Maria calls out sick; the worker scores replacements, texts them, and the first YES locks the shift atomically. Everyone else is stood down politely.

```mermaid
sequenceDiagram
    autonumber
    actor Maria as Maria (callout)
    participant Rock as Rock — FrontDesk
    participant DB as Postgres
    participant W as Dispatch worker
    actor James as James (prospect)

    Maria->>Rock: "I'm sick, can't make my shift"
    Rock->>DB: report_my_callout — scheduled → callout
    Rock->>DB: EMR write-back: callout_documented
    W->>DB: claim → score → offers (continuity bonus applies)
    W->>James: SMS "Reply YES to take it or NO to pass"
    James->>DB: YES → lock_shift() — first YES wins
    DB-->>James: "Confirmed, it's yours"
    W->>DB: EMR write-back: shift_reassigned
    Note over DB: losers stood down + courtesy text
```

**Events:** `callout_recorded` → `emr_writeback` → `prospects_scored` → `offer_sent` → `offer_response yes` → `shift_status_changed offers_out→filled` → `emr_writeback` → `stand_down`.

## 2. Decline with a reason — memory is born

Fatima replies *"no, I don't do weekends"*. Not a bare NO, so the SMS agent interprets it once, declines the offer, and compiles the sentence into a rule.

```mermaid
sequenceDiagram
    autonumber
    actor Fatima as Fatima (prospect)
    participant Hook as SMS webhook
    participant Agent as SMS agent (LLM)
    participant DB as Postgres

    Fatima->>Hook: "no, I don't do weekends"
    Hook->>Agent: not a strict YES/NO → context + tools
    Agent->>DB: decline_pending_offer(reason, avoid_weekends=true)
    DB-->>DB: preferences: avoid_dows=[Sat,Sun] + memory note
    DB-->>Fatima: "Offer declined — we'll remember that"
    Note over DB: memory_learned event · next weekend callout skips her
```

**Events:** `sms_in` → `offer_response no` → `memory_learned` → (next weekend) `prospects_scored` with *"held back — learned preference"*.

## 3. The last-resort override — asking like a human

A Saturday callout where every clean prospect is exhausted. Instead of escalating, Rock makes one gentle call to a soft-preference nurse — opening with the apology, never pushing.

```mermaid
sequenceDiagram
    autonumber
    participant W as Dispatch worker
    participant DB as Postgres
    participant Agent as Rock — OfferAgent
    actor Maria as Maria (soft: no weekends)

    W->>DB: voice rung — clean prospects exhausted
    W->>DB: preference_override_ask (audited)
    W->>Agent: dial with override context
    Agent->>Maria: "I know you don't do weekends — sorry to ask, everything else fell through. No is fine."
    alt she helps out
        Maria->>Agent: "ok, just this once" → lock_shift()
        DB-->>DB: override counter resets — stays soft
    else she declines
        Maria->>Agent: "sorry, can't"
        DB-->>DB: override_outcome declined ×2 → promoted to HARD
        W->>DB: escalated — human takes over
    end
```

**Events:** `preference_override_ask` → `offer_call` → `override_outcome` → (`shift_filled` | `escalated`). Two declines auto-promote to `hard_avoid_dows` — she is never asked again. Details in [memory](memory.md).

## 4. The guards — overtime, hard preferences, escalation

The scorer refuses quietly dangerous fills and says why, out loud, in the audit feed.

```mermaid
flowchart LR
    callout["Saturday callout"] --> rank{"scoring guards"}
    rank -- "38h booked, +6h > 40h cap" --> ot["Grace skipped — overtime"]
    rank -- "hard preference: never Saturdays" --> hard["Priya skipped — hard rule"]
    rank -- "clean + fallbacks empty" --> esc["status: escalated — coordinator takes over"]
    rank -- "eligible" --> ladder["offers → SMS → WhatsApp → voice"]
```

**Events:** `prospects_scored` carries every skip note (`skipped`, `fallbacks` payload keys); a dead-end ends as `shift_status_changed → escalated` — an audited stop, never a silent one.

---

Run any of these yourself with the one-phone playbook in [demo.md](demo.md); the hero GIF at the top of the README is case 1 + 2 + 3 played by the console's built-in demo mode (regenerate it with `ops-console/scripts/demo-gif/`).
