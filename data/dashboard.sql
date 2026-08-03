-- Dashboard additions. Apply once: psql $DB_URL -f data/dashboard.sql
-- Adds: workflows (registered demo/ops scenarios), nurse channel
-- preferences + avatars, anon RLS policies for the dashboard app, and the
-- realtime publication the live graph subscribes to.

create table workflows (
    id uuid primary key default gen_random_uuid(),
    agency_id uuid not null references agencies(id),
    name text not null,
    kind text not null default 'scheduling',
    nurse_ids uuid[] not null default '{}',
    active boolean not null default true,
    created_at timestamptz not null default now()
);
alter table workflows enable row level security;

-- Which channels a nurse is comfortable with; the outreach ladder obeys it.
alter table nurses add column preferences jsonb not null
    default '{"channels": ["sms", "whatsapp", "voice"]}';
alter table nurses add column avatar_url text not null default '';

-- DEMO POLICIES (currently applied). The dashboard is a single-tenant ops
-- tool that talks to Supabase with the anon key and NO auth session: it needs
-- anon SELECT on every table (live story feed) plus anon INSERT/UPDATE on
-- nurses/patients/shifts/workflows (workflow registration + demo seeding).
-- These are DELIBERATELY permissive for the public demo. Service role bypasses
-- RLS entirely. For a production posture, see "PRODUCTION HARDENING" at the
-- bottom of this file (do not enable it without adding Auth to the console).
create policy dash_read on agencies for select to anon using (true);
create policy dash_read on patients for select to anon using (true);
create policy dash_read on shifts for select to anon using (true);
create policy dash_read on offers for select to anon using (true);
create policy dash_read on events for select to anon using (true);
create policy dash_read on nurses for select to anon using (true);
create policy dash_read on workflows for select to anon using (true);
create policy dash_insert on nurses for insert to anon with check (true);
create policy dash_update on nurses for update to anon using (true) with check (true);
create policy dash_insert on patients for insert to anon with check (true);
create policy dash_insert on shifts for insert to anon with check (true);
create policy dash_all on workflows for all to anon using (true) with check (true);

-- Live graph + log feed subscribe to these.
alter publication supabase_realtime add table events, shifts, offers, nurses, workflows;

-- Demo fast-forward: the dashboard button skips ladder waits. Deliberately
-- the ONLY mutation the anon role can make to shifts.
create or replace function ff_shifts() returns integer
language sql security definer set search_path = public as $$
  with bumped as (
    update shifts set next_action_at = now()
    where status in ('callout', 'offers_out')
    returning 1)
  select count(*)::int from bumped;
$$;
grant execute on function ff_shifts() to anon;

-- Demo coherence: when a nurse's profile specialty/area changes in the
-- console, their upcoming scheduled shift follows — otherwise the worker's
-- hard specialty filter finds no prospects after edits. Anon-callable like
-- ff_shifts; guarded to scheduled rows whose specialty no longer matches.
create or replace function sync_demo_shifts() returns integer
language sql security definer set search_path = public as $$
  with synced as (
    update shifts s
       set specialty = n.specialties[1],
           area = coalesce(n.areas[1], s.area)
      from nurses n
     where s.nurse_id = n.id
       and s.status = 'scheduled'
       and cardinality(n.specialties) > 0
       and not (s.specialty = any(n.specialties))
    returning 1)
  select count(*)::int from synced;
$$;
grant execute on function sync_demo_shifts() to anon;


-- ============================================================================
-- PRODUCTION HARDENING (NOT APPLIED IN THE DEMO)
-- ----------------------------------------------------------------------------
-- The demo policies above grant the anonymous role broad read/write access so
-- the console can run with no login. That is fine for a single-tenant public
-- demo but unacceptable for real PHI. To harden for production you must FIRST
-- add Supabase Auth to the ops console (sign-in + an authenticated session);
-- the console must send the user's JWT (not the anon key) on every request.
-- Only then swap the anon policies below for authenticated-role equivalents.
--
-- This block is intentionally left commented out. Applying it as-is WITHOUT
-- console auth will break registration and the live graph (the console would
-- have no authenticated session and lose all access). Enable deliberately.
--
--   -- 1) Drop the permissive demo policies.
--   drop policy dash_read   on agencies;
--   drop policy dash_read   on patients;
--   drop policy dash_read   on shifts;
--   drop policy dash_read   on offers;
--   drop policy dash_read   on events;
--   drop policy dash_read   on nurses;
--   drop policy dash_read   on workflows;
--   drop policy dash_insert on nurses;
--   drop policy dash_update on nurses;
--   drop policy dash_insert on patients;
--   drop policy dash_insert on shifts;
--   drop policy dash_all    on workflows;
--
--   -- 2) Re-grant the same capabilities to signed-in users only. Tighten the
--   --    USING/WITH CHECK expressions further for multi-tenant (e.g. join the
--   --    row's agency_id to the caller's claim) — `using (true)` here just
--   --    means "any authenticated user", which is the minimum improvement.
--   create policy app_read   on agencies  for select to authenticated using (true);
--   create policy app_read   on patients  for select to authenticated using (true);
--   create policy app_read   on shifts    for select to authenticated using (true);
--   create policy app_read   on offers    for select to authenticated using (true);
--   create policy app_read   on events    for select to authenticated using (true);
--   create policy app_read   on nurses    for select to authenticated using (true);
--   create policy app_read   on workflows for select to authenticated using (true);
--   create policy app_insert on nurses    for insert to authenticated with check (true);
--   create policy app_update on nurses    for update to authenticated using (true) with check (true);
--   create policy app_insert on patients  for insert to authenticated with check (true);
--   create policy app_insert on shifts    for insert to authenticated with check (true);
--   create policy app_all    on workflows for all    to authenticated using (true) with check (true);
--
--   -- 3) Restrict the demo helper RPCs to signed-in users too.
--   revoke execute on function ff_shifts()        from anon;
--   revoke execute on function sync_demo_shifts() from anon;
--   grant  execute on function ff_shifts()        to authenticated;
--   grant  execute on function sync_demo_shifts() to authenticated;
--
-- Additionally for real PHI: sign a Supabase BAA, restrict the events table's
-- verbatim payloads (set LOG_MESSAGE_CONTENT=false so data.db.log_event scrubs
-- them), and rotate any keys that were exposed during the demo.
-- ============================================================================
