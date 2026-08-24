/**
 * Client for the local eval API (evals/server.py — `make eval-server`).
 *
 * The eval lab is a testing sandbox: the server only ever talks to the
 * isolated eval Supabase project, so nothing here can touch production.
 */

export const EVALS_API =
  (import.meta.env["VITE_EVALS_API_URL"] as string | undefined) ??
  "http://localhost:8321";

/** Bearer token for POSTs (start runs / promote) on a hosted eval server.
 * Kept in localStorage so it's entered once per browser, never in the bundle. */
const TOKEN_KEY = "evals_api_token";

export function getApiToken(): string {
  if (typeof localStorage === "undefined") return "";
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setApiToken(token: string): void {
  if (typeof localStorage === "undefined") return;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

function postHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getApiToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

export interface Metric {
  name: string;
  role: "gate" | "track" | "compare";
  value: number | string | boolean | null;
  unit: string;
}

export interface MetricDelta {
  name: string;
  role: string;
  baseline: number | string | boolean | null;
  current: number | string | boolean | null;
  direction: "better" | "worse" | "same" | "missing";
  blocks: boolean;
}

export interface Scorecard {
  scenario_id: string;
  suite_run_id: string;
  engine_profile: string;
  channel: string;
  git_sha: string;
  ts: string;
  deterministic: Record<string, unknown>;
  nondeterministic: {
    k: number;
    passes: number;
    pass_k: boolean;
    judge: {
      rubric_verdicts: boolean[];
      agreement_with_oracle: number | null;
      stability: string;
      model: string | null;
    };
  };
  metrics: Metric[];
  evidence: Record<string, unknown>;
}

export interface SuiteSummary {
  suite_run_id: string;
  ts: string;
  git_sha: string;
  engine_profile: string;
  headline: string;
  kind: string;
  label: string | null;
  n_scenarios: number;
  scenario_ids: string[];
  regressions: number;
  pass_k: number;
}

export interface Trial {
  folder: string;
  run_idx: number;
  turns?: { role: string; text: string; ts?: string }[];
  tools?: { name: string; args: unknown }[];
  ttfa_ms?: number | null;
  verdict?: string;
  failed?: string[];
  judge_all_yes?: boolean | null;
  judge?: { answers: { question: string; verdict: boolean; quote: string }[]; model: string };
}

export interface SuiteDetail {
  suite_run_id: string;
  ts: string;
  git_sha: string;
  engine_profile: string;
  headline: string;
  scorecards: Scorecard[];
  baseline_deltas: Record<string, MetricDelta[]>;
  gate_blocks: { scenario: string; metric: string; baseline: unknown; current: unknown }[];
  meta?: { kind?: string; overrides?: Record<string, string> };
}

export interface ScenarioInfo {
  file: string;
  scenario_id: string;
  description: string;
  channel: string;
  layer: string;
  purpose: string[];
  gates: string[];
  judge_rubric: string[];
  k_trials: number;
  max_turn_budget: number | null;
  persona: { style?: string; policy?: string[] };
  tags: string[];
}

export interface RunEvent {
  kind: string;
  ts: string;
  [key: string]: unknown;
}

export interface RunRecord {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "error";
  started_at: string;
  finished_at?: string;
  config: {
    kind: string;
    scenarios: string[] | null;
    k: number | null;
    overrides: Record<string, string>;
  };
  suite_id?: string;
  verdict?: string;
  error?: string;
  events?: RunEvent[];
}

export interface HealthInfo {
  ok: boolean;
  busy: boolean;
  active_run: string | null;
  eval_db: string;
  defaults: Record<string, string>;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${EVALS_API}${path}`);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export const fetchHealth = () => get<HealthInfo>("/api/health");
export const fetchScenarios = () => get<ScenarioInfo[]>("/api/scenarios");
export const fetchSuites = () => get<SuiteSummary[]>("/api/suites");
export const fetchSuite = (sid: string) => get<SuiteDetail>(`/api/suites/${sid}`);
export const fetchLatest = () => get<SuiteDetail>("/api/latest");
export const fetchBaseline = () => get<{ scorecards: Scorecard[] }>("/api/baseline");
export const fetchRuns = () => get<Omit<RunRecord, "events">[]>("/api/runs");
export const fetchTranscripts = (suite: string, scenario: string) =>
  get<{ suite: string; scenario: string; trials: Trial[] }>(
    `/api/transcripts?suite=${suite}&scenario=${scenario}`,
  );
export const fetchRun = (rid: string) => get<RunRecord>(`/api/runs/${rid}`);
export const fetchCompare = (left: string, right: string) =>
  get<{
    left: { suite_run_id: string; engine_profile: string };
    right: { suite_run_id: string; engine_profile: string };
    scenarios: { scenario_id: string; deltas: MetricDelta[] }[];
  }>(`/api/compare?left=${left}&right=${right}`);

export async function startRun(body: {
  kind: "scenario" | "regression" | "benchmark";
  scenarios?: string[];
  k?: number;
  overrides?: Record<string, string>;
}): Promise<{ run_id: string }> {
  const res = await fetch(`${EVALS_API}/api/runs`, {
    method: "POST",
    headers: postHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => null)) as { error?: string } | null;
    throw new Error(detail?.error ?? `run failed to start (${res.status})`);
  }
  return res.json() as Promise<{ run_id: string }>;
}

export async function promoteBaseline(suiteId: string): Promise<void> {
  const res = await fetch(`${EVALS_API}/api/baseline/promote`, {
    method: "POST",
    headers: postHeaders(),
    body: JSON.stringify({ suite_id: suiteId }),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => null)) as { error?: string } | null;
    throw new Error(detail?.error ?? `promote failed (${res.status})`);
  }
}

/** Metric value → display text; null means MISSING (never estimated). */
export function metricText(m: Metric | undefined): string {
  if (!m || m.value === null || m.value === undefined) return "MISSING";
  if (typeof m.value === "boolean") return m.value ? "true" : "false";
  if (typeof m.value === "number") {
    const rounded = Number.isInteger(m.value) ? m.value : m.value.toFixed(1);
    return `${rounded}${m.unit}`;
  }
  return `${m.value}${m.unit}`;
}

export function metric(card: Scorecard, name: string): Metric | undefined {
  return card.metrics.find((m) => m.name === name);
}
