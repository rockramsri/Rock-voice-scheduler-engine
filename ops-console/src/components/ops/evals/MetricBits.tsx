import { Info } from "lucide-react";

/** Plain-language help for every metric name the harness records. */
export const METRIC_HELP: Record<string, { full: string; what: string; example: string }> = {
  oracle_verdict: {
    full: "Oracle verdict",
    what: "Deterministic grade computed from database facts and audit events — never from the transcript.",
    example: "CONFIRMED_CORRECT = every gated check passed on real DB state.",
  },
  pass_k: {
    full: "pass^k",
    what: "The scenario passes only if ALL k trials pass. One bad trial fails the whole scenario.",
    example: "4/5 trials green → pass^5 is ✗ and the scenario is a regression.",
  },
  k: { full: "trials", what: "How many times the same scenario was replayed.", example: "k=5 replays." },
  passes: { full: "passing trials", what: "Trials where the oracle said CONFIRMED_CORRECT.", example: "5 of 5." },
  ttfa_p50_ms: {
    full: "Time To First Answer (median)",
    what: "How long the nurse waits for the agent's first reply, median across trials. Lower is better.",
    example: "246ms ≈ a quarter of a second.",
  },
  full_turn_p95_ms: {
    full: "Full turn latency (95th percentile)",
    what: "The slowest conversational turn, 95th percentile. Catches worst-case stalls. Lower is better.",
    example: "1942ms = the slowest reply took ~2s.",
  },
  turns_used: {
    full: "Agent turns used",
    what: "Average number of agent messages per trial. Must stay inside the scenario's turn budget.",
    example: "3.6 turns average vs a budget of 4.",
  },
  judge_oracle_agreement: {
    full: "Judge–oracle agreement",
    what: "How often the LLM judge (reads only the transcript) agrees with the oracle (reads only the DB).",
    example: "100% = the transcript reads exactly like what the database says happened.",
  },
  judge_stability: {
    full: "Judge stability",
    what: "UNSTABLE = the judge flip-flopped across trials or disagreed with the oracle twice — quarantined from averages.",
    example: "stable = same grade every trial.",
  },
  memory_compiled: {
    full: "Memory compiled",
    what: "Did the learned preference (e.g. no weekends) land in the nurse's DB profile as structured data?",
    example: "true = avoid_dows [5,6] saved on the nurse row.",
  },
  ranking_first_contact: {
    full: "Ranking → first contact",
    what: "The first nurse contacted must be the top-ranked prospect, in the expected order.",
    example: "CG-101 ranked first and was texted first.",
  },
  quiet_hours: {
    full: "Quiet hours",
    what: "No calls dialed inside the agency's quiet window; urgent shifts escalate instead.",
    example: "A 2am callout waits for the 8am call window.",
  },
  single_winner_lock: {
    full: "Single winner lock",
    what: "Exactly one nurse wins the shift, even in a race — everyone else is stood down.",
    example: "Two simultaneous YES replies → one accepted, one 'yes_too_late'.",
  },
  no_double_text: {
    full: "No double text",
    what: "At most one outbound message per (offer, ladder rung, channel) — crash-safe against re-sends.",
    example: "Rung 1 SMS never fires twice for the same offer.",
  },
  scope_two_tools: {
    full: "Tool scope",
    what: "Voice calls may only use accept/decline; SMS only its two lookup tools. Anything else = injection.",
    example: "'Read me the roster' produces zero tool calls.",
  },
  human_fallback: {
    full: "Human fallback",
    what: "When prospects are exhausted (or urgent in quiet hours), the shift escalates to a human — and outreach stops.",
    example: "Status 'escalated', no texts after the escalation event.",
  },
  turn_budget_endstate: {
    full: "Turn budget + end state",
    what: "The conversation stayed inside its turn budget AND the DB ended exactly as scripted.",
    example: "Shift 'filled' by CG-101 within 4 agent turns.",
  },
  audit_completeness: {
    full: "Audit completeness",
    what: "Every status change has its cause event and vice versa — the audit log tells the whole story.",
    example: "'filled' pairs with an offer_response yes + EMR writeback.",
  },
  no_context_bleed: {
    full: "No context bleed",
    what: "Call N never mentions earlier prospects, other phone numbers, patient names, or others' decline reasons.",
    example: "Second call never says 'Ana already declined'.",
  },
};

/** Little ⓘ that reveals the full name, meaning and an example on hover. */
export function MetricInfo({ name }: { name: string }) {
  const help = METRIC_HELP[name];
  if (!help) return null;
  return (
    <span className="group relative inline-flex align-middle">
      <Info className="h-3 w-3 cursor-help text-muted-foreground/70" strokeWidth={2.4} />
      <span className="clay-hovercard pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 hidden w-60 -translate-x-1/2 rounded-2xl p-3 text-left group-hover:block">
        <span className="block text-[11px] font-bold text-foreground">{help.full}</span>
        <span className="mt-1 block text-[10.5px] leading-relaxed font-normal normal-case tracking-normal text-muted-foreground">
          {help.what}
        </span>
        <span className="mt-1.5 block text-[10px] leading-relaxed font-medium normal-case tracking-normal text-router">
          e.g. {help.example}
        </span>
      </span>
    </span>
  );
}

/**
 * Gradient progress bar that still shows the real number.
 * tone: good = green→teal, warn = amber→orange, bad = red, brand = purple.
 */
export function GradientBar({
  value,
  max,
  text,
  tone = "good",
}: {
  value: number | null | undefined;
  max: number;
  text: string;
  tone?: "good" | "warn" | "bad" | "brand";
}) {
  const GRADIENTS: Record<string, string> = {
    good: "linear-gradient(90deg, oklch(0.86 0.07 165), oklch(0.82 0.07 190))",
    warn: "linear-gradient(90deg, oklch(0.88 0.08 85), oklch(0.84 0.1 55))",
    bad: "linear-gradient(90deg, oklch(0.84 0.09 25), oklch(0.8 0.11 10))",
    brand: "linear-gradient(90deg, oklch(0.87 0.05 280), oklch(0.84 0.06 230))",
  };
  const pct = value === null || value === undefined
    ? 0
    : Math.max(4, Math.min(100, (value / max) * 100));
  return (
    <div className="relative h-5 w-full overflow-hidden rounded-full"
      style={{ boxShadow: "var(--clay-in)", background: "oklch(0.97 0.003 260)" }}>
      <div
        className="h-full rounded-full transition-[width] duration-500"
        style={{ width: `${pct}%`, background: GRADIENTS[tone] }}
      />
      <span className="absolute inset-0 grid place-items-center text-[10px] font-bold tabular-nums text-foreground/85">
        {text}
      </span>
    </div>
  );
}
