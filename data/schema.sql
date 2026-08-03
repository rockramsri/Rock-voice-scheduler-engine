-- ROCK Scheduler schema. Apply once: psql $DB_URL -f data/schema.sql
-- Five domain tables + agencies. The safety rules live in the DATABASE:
-- an exclusion constraint makes double-booking impossible, claim_shifts()
-- makes worker pickup race-free, lock_shift() makes "first YES wins" atomic.

create extension if not exists btree_gist;

-- One row per agency. Quiet hours + ladder thresholds are data, not code.
create table agencies (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    timezone text not null default 'America/New_York',
    quiet_start smallint not null default 22,   -- no calls at/after 10pm
    quiet_end smallint not null default 6,      -- no calls before 6am
    urgent_lead_hours int not null default 5,
    relaxed_lead_hours int not null default 24
);

-- "WHO could work?" One row per caregiver. Phone is deliberately NOT unique:
-- solo testing puts one real number on several nurses; identification is by
-- name in conversation, and offers always carry their own nurse_id.
create table nurses (
    id uuid primary key default gen_random_uuid(),
    agency_id uuid not null references agencies(id),
    name text not null,
    phone text not null,
    specialties text[] not null default '{}',
    areas text[] not null default '{}',
    pay_level int not null default 2,
    license_ok boolean not null default true,
    reliability real not null default 0.7,
    max_hours_week int not null default 40,
    availability jsonb not null default '[]',   -- [{"dow":2,"start":"08:00","end":"16:00"}]
    active boolean not null default true
);

-- "Who RECEIVES care, where?"
create table patients (
    id uuid primary key default gen_random_uuid(),
    agency_id uuid not null references agencies(id),
    name text not null,
    area text not null,
    address text not null default '',
    care_needs text[] not null default '{}',
    language text not null default 'en',
    phone text not null default ''
);

-- THE contested row: calendar fact + callout + scheduler checkpoint + lock.
create table shifts (
    id uuid primary key default gen_random_uuid(),
    agency_id uuid not null references agencies(id),
    patient_id uuid not null references patients(id),
    nurse_id uuid references nurses(id),        -- NULL = open seat (lock target)
    specialty text not null,
    area text not null,
    starts_at timestamptz not null,
    ends_at timestamptz not null,
    pay_rate int not null default 0,
    -- scheduled | callout | offers_out | filled | escalated | cancelled | completed
    status text not null default 'scheduled',
    callout_nurse_id uuid references nurses(id),
    callout_reason text,
    callout_at timestamptz,
    rung int not null default 0,                -- last outreach rung executed
    next_action_at timestamptz,                 -- the worker polls this
    claimed_by text,
    claimed_at timestamptz,
    -- a nurse can never hold two overlapping shifts, enforced by storage
    constraint no_double_booking exclude using gist
        (nurse_id with =, tstzrange(starts_at, ends_at) with &&)
        where (nurse_id is not null)
);

-- Scoreboard: one row per shift x prospect (current state; history in events).
create table offers (
    id uuid primary key default gen_random_uuid(),
    shift_id uuid not null references shifts(id),
    nurse_id uuid not null references nurses(id),
    score real not null,
    reason text not null default '',            -- spoken by agents
    -- scored | messaged | declined | accepted | no_answer
    state text not null default 'scored',
    rung int not null default 0,                -- last rung that touched THIS offer
    last_channel text,
    last_touch_at timestamptz,
    responded_at timestamptz,
    unique (shift_id, nurse_id)                 -- retries can never double-text
);

-- Append-only audit. Fat payloads (transcripts, recordings) go to object
-- storage; events carry URLs only.
create table events (
    id bigint generated always as identity primary key,
    at timestamptz not null default now(),
    agency_id uuid,
    actor text not null,        -- frontdesk | worker | offer_agent | webhook | db
    kind text not null,         -- callout_recorded | offer_sent | shift_filled | ...
    shift_id uuid,
    nurse_id uuid,
    channel text,
    rung int,
    outcome text,
    payload jsonb not null default '{}'
);

-- The whole index budget.
create index shifts_due_idx on shifts (next_action_at)
    where status in ('callout', 'offers_out');
create index shifts_nurse_time_idx on shifts (nurse_id, starts_at);
create index offers_shift_state_idx on offers (shift_id, state);
create index events_shift_idx on events (shift_id, at);
create index events_kind_idx on events (kind, at);
create index nurses_specialties_idx on nurses using gin (specialties);

-- Worker pickup: the one query that needs FOR UPDATE SKIP LOCKED, so it
-- lives in the database. Stale claims (>3 min) are fair game for takeover.
create or replace function claim_shifts(p_worker text, p_limit int default 5)
returns setof shifts language sql as $$
    update shifts s
       set claimed_by = p_worker, claimed_at = now()
     where s.id in (
        select id from shifts
         where status in ('callout', 'offers_out')
           and (next_action_at is null or next_action_at <= now())
           and (claimed_at is null or claimed_at < now() - interval '3 minutes')
         order by starts_at
         limit p_limit
           for update skip locked)
    returning s.*;
$$;

-- First YES wins. Guarded status + the exclusion constraint both protect us;
-- an overlap with the nurse's other shifts comes back as false, not an error.
create or replace function lock_shift(p_shift uuid, p_nurse uuid)
returns boolean language plpgsql as $$
begin
    update shifts
       set nurse_id = p_nurse, status = 'filled',
           next_action_at = null, claimed_by = null, claimed_at = null
     where id = p_shift and status in ('callout', 'offers_out') and nurse_id is null;
    return found;
exception when exclusion_violation then
    return false;
end;
$$;

-- The doorbell: audits every status change and rings; never does real work.
create or replace function log_shift_status() returns trigger language plpgsql as $$
begin
    if new.status is distinct from old.status then
        insert into events (agency_id, actor, kind, shift_id, payload)
        values (new.agency_id, 'db', 'shift_status_changed', new.id,
                jsonb_build_object('from', old.status, 'to', new.status));
        perform pg_notify('shift_changed', new.id::text);
    end if;
    return new;
end;
$$;
create trigger shifts_status_audit after update on shifts
    for each row execute function log_shift_status();

-- App writes via service role only (bypasses RLS). Enabling RLS with no
-- policies keeps anon/authenticated locked out until Phase 4 adds them.
alter table agencies enable row level security;
alter table nurses enable row level security;
alter table patients enable row level security;
alter table shifts enable row level security;
alter table offers enable row level security;
alter table events enable row level security;
