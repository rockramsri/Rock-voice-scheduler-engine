/**
 * Workflow / nurse roster store — LIVE version.
 *
 * Same types, helpers, and mock templates as the design reference, but the
 * store hook persists straight to Supabase: nurses upserted by phone (the
 * identity), workflows upserted by id, single-profile edits written through.
 * Realtime (use-live-data) reflects every change back into the UI.
 *
 * Mock injects carry a demo_shift tag (today / tomorrow / +N days). On save,
 * missing scheduled shifts are created so a phone callout can run end-to-end.
 */
import { useCallback, useMemo, useState } from "react";
import { supabase } from "@/lib/supabase";

export type Channel = "sms" | "whatsapp" | "voice";

/** When the nurse's next scheduled shift should land (relative to save time). */
export interface DemoShift {
  label: string; // shown on inject cards, e.g. "today", "tomorrow", "in 3 days"
  offset_days: number; // 0 = today (+~3h), else that many midnights ahead @ 8am
}

export interface NurseProfile {
  id: string; // uuid
  name: string;
  phone: string; // E.164, UNIQUE — caller identity
  specialties: string[];
  areas: string[];
  pay_level: 1 | 2 | 3;
  license_ok: boolean;
  reliability: number; // 0..1
  preferences: { channels: Channel[] };
  avatar_url: string; // "" = initials avatar
  active: boolean;
  /** Present on mock templates; stripped after first save creates the row. */
  demo_shift?: DemoShift;
}

export interface Workflow {
  id: string; // uuid
  name: string;
  kind: "scheduling";
  nurse_ids: string[];
  active: boolean;
  created_at: string; // ISO
}

export const CHANNELS: Channel[] = ["sms", "whatsapp", "voice"];

export const uid = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `id-${Math.random().toString(36).slice(2)}-${Date.now()}`;

/** Blank slot used by the workflow builder. */
export function emptyNurse(): NurseProfile {
  return {
    id: uid(),
    name: "",
    phone: "",
    specialties: [],
    areas: [],
    pay_level: 2,
    license_ok: true,
    reliability: 0.8,
    preferences: { channels: ["sms", "whatsapp", "voice"] },
    avatar_url: "",
    active: true,
  };
}

const SHIFT_TODAY: DemoShift = { label: "today", offset_days: 0 };
const SHIFT_TOMORROW: DemoShift = { label: "tomorrow", offset_days: 1 };
const SHIFT_IN_2: DemoShift = { label: "in 2 days", offset_days: 2 };
const SHIFT_IN_3: DemoShift = { label: "in 3 days", offset_days: 3 };

/** Injectable mock templates — phone blank; demo_shift tags seed a real calendar row on save. */
export const MOCK_PROFILES: Omit<NurseProfile, "id">[] = [
  // 4× today so a live callout demo always has someone to pull up
  ["Maria Alvarez", "wound care", "Jersey City", 3, true, 0.9, SHIFT_TODAY],
  ["James Okafor", "wound care", "Hoboken", 2, true, 0.85, SHIFT_TODAY],
  ["Fatima Diallo", "wound care", "Bayonne", 1, true, 0.8, SHIFT_TODAY],
  ["Priya Natarajan", "geriatric", "Jersey City", 3, true, 0.88, SHIFT_TODAY],
  ["Grace Lim", "geriatric", "Edison", 2, true, 0.82, SHIFT_TOMORROW],
  ["Elena Petrova", "pediatric", "Montclair", 2, true, 0.78, SHIFT_IN_2],
  ["Robert Cianci", "pediatric", "Princeton", 2, false, 0.7, SHIFT_TOMORROW],
  ["Darnell Hayes", "physical therapy", "Hackensack", 3, true, 0.86, SHIFT_IN_3],
  ["Hannah Weiss", "physical therapy", "Morristown", 2, true, 0.75, SHIFT_TOMORROW],
  ["Tom Whitfield", "wound care", "Newark", 1, false, 0.6, SHIFT_IN_3],
].map(([name, specialty, area, pay, licensed, reliability, demo_shift]) => ({
  name: name as string,
  phone: "",
  specialties: [specialty as string],
  areas: [area as string],
  pay_level: pay as 1 | 2 | 3,
  license_ok: licensed as boolean,
  reliability: reliability as number,
  preferences: { channels: [...CHANNELS] },
  avatar_url: "",
  active: true,
  demo_shift: demo_shift as DemoShift,
}));

/** Fallback when a saved nurse has no mock tag — keeps custom names demo-ready. */
function defaultDemoShift(index: number): DemoShift {
  if (index < 4) return SHIFT_TODAY;
  if (index < 7) return SHIFT_TOMORROW;
  if (index < 9) return SHIFT_IN_2;
  return SHIFT_IN_3;
}

function shiftWindow(
  offsetDays: number,
  todayIndex: number,
): { starts: string; ends: string } {
  const now = new Date();
  let starts: Date;
  let hours = 8;
  if (offsetDays <= 0) {
    // Staggered 4h blocks (+3h, +7h, +11h …) so today-nurses never overlap —
    // the worker excludes anyone booked during the callout window, so
    // same-slot shifts would leave a callout with zero prospects.
    starts = new Date(now.getTime() + (3 + todayIndex * 4) * 60 * 60 * 1000);
    hours = 4;
  } else {
    starts = new Date(now);
    starts.setHours(0, 0, 0, 0);
    starts.setDate(starts.getDate() + offsetDays);
    starts.setHours(8, 0, 0, 0);
  }
  const ends = new Date(starts.getTime() + hours * 60 * 60 * 1000);
  return { starts: starts.toISOString(), ends: ends.toISOString() };
}

async function ensurePatient(
  agencyId: string,
  area: string,
  specialty: string,
): Promise<string> {
  const { data: existing } = await supabase
    .from("patients").select("id").eq("area", area).limit(1);
  if (existing?.[0]?.id) return existing[0].id as string;
  const { data, error } = await supabase.from("patients").insert({
    agency_id: agencyId,
    name: `Client in ${area}`,
    area,
    care_needs: [specialty],
  }).select("id").single();
  if (error) throw error;
  return (data as { id: string }).id;
}

/** Create a scheduled shift for each nurse who does not already have one. */
async function ensureDemoShifts(
  agencyId: string,
  nurses: { id: string; profile: NurseProfile }[],
) {
  let todayIndex = 0;
  for (let i = 0; i < nurses.length; i++) {
    const { id, profile } = nurses[i]!;
    const demo = profile.demo_shift ?? defaultDemoShift(i);
    const { data: have } = await supabase.from("shifts").select("id")
      .eq("nurse_id", id).eq("status", "scheduled").limit(1);
    if (have?.length) {
      if (demo.offset_days <= 0) todayIndex++;
      continue;
    }

    const specialty = profile.specialties[0] || "wound care";
    const area = profile.areas[0] || "Jersey City";
    const patientId = await ensurePatient(agencyId, area, specialty);
    const { starts, ends } = shiftWindow(demo.offset_days, todayIndex);
    if (demo.offset_days <= 0) todayIndex++;
    const { error } = await supabase.from("shifts").insert({
      agency_id: agencyId,
      patient_id: patientId,
      nurse_id: id,
      specialty,
      area,
      starts_at: starts,
      ends_at: ends,
      pay_rate: 38 + profile.pay_level * 4,
      status: "scheduled",
    });
    if (error) throw error;
  }
  // Profile edits (specialty/area) flow into existing scheduled shifts, so
  // the worker's hard specialty filter keeps finding prospects after edits.
  await supabase.rpc("sync_demo_shifts");
}

/* ── avatar helpers ─────────────────────────────────────────────────────── */

export function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "··";
  return (parts[0]![0]! + (parts[1]?.[0] ?? "")).toUpperCase();
}

/** Deterministic hue from the name so avatars are stable across renders. */
export function avatarHue(name: string) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
  return h;
}

/* ── validation ─────────────────────────────────────────────────────────── */

export const E164 = /^\+[1-9]\d{7,14}$/;

export interface NurseErrors {
  name?: string;
  phone?: string;
  channels?: string;
}

export function validateNurse(n: NurseProfile, all: NurseProfile[]): NurseErrors {
  const e: NurseErrors = {};
  if (!n.name.trim()) e.name = "Name is required";
  else if (all.some((o) => o.id !== n.id && o.name.trim() === n.name.trim()))
    e.name = "Duplicate name — names identify people on calls";
  if (!n.phone.trim()) e.phone = "Phone is required — offers are sent to it";
  else if (!E164.test(n.phone.trim())) e.phone = "Use E.164 format, e.g. +12015550142";
  else if (n.phone.trim().startsWith("+1") && n.phone.trim().length !== 12)
    e.phone = "US numbers need exactly 10 digits after +1";
  // Duplicate phones are ALLOWED on purpose: solo testing puts one real
  // number on several nurses; identity in conversation is by name.
  if (!n.preferences.channels.length) e.channels = "Pick at least one channel";
  return e;
}

export function hasErrors(e: NurseErrors) {
  return Boolean(e.name || e.phone || e.channels);
}

/* ── live store: Supabase persistence + realtime-fed reads ──────────────── */

const ALL_WEEK = Array.from({ length: 7 }, (_, dow) =>
  ({ dow, start: "07:00", end: "20:00" }));

export interface LiveSource {
  workflows: Workflow[];
  nurses: NurseProfile[]; // realtime rows from use-live-data (superset is fine)
  agencyId: string;
  refresh: () => void;
}

export function useWorkflowStore(source: LiveSource) {
  const [saving, setSaving] = useState(false);
  const byId = useMemo(
    () => new Map(source.nurses.map((n) => [n.id, n])), [source.nurses]);

  const saveWorkflow = useCallback(async (workflow: Workflow, members: NurseProfile[]) => {
    setSaving(true);
    try {
      const saved: { id: string; profile: NurseProfile }[] = [];
      for (const n of members) {
        const fields = {
          agency_id: source.agencyId,
          name: n.name.trim(),
          phone: n.phone.trim(),
          specialties: n.specialties,
          areas: n.areas,
          pay_level: n.pay_level,
          license_ok: n.license_ok,
          reliability: n.reliability,
          preferences: { channels: n.preferences.channels },
          avatar_url: n.avatar_url,
          active: n.active,
        };
        // Existing member (id known to the live roster) -> update in place.
        // New/injected profile -> insert. Duplicate phones are fine; each
        // nurse keeps their own row and offers carry nurse_id.
        if (byId.has(n.id)) {
          const { error } = await supabase.from("nurses").update(fields).eq("id", n.id);
          if (error) throw error;
          saved.push({ id: n.id, profile: n });
        } else {
          const { data, error } = await supabase.from("nurses")
            .insert({ ...fields, availability: ALL_WEEK }).select("id").single();
          if (error) throw error;
          saved.push({ id: (data as { id: string }).id, profile: n });
        }
      }
      const ids = saved.map((s) => s.id);
      const { error } = await supabase.from("workflows").upsert({
        id: workflow.id, agency_id: source.agencyId, name: workflow.name,
        kind: workflow.kind, nurse_ids: ids, active: workflow.active,
      }, { onConflict: "id" });
      if (error) throw error;
      // Seed calendar rows so FrontDesk get_shift / report_callout work live.
      await ensureDemoShifts(source.agencyId, saved);
      source.refresh();
      return { ...workflow, nurse_ids: ids };
    } finally {
      setSaving(false);
    }
  }, [source, byId]);

  const deleteWorkflow = useCallback(async (id: string) => {
    await supabase.from("workflows").delete().eq("id", id);
    source.refresh();
  }, [source]);

  const toggleWorkflow = useCallback(async (id: string, active: boolean) => {
    await supabase.from("workflows").update({ active }).eq("id", id);
    source.refresh();
  }, [source]);

  /** Single-profile edit popup writes through here (applies everywhere). */
  const updateNurse = useCallback(async (n: NurseProfile) => {
    await supabase.from("nurses").update({
      name: n.name.trim(), phone: n.phone.trim(), specialties: n.specialties,
      areas: n.areas, pay_level: n.pay_level, license_ok: n.license_ok,
      reliability: n.reliability, preferences: { channels: n.preferences.channels },
      avatar_url: n.avatar_url, active: n.active,
    }).eq("id", n.id);
    await supabase.rpc("sync_demo_shifts");
    source.refresh();
  }, [source]);

  const membersOf = useCallback(
    (w: Workflow) =>
      w.nurse_ids.map((id) => byId.get(id)).filter(Boolean) as NurseProfile[],
    [byId],
  );

  return {
    workflows: source.workflows,
    nurses: Object.fromEntries(source.nurses.map((n) => [n.id, n])),
    saving,
    saveWorkflow,
    deleteWorkflow,
    toggleWorkflow,
    updateNurse,
    membersOf,
  };
}
