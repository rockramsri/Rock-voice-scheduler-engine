export interface Nurse {
  id: string;
  agency_id: string;
  name: string;
  phone: string;
  specialties: string[];
  areas: string[];
  pay_level: number;
  license_ok: boolean;
  reliability: number;
  preferences: { channels: string[] };
  avatar_url: string;
  active: boolean;
}

export interface Workflow {
  id: string;
  agency_id: string;
  name: string;
  kind: string;
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
