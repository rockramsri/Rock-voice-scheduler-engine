# EMR/EHR integration layer — architecture (Stage 1 deliverable)

Status: awaiting approval. No implementation code exists yet; this document is the
contract for Stage 2. Companions: [architecture](architecture.md),
[decisions](decisions.md), [deployment](deployment.md).

Scope agreed in design review (2026-09-19): **FHIR depth first** — interface +
outbox, then HAPI (dev/CI target), then Medplum, then sync-in, then OpenEMR,
then the onboarding import CLI. HL7 v2, Epic read-only import, and the
proprietary drivers (AxisCare/WellSky) are **deferred but interface-ready**:
the `EmrClient` protocol, `EmrKind` event model, registry, and outbox are
driver-agnostic, so each lands later as a new driver module plus config —
zero changes to domain code or schema.

---

## 1. Locked decisions, restated

Rock's Supabase Postgres remains the sole source of truth for live scheduling
state; the agency's EHR is the source of truth for identity and the official
visit record, and Rock caches identity rows with a link to the external id.
Each agency maps to exactly one backend, configured as data on its `agencies`
row (no global backend; a `mock` default exists only so dev keeps working).
Nothing on the accept or callout hot path ever awaits a network call: every
external side effect is an `outbox` row inserted in the same database
transaction as the state change it describes, carrying **ids only** — the
drainer re-reads fresh rows at execute time, which keeps PHI out of the queue
and makes replays use current state. Every EHR write is idempotent via
conditional create keyed on a Rock identifier, then update by id, so replaying
any outbox row can never create a duplicate resource. Vendor differences live
in backend profiles (config + quirks hooks), never in domain code; the
contract test suite is the specification every backend must satisfy. Secrets
never enter the database — `agencies.emr_secret_ref` stores the NAME of an
environment variable, resolved at drain time. Outbound payloads are minimum
necessary: staff names and shift facts always; patient name/address and nurse
phone only behind per-agency flags that default off; free-text reasons never
leave Rock. Transport is plain `aiohttp`; no vendor SDKs. The console keeps
reading Supabase Realtime only — outbox activity is visible through the
`emr_writeback` events the drainer writes, no new channel.

One multi-writer caveat accepted in review: on the EHR side, concurrent
writers are last-write-wins per resource. The operating contract with an
agency is *Rock-managed shifts have one writer: Rock*. Rock's own database
stays correct regardless, because Rock never trusts the EHR for scheduling
state.

## 2. Module and file map

| Path | Responsibility |
| --- | --- |
| `workplane/emr/__init__.py` | Package facade. `post_chart_event(...)` keeps the legacy signature; now maps `action` → `EmrKind` and enqueues via `db.enqueue_emr`, returning the idempotency key. |
| `workplane/emr.py` | Thin re-export so `from workplane import emr` keeps compiling everywhere. |
| `workplane/emr/base.py` | `EmrKind`, `EmrJob`, `EmrResult`, `EmrContext`, `EmrClient` protocol, `EmrTransientError`, `EmrPermanentError`. The write entry point is `execute()`; sync-in is `pull_changes()`; discovery is `capabilities()`. |
| `workplane/emr/registry.py` | `build_client(agency) -> EmrClient`, selected by `agencies.emr_backend`. Unknown backend raises `EmrPermanentError` at drain time → dead-letter + event, so misconfiguration is visible in the console. |
| `workplane/emr/mock_driver.py` | Reproduces today's behavior (`WSK-…` record id) through the outbox so all existing evals and the deployed demo keep working with `emr_backend='mock'`. |
| `workplane/emr/fhir_driver.py` | The one FHIR R4 driver: conditional create (`If-None-Exist`), ETag read-modify-write updates, capability discovery from `/metadata`, per-kind step sequences with links stored after every step. |
| `workplane/emr/auth.py` | Auth adapters: `none` (HAPI), `bearer`, `client_credentials` (Medplum, token cached until 60 s before expiry), `oauth2_password` (OpenEMR lab only). |
| `workplane/emr/profiles/{hapi,medplum,openemr,generic}.py` | Base URL, auth kind, quirks hooks (`before_create(resource)`, `unsupported_fallback(kind, ctx)`). |
| `data/emr.sql` | Schema additions (section 4). Applied after `schema.sql` + `dashboard.sql`, same convention. |
| `data/db.py` | Only module touching Postgres. New: `enqueue_emr`, `claim_outbox`, `complete_outbox`, `fail_outbox`, `upsert_emr_link`, `emr_links_for`, `agency_by_id`, `mark_agency_synced`, `lock_shift_with_outbox`, `record_callout_with_outbox`, `upsert_nurse_from_emr`, `upsert_patient_from_emr`. Every complete/fail is a guarded UPDATE on `claimed_by`. |
| `data/fhir_sync.py` | Sync-in normalization (`{"kind","external_type","external_id","name","active","specialties","language","phone"}`) and the upsert rules (section on sync below). |
| `data/import_fhir.py` | Onboarding CLI: bulk first pull of Practitioners (+ `--patients`) through the driver's read path. `--real-phones` maps `Practitioner.telecom` → `nurses.phone`; default lab behavior stays fake 555s. |
| `workers/outbox_worker.py` | Drainer process (`python -m workers.outbox_worker`) plus `drain_outbox_once(agency_id=None)` used synchronously by evals. Also runs the pull-sync tick for agencies with `emr_sync_mode='pull'`. |
| `channels/webhook.py` | Gains `POST /emr/medplum/hook`: verify `X-Signature` (HMAC-SHA256 of raw body, TextBelt pattern), de-dupe via `webhook_receipts(provider='medplum', external_id=<id>:<versionId>)`, 200 fast, upsert as background task. |
| `shared/config.py` | New env vars (section 9 of the master prompt): `OUTBOX_POLL_SECONDS`, `OUTBOX_MAX_ATTEMPTS`, `EMR_DEFAULT_BACKEND`, `EMR_ORACLE_WINDOW_SECONDS`, `DEBUG_EMR_BODIES`, `MEDPLUM_*`, `OPENEMR_*`, `HAPI_BASE_URL`, `EMR_TEST_BACKENDS`. |
| `evals/oracle.py` | New additive check `emr_writeback_complete` (filled ⇒ `emr_writeback` kind `shift_reassigned` within `EMR_ORACLE_WINDOW_SECONDS`). Existing `audit_completeness` untouched — the drainer's event payload keeps the legacy `action` key. |
| `evals/seed.py` | `cleanup()` additionally deletes `outbox` and `emr_links` rows (new FKs) before deleting the agency. |
| `evals/tests/test_emr_mapping.py`, `test_outbox_backoff.py` | Pure tests, always on. |
| `evals/tests/test_emr_contract.py` | The spec, parametrized over `EMR_TEST_BACKENDS` (default `mock,hapi`), per-backend reachability skip within 2 s. |
| `lab/docker-compose.emr.yml`, `lab/README.md`, `lab/seed_lab.py` | Lab targets + `make lab-up / lab-down / lab-seed`. |

Callers move off the hot path:
- `workplane/offers.py:31` → `db.lock_shift_with_outbox(...)`; the inline
  `emr.post_chart_event` at lines 41–43 is deleted.
- `workplane/tools/scheduling_tools.py:122` → `db.record_callout_with_outbox(...)`;
  the inline call at 126–127 is deleted.
- `workers/rungs.py escalate()` → after `db.mark_escalated`, enqueue
  `escalated` (ids only; free-text reason stays in Rock's own event, as today).
- Stand-downs stay as they are (deferred; see section 8).

## 3. Sequences and crash points

### `callout_documented`

```
voice tool report_my_callout
  └─ db.record_callout_with_outbox(shift, nurse, reason)     ← ONE transaction
       ├─ guarded UPDATE shifts (id + status='scheduled')     [same WHERE as db.py today]
       └─ INSERT outbox (kind, ids, idempotency_key)          [conflict → no-op]
  crash before commit → nothing happened anywhere; caller retries
  crash after commit  → state + outbox row both exist, exactly once

outbox drainer (any instance, any time)
  └─ claim_outbox(worker, 10)             [SKIP LOCKED; stale claims >5 min re-claimable]
  └─ build EmrContext from FRESH rows     [agency, shift, nurse, patient, links, secret]
  └─ fhir driver executes idempotent steps, storing emr_links after EACH:
       1. ensure Organization      (If-None-Exist: ids/agency|<uuid>)
       2. ensure Practitioner      (callout nurse)
       3. ensure Patient           (name/address per agency flags)
       4. ensure Appointment       (booked, both participants)
       5. Appointment: callout nurse participant → declined, status → pending
          (GET → mutate → PUT If-Match; on 412 refetch once, retry, then transient)
       6. create Task requested    (identifier ids/task|<shift>:<callout_at compact>)
  └─ complete_outbox (guarded on claimed_by)
  └─ log_event("emr","emr_writeback", payload={action, kind, backend, attempt, external_ids})
```

Crash between steps 4 and 6: the row goes back to due after the 5-minute claim
window; the re-run's steps 1–5 are conditional no-ops (identifier hits) and
step 6 completes. Crash between driver success and `complete_outbox`: the
whole job replays; every step no-ops; `complete_outbox` lands. This is the
same replay-not-duplicate discipline as `bump_offer_rung`, inverted: for EHR
writes the failure mode is one extra (harmless, idempotent) replay, never a
missing record.

### `shift_reassigned`

Same shape via `lock_shift_with_outbox` (calls the existing `lock_shift`, so
the first-YES-wins guard is unchanged; on success inserts the outbox row in
the same transaction). Driver steps: ensure winner Practitioner → Appointment
participants swapped to winner accepted + status booked → Task completed,
businessStatus filled → Provenance. Provenance gets an identifier
(`ids/provenance` | `<shift>:<callout_at compact>`) so a replayed job cannot
write a second one — a deviation from the master prompt, which left Provenance
un-keyed (proposal, section 8).

### Retry and dead-letter

`EmrTransientError` (network, 5xx, 408, 429, ambiguous timeout) → backoff
`[30, 60, 300, 900, 3600, 3600, 3600, 3600]` s by attempt; after
`OUTBOX_MAX_ATTEMPTS` (8) → `dead_at`, event `emr_writeback_dead`.
`EmrPermanentError` (other 4xx, validation, unsupported resource, unknown
backend) → dead-letter immediately, `outcome="permanent"`. `last_error` is
truncated to 200 chars and passed through `shared.redact.scrub_text` when
`LOG_MESSAGE_CONTENT` is off. One row's exception never stops the batch.

## 4. Exact SQL (`data/emr.sql`)

Differences from the master prompt, all approved in review: the
`record_callout_with_outbox` WHERE clause matches `data/db.py:282-286` exactly
(no extra `nurse_id` guard — ownership is enforced by the caller-scoped tools,
as today); `source` columns are added to `nurses`/`patients` (the sync upsert
rules need them); `claim_outbox` takes an optional agency filter so eval runs
drain only their own namespaced world.

```sql
-- EMR/EHR integration layer. Apply once, after schema.sql and dashboard.sql:
--   psql $DB_URL -f data/emr.sql
-- Conventions preserved: comments say why, RLS on with no policies
-- (service role only), guarded UPDATEs, timestamps as checkpoints.

-- Per-agency system of record. Secrets are env-var NAMES, never values.
alter table agencies
    add column emr_backend text not null default 'mock',        -- mock | fhir (hl7v2 | axiscare | wellsky reserved)
    add column emr_base_url text,                               -- e.g. http://localhost:8080/fhir
    add column emr_auth_kind text not null default 'none',      -- none | bearer | client_credentials | oauth2_password
    add column emr_client_id text,
    add column emr_secret_ref text,                             -- NAME of the env var holding the secret
    add column emr_org_ref text,                                -- external Organization id once seeded
    add column emr_profile text not null default 'generic',     -- generic | hapi | medplum | openemr
    add column emr_sync_mode text not null default 'none',      -- none | push | pull
    add column emr_sync_interval_seconds int not null default 300,
    add column emr_last_sync_at timestamptz,
    add column emr_send_patient_name boolean not null default false,
    add column emr_send_address boolean not null default false,
    add column emr_send_nurse_phone boolean not null default false;

-- Where an identity row came from; sync-in never deletes, only deactivates.
alter table nurses  add column source text not null default 'rock';   -- rock | emr
alter table patients add column source text not null default 'rock';

-- Link table: which external id represents which Rock row on which backend.
-- One nurse maps to BOTH a Practitioner and a PractitionerRole, so
-- external_type is part of the key.
create table emr_links (
    agency_id uuid not null references agencies(id),
    rock_kind text not null,          -- agency | nurse | patient | shift | task | encounter
    rock_id uuid not null,
    external_type text not null,      -- Organization | Practitioner | PractitionerRole | Patient | Appointment | Task | Provenance
    external_id text not null,
    backend text not null,
    updated_at timestamptz not null default now(),
    primary key (agency_id, rock_kind, rock_id, external_type)
);

-- Transactional outbox: every external side effect, ids only. Inserted in the
-- same transaction as the state change (see the *_with_outbox functions).
create table outbox (
    id bigserial primary key,
    agency_id uuid not null references agencies(id),
    kind text not null,               -- EmrKind
    shift_id uuid references shifts(id),
    nurse_id uuid references nurses(id),
    patient_id uuid references patients(id),
    idempotency_key text not null unique,
    attempts int not null default 0,
    next_attempt_at timestamptz not null default now(),
    claimed_by text,
    claimed_at timestamptz,
    last_error text,                  -- PHI-free, truncated to 200 chars
    done_at timestamptz,
    dead_at timestamptz,
    created_at timestamptz not null default now()
);
create index outbox_due_idx on outbox (next_attempt_at) where done_at is null and dead_at is null;
create index outbox_shift_idx on outbox (shift_id);

-- Drainer pickup, same discipline as claim_shifts. p_agency narrows the scan
-- for eval isolation (each eval run drains only its own world).
create or replace function claim_outbox(p_worker text, p_limit int default 10,
                                        p_agency uuid default null)
returns setof outbox language sql as $$
    update outbox o
       set claimed_by = p_worker, claimed_at = now()
     where o.id in (
        select id from outbox
         where done_at is null and dead_at is null
           and next_attempt_at <= now()
           and (p_agency is null or agency_id = p_agency)
           and (claimed_at is null or claimed_at < now() - interval '5 minutes')
         order by next_attempt_at
         limit p_limit
           for update skip locked)
    returning o.*;
$$;

-- First YES wins AND the write-back intent is recorded, atomically.
-- Calls the existing lock_shift so the guard is character-identical.
create or replace function lock_shift_with_outbox(p_shift uuid, p_nurse uuid)
returns boolean language plpgsql as $$
declare v_agency uuid; v_patient uuid; v_callout_at timestamptz;
begin
    if not lock_shift(p_shift, p_nurse) then return false; end if;
    select agency_id, patient_id, callout_at into v_agency, v_patient, v_callout_at
      from shifts where id = p_shift;
    insert into outbox (agency_id, kind, shift_id, nurse_id, patient_id, idempotency_key)
    values (v_agency, 'shift_reassigned', p_shift, p_nurse, v_patient,
            'shift_reassigned:' || p_shift || ':' ||
            coalesce(to_char(v_callout_at, 'YYYYMMDDHH24MISS'), 'none'))
    on conflict (idempotency_key) do nothing;
    return true;
end;
$$;

-- scheduled -> callout + outbox row, one transaction. The UPDATE matches
-- data/db.py record_callout exactly: guard on id + status only, and the same
-- column writes (nurse_id cleared, callout_* stamped, worker woken).
create or replace function record_callout_with_outbox(p_shift uuid, p_nurse uuid, p_reason text)
returns boolean language plpgsql as $$
declare v_agency uuid; v_patient uuid;
begin
    update shifts
       set status = 'callout', nurse_id = null, callout_nurse_id = p_nurse,
           callout_reason = p_reason, callout_at = now(), next_action_at = now()
     where id = p_shift and status = 'scheduled';
    if not found then return false; end if;
    select agency_id, patient_id into v_agency, v_patient from shifts where id = p_shift;
    insert into outbox (agency_id, kind, shift_id, nurse_id, patient_id, idempotency_key)
    values (v_agency, 'callout_documented', p_shift, p_nurse, v_patient,
            'callout_documented:' || p_shift || ':' || to_char(now(), 'YYYYMMDDHH24MISS'))
    on conflict (idempotency_key) do nothing;
    return true;
end;
$$;

-- Generic enqueue for the facade, escalation, and future cancel paths.
-- Returns true when inserted; a duplicate key returns NULL (no row), which
-- data/db.py treats as success — enqueued-or-already-enqueued are the same.
create or replace function enqueue_emr(p_agency uuid, p_kind text, p_shift uuid,
                                       p_nurse uuid, p_patient uuid, p_key text)
returns boolean language sql as $$
    insert into outbox (agency_id, kind, shift_id, nurse_id, patient_id, idempotency_key)
    values (p_agency, p_kind, p_shift, p_nurse, p_patient, p_key)
    on conflict (idempotency_key) do nothing
    returning true;
$$;

alter table emr_links enable row level security;
alter table outbox enable row level security;
```

Migration notes (for `docs/deployment.md`): applied to the **eval** Supabase
project by the agent via the Supabase MCP at M1; applied to the **main** demo
project manually by the operator (SQL editor or psql) on explicit approval.
`evals/seed.py cleanup()` gains `outbox` + `emr_links` deletes ahead of the
agency delete, or the new FKs abort cleanup.

## 5. Backend profile table

Columns marked MISSING are measured at lab bring-up (`GET /metadata`) and
filled in then; everything else is verified against current official docs
(2026-09-19).

| | `mock` | `hapi` | `medplum` | `openemr` |
| --- | --- | --- | --- | --- |
| Image / source | in-process | `hapiproject/hapi:v8.10.0-3` (latest) | upstream `docker-compose.full-stack.yml` (`medplum/medplum-server:latest` + app + postgres + redis) | `openemr/openemr:8.2.0` + `mariadb:11.8` |
| FHIR base | — | `http://localhost:8080/fhir` | `http://localhost:8103/fhir/R4` | `https://localhost:9300/apis/default/fhir` (container 443→9300; SSL required for OAuth2) |
| Auth | none | none | `client_credentials` at `http://localhost:8103/oauth2/token`; ClientApplication created in the app (`:3000`); token cached until 60 s before `expires_in` | OAuth2 at `{site}/oauth2/default`: dynamic registration `POST /oauth2/default/registration`, token `POST /oauth2/default/token`; scopes `user/Patient.cruds user/Practitioner.cruds user/Organization.cruds api:oemr api:fhir` (SMART v2 granular); password grant lab-only behind Globals toggle "Enable OAuth2 Password Grant (Not considered secure)"; registered client must be enabled at Administration→System→API Clients |
| Writes | all (fake) | full CRUD; conditional create via `If-None-Exist` supported by the JPA server | full CRUD; conditional create supported | **FHIR writes: Patient, Practitioner, Organization only** (write-support PR #11507 was closed unmerged; epic #9076 still open) |
| Sync | none | pull (`_lastUpdated`) | **push**: Subscription rest-hook, `channel.endpoint = <PUBLIC_BASE_URL>/emr/medplum/hook`, secret in extension `https://www.medplum.com/fhir/StructureDefinition/subscription-secret`, signature = HMAC-SHA256 hex of the **raw body** in `X-Signature`; `X-Medplum-Interaction` header carries create/update/delete; delete bodies are `{}` | pull (`_lastUpdated`) |
| `/metadata` resources | n/a | MISSING | MISSING | MISSING |
| Fallbacks | — | none expected | none expected | Appointment create/update via the standard REST API (`/apis/default/api/patient/{pid}/appointment`), recorded in `emr_links` as `external_type='Appointment'`; `Task` unsupported → open seat represented as the Appointment's status (`pending` while backfilling, `booked` when filled); `Provenance` write unsupported → skipped with an `emr_unsupported` event |
| Enable steps | — | none | first run: create project + ClientApplication, put id/secret in `.env.lab` | Administration→Globals→Connectors: "Enable OpenEMR Standard REST API", the FHIR API toggle (exact label confirmed at bring-up), and "Site Address (required for OAuth2 and FHIR)" |

Lab agencies (seeded behind `python -m data.seed --lab`): "Rockram Home
Health Care A" on `medplum`, "B" on `openemr`, both with
`emr_send_patient_name = true` and `emr_send_address = true` (fictional
patients; fuller-looking charts for demos). `emr_send_nurse_phone` stays false
everywhere — Rock does the dialing; the EHR has no use for the number. Schema
defaults for all three flags remain false; the deployed demo agency stays
all-off on `mock`.

## 6. VERIFY results (checked 2026-09-19)

| # | Claim in the master prompt | Verdict |
| --- | --- | --- |
| 1 | Medplum ports 8103/3000, token `/oauth2/token`, client_credentials | **Confirmed** via medplum.com docs + upstream `docker-compose.full-stack.yml`. Project isolation: resources are project-scoped; lab uses one project (one lab agency per project if a second is ever needed). |
| 2 | Medplum Subscription signature "extension + header, VERIFY names" | **Confirmed**: extension `https://www.medplum.com/fhir/StructureDefinition/subscription-secret`, header `X-Signature`, HMAC-SHA256 hex over the raw POST body (server source: `buildRestHookHeaders`). Delete interactions sign the literal body `{}`. |
| 3 | OpenEMR "some FHIR resources read-only; Appointment via REST API; Task likely unsupported" | **Confirmed and sharpened**: writes exist for exactly Patient/Practitioner/Organization (POST+PUT). Appointment FHIR write support was proposed in PR #11507 (POST-only) but the PR is closed unmerged. Task is absent. The quirks profile is designed for the confirmed state; `capabilities()` reads `/metadata` at runtime, so if a newer image ships writes, the driver uses them without code changes. |
| 4 | OpenEMR image tag "7.x or 8.x, VERIFY" | Current production tag is **8.2.0** (7.0.4 still published). Lab pins 8.2.0. Container listens on 80/443; compose maps 8300:80, 9300:443. Env: `MYSQL_HOST`, `MYSQL_ROOT_PASS` required; `MYSQL_USER`, `MYSQL_PASS`, `OE_USER`, `OE_PASS` optional. |
| 5 | OpenEMR OAuth registration/scopes | **Confirmed**: `POST {site}/oauth2/default/registration` (returns client_id + registration_access_token), token `{site}/oauth2/default/token`, SMART v2 granular scopes (`user/Patient.cruds`), v1 `.read/.write` still accepted. |
| 6 | HAPI image + conditional create | **Confirmed**: `hapiproject/hapi` current `v8.10.0-3`; JPA server honors `If-None-Exist` on POST. |
| 7 | `record_callout` WHERE clause (`db.py:280-287`) | **Differs from the prompt's draft SQL**: the real guard is `id = ? AND status = 'scheduled'` only — no `nurse_id` condition — and the update also clears `nurse_id`. The RPC in section 4 matches the real code exactly; the prompt's extra `nurse_id = p_nurse` guard was dropped. |
| 8 | Oracle/event compatibility (not flagged in the prompt, found in review) | `evals/oracle.py audit_completeness` and `evals/tests/test_oracle.py` require `emr_writeback` events with `payload.action`. The drainer keeps the `action` key alongside `backend/kind/attempt/external_ids`. |
| 9 | Synthea "jar name and flags, VERIFY" | **Changed approach**: no local Java. Lab seeding uses MITRE's pre-generated 100-patient FHIR R4 transaction bundles (synthea.mitre.org/downloads, ~36 MB); each file POSTs directly to a FHIR base. Commands documented in `lab/README.md`. |
| 10 | hl7apy, Mirth/OIE image, HL7 field positions, Epic backend services | **Moot for this build** — HL7 v2 and Epic are deferred. The VERIFY items carry over verbatim to their future milestones. |

## 7. Test plan

Pure tests (always on, no DB):
- `test_emr_mapping.py` — resource templates as pure functions from fixture
  rows; flag behavior (name/address/phone included only when the agency flags
  say so); identifier systems and values.
- `test_outbox_backoff.py` — backoff schedule, dead-letter threshold,
  transient vs permanent classification.

Contract suite `test_emr_contract.py` (DB-backed via the existing `eval_db`
fixture; parametrized over `EMR_TEST_BACKENDS`, default `mock,hapi`; each
backend fixture skips if unreachable within 2 s; each test seeds its own
namespaced agency per `evals/seed.py` and drains synchronously with
`drain_outbox_once(agency_id)`):

| # | Scenario | mock | hapi | medplum | openemr |
| --- | --- | --- | --- | --- | --- |
| 1 | `test_seed_roster` — idempotent seed: 1 Organization, N Practitioners, M Patients, 1 Appointment; re-seed creates nothing | ✓ (links only) | ✓ | ✓ | ✓ |
| 2 | `test_callout_then_fill` — Task requested→completed, participant swap, status pending→booked, one Provenance | ✓ (events) | ✓ | ✓ | ✓ with fallbacks (Appointment status transitions via REST; no Task/Provenance) |
| 3 | `test_replay_is_idempotent` — reset `done_at`, drain again, counts unchanged | ✓ | ✓ | ✓ | ✓ |
| 4 | `test_escalated` — Task on-hold | ✓ | ✓ | ✓ | unsupported → documented skip |
| 5 | `test_transient_then_success` — one 503, attempts=2, exactly one resource | ✓ | ✓ | ✓ | ✓ |
| 6 | `test_permanent_dead_letters` — 400 → `dead_at` on attempt 1 + event | ✓ | ✓ | ✓ | ✓ |
| 7 | `test_crash_resume` — inject crash after the Appointment update, restart, Task completes, no duplicate Provenance | ✓ | ✓ | ✓ | ✓ (REST path) |
| 8 | `test_sync_in` — rename propagates, phone/preferences untouched, deactivate → `active=false` | — | pull | push (simulated hook POST with real signature) | pull |
| 9 | `test_minimum_necessary` — flags-off agency; recording transport asserts no patient name/address/nurse phone/reason in any request body | ✓ | ✓ | ✓ | ✓ |
| 10 | `test_config_visible_failure` — unknown backend dead-letters + event | ✓ | n/a | n/a | n/a |

Oracle: new additive check `emr_writeback_complete` (every `filled` scenario
has an `emr_writeback` kind/action `shift_reassigned` within
`EMR_ORACLE_WINDOW_SECONDS=30` of the fill). Eval runners call
`drain_outbox_once(run.agency_id)` before `seed.snapshot(...)` — deterministic
and compatible with the frozen-`now()` pattern in `run_voice.py`.

CI: `evals/ci-workflow.yaml` gains a pure-tests job (no secrets) and a
`hapi`-only contract job (docker service, no secrets). Medplum/OpenEMR lanes
run locally via `make lab-up`.

## 8. Risks and proposals

Proposals (each marked, with reason):
1. **Provenance idempotency key** (deviation): give Provenance an identifier
   (`ids/provenance` | `<shift>:<callout_at>`) so crash-resume can't write two.
   The prompt's un-keyed Provenance fails contract scenario 7 on a strict read.
2. **Synchronous eval drain** (deviation): `drain_outbox_once(agency_id)`
   called by runners/tests instead of a background drainer task —
   deterministic, frozen-time-safe, and isolates parallel eval runs (via the
   `p_agency` filter on `claim_outbox`).
3. **Legacy `action` key kept** in drainer events — protects
   `audit_completeness`, `test_oracle.py`, and the console feed unchanged.
4. **No LISTEN/NOTIFY for the drainer** — supabase-py (PostgREST) cannot
   LISTEN; a 2 s poll mirrors `WORKER_POLL_SECONDS` and the dispatch worker.
   Revisit only if write-back latency ever matters more than simplicity.
5. **Stand-down migration to the outbox: deferred.** Texts already survive
   crashes acceptably (state-first, background task); migrating them buys
   little now and doubles M1's blast radius.
6. **`--real-phones` on the import CLI** (deviation from "phones never
   imported"): real onboarding must import phones — they're mandatory for
   outreach. Lab default remains fake 555s; after first import the field is
   Rock-owned (sync never overwrites it).
7. **pgmq cleanup covers all four mentions** (`channels/sms.py:8`,
   `channels/outbound.py:3-5`, `docs/decisions.md:30`,
   `ops-console/README.md:46`) so the final `grep -rn pgmq` gate passes
   honestly.
8. **OpenEMR runs capability-adaptive**: the profile encodes today's confirmed
   limits, but `capabilities()` from `/metadata` decides at runtime, so a
   future image with Appointment writes upgrades behavior with zero code.

Risks:
- **OpenEMR is the highest-risk milestone**: least standard, most fallbacks;
  its contract row above is the honest target, not full parity.
- **Medplum first-run setup is manual** (project + ClientApplication); scripted
  as far as its API allows, documented where not.
- **`/metadata` cells are MISSING until lab bring-up**; if a server disagrees
  with its docs, the profile adapts and the difference lands in this table.
- **Railway drainer deferred to the last milestone** (approved): until then the
  deployed demo's write-backs drain only when a local worker runs. Mitigated by
  the deployed agency staying on `mock` and the console reading events as
  before.

## 9. Milestones (Stage 2, gated, revised in review)

| # | Deliverable | Gate |
| --- | --- | --- |
| M1 | `data/emr.sql` applied (eval DB via MCP), `db.py` functions, `workplane/emr/` package + facade, mock driver, `workers/outbox_worker.py`, both callers moved, `escalate()` enqueue, oracle check, eval cleanup fix | `pytest evals/tests` output pasted; contract scenarios 2,3,5,6,7,10 on `mock`; measured callout→`emr_writeback` timing |
| M2 | FHIR driver + auth adapters + `hapi` profile; `lab/docker-compose.emr.yml` (hapi only); mapping tests | Scenarios 1–7,9,10 on `hapi`; resource counts from HAPI after a double replay |
| M3 | `medplum` profile (client_credentials, first-run notes); lab compose gains the Medplum stack | Same counts on Medplum; Task+Appointment JSON dumps with PHI fields absent |
| M4 | Sync-in: `/emr/medplum/hook` (X-Signature verify, receipts), pull tick, upsert rules, `data/fhir_sync.py` | Scenario 8: rename shows in `nurses`, phone untouched, deactivate propagates |
| M5 | `openemr` profile + quirks + REST appointment fallback; lab compose gains OpenEMR | Which scenarios pass vs documented-unsupported, with reasons |
| M6 | Onboarding: `data/import_fhir.py` (+`--real-phones`), Synthea sample load, `make lab-seed`, `data/seed.py --lab` | Import counts printed; lab seed idempotent |
| M7 | Docs (architecture/decisions/deployment/README/evals), pgmq cleanup, proprietary stubs, Railway drainer service | `grep -rn pgmq` empty; new decisions entry; Railway service live on mock |

Deferred backlog (interface-ready, no schema changes needed): HL7 v2 driver
(SIU over MLLP, OIE/Mirth lab, hl7apy decision), Epic read-only import (SMART
backend services RS384), AxisCare/WellSky partner drivers, stand-down
migration into the outbox, `encounter_start/end` EVV wiring.
