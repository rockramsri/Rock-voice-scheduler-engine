/**
 * Supabase browser client + row types. The publishable key is public by
 * design; RLS policies (Rock-scheduler-voice-agent/data/dashboard.sql)
 * decide what it can read and touch.
 */
import { createClient } from "@supabase/supabase-js";

const url =
  import.meta.env["VITE_SUPABASE_URL"] ?? "https://xzcpacifagkkxlplocgu.supabase.co";
const key =
  import.meta.env["VITE_SUPABASE_ANON_KEY"] ??
  "sb_publishable_bAjmPr7lb8fSJnyWzS9T8w_fjXLexkE";

export const supabase = createClient(url, key);

/** The agency line callers dial — Twilio number routed through LiveKit SIP. */
export const AGENCY_PHONE =
  import.meta.env["VITE_AGENCY_PHONE"] ?? "+1 (929) 730-7867";

export interface Nurse {
  id: string;
  agency_id: string;
  name: string;
  phone: string;
  specialties: string[];
  areas: string[];
  pay_level: 1 | 2 | 3;
  license_ok: boolean;
  reliability: number;
  preferences: { channels: ("sms" | "whatsapp" | "voice")[] };
  avatar_url: string;
  active: boolean;
}

export interface Workflow {
  id: string;
  agency_id: string;
  name: string;
  kind: "scheduling";
  nurse_ids: string[];
  active: boolean;
  created_at: string;
}

export interface Shift {
  id: string;
  patient_id: string;
  nurse_id: string | null;
  specialty: string;
  area: string;
  starts_at: string;
  ends_at: string;
  status: string;
  callout_nurse_id: string | null;
  callout_reason: string | null;
  callout_at: string | null;
  rung: number;
  patients?: { name: string; area: string };
}

export interface Offer {
  id: string;
  shift_id: string;
  nurse_id: string;
  score: number;
  reason: string;
  state: string;
  rung: number;
  last_channel: string | null;
  last_touch_at: string | null;
  responded_at: string | null;
}

export interface EventRow {
  id: number;
  at: string;
  actor: string;
  kind: string;
  shift_id: string | null;
  nurse_id: string | null;
  channel: string | null;
  rung: number | null;
  outcome: string | null;
  payload: Record<string, unknown>;
}
