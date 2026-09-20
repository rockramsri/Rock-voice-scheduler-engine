-- EMR/EHR integration layer. Apply once, after schema.sql and dashboard.sql:
--   psql $DB_URL -f data/emr.sql
-- Conventions preserved from schema.sql: comments say why, RLS on with no
-- policies (service role only), guarded UPDATEs, timestamps as checkpoints.
--
-- Two ideas live here:
--   1. outbox — every external side effect is a row inserted in the SAME
--      transaction as the state change it describes (ids only, no PHI).
--      workers/outbox_worker.py drains it with SKIP LOCKED and retries.
--   2. emr_links — the translation dictionary between Rock uuids and the
--      EHR's ids, per agency. One nurse maps to SEVERAL external records
--      (Practitioner + PractitionerRole), so external_type is in the key.

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

create table emr_links (
    agency_id uuid not null references agencies(id),
    rock_kind text not null,          -- agency | nurse | patient | shift | task | encounter
    rock_id uuid not null,
    external_type text not null,      -- Organization | Practitioner | PractitionerRole | Patient | Appointment | Task | Provenance | record_id (mock)
    external_id text not null,
    backend text not null,
    updated_at timestamptz not null default now(),
    primary key (agency_id, rock_kind, rock_id, external_type)
);

-- Transactional outbox: ids only, never data. The drainer re-reads the live
-- rows at execute time, so replays always use fresh state and no PHI queues.
create table outbox (
    id bigserial primary key,
    agency_id uuid not null references agencies(id),
    kind text not null,               -- EmrKind (workplane/emr/base.py)
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

-- Drainer pickup, same discipline as claim_shifts: SKIP LOCKED partitions the
-- work, stale claims (>5 min) are fair game for takeover. p_agency narrows the
-- scan so eval runs drain only their own seeded world.
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

-- First YES wins AND the write-back intent is recorded, atomically. Calls the
-- existing lock_shift so the guard stays character-identical.
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
-- data/db.py record_callout exactly: guard on id + status only, same columns.
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

-- Generic enqueue for escalations, future cancels, and the legacy facade.
-- Returns true when inserted; a duplicate key returns NULL (no row), which
-- data/db.py treats the same — queued-or-already-queued are both success.
create or replace function enqueue_emr(p_agency uuid, p_kind text, p_shift uuid,
                                       p_nurse uuid, p_patient uuid, p_key text)
returns boolean language sql as $$
    insert into outbox (agency_id, kind, shift_id, nurse_id, patient_id, idempotency_key)
    values (p_agency, p_kind, p_shift, p_nurse, p_patient, p_key)
    on conflict (idempotency_key) do nothing
    returning true;
$$;

-- App writes via service role only, same posture as every other table.
alter table emr_links enable row level security;
alter table outbox enable row level security;
