import { useState } from "react";
import { ChevronDown, Play } from "lucide-react";
import {
  metric,
  metricText,
  type MetricDelta,
  type Scorecard,
} from "@/lib/evals-api";

const VERDICT_TONE: Record<string, string> = {
  CONFIRMED_CORRECT: "var(--ring-accepted)",
  REGRESSION: "var(--ring-escalated)",
  UNRESOLVED: "var(--ring-callout)",
};

const DIRECTION_TONE: Record<string, string> = {
  better: "var(--ring-accepted)",
  worse: "var(--ring-escalated)",
  same: "var(--edge-idle)",
  missing: "var(--ring-callout)",
};

function deltaGlyph(direction: string): string {
  if (direction === "better") return "▲";
  if (direction === "worse") return "▼";
  if (direction === "missing") return "?";
  return "—";
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="clay-chip rounded-2xl px-3 py-2 text-center">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-0.5 text-[13px] font-bold tabular-nums text-foreground">{value}</p>
    </div>
  );
}

export function ScorecardCard({
  card,
  deltas,
  description,
  onQuickRun,
  busy,
}: {
  card: Scorecard;
  deltas?: MetricDelta[];
  description?: string;
  onQuickRun?: (scenarioId: string) => void;
  busy?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const verdict = String(card.deterministic.oracle_verdict ?? "UNRESOLVED");
  const tone = VERDICT_TONE[verdict] ?? "var(--ring-callout)";
  const nd = card.nondeterministic;
  const judge = nd.judge;
  const unstable = judge.stability === "UNSTABLE";
  const deltaByName = new Map((deltas ?? []).map((d) => [d.name, d]));
  const blocking = (deltas ?? []).filter((d) => d.blocks);

  return (
    <article
      className="clay-card flex flex-col gap-3 rounded-[24px] p-5"
      style={
        blocking.length
          ? { boxShadow: "var(--clay-out), inset 0 0 0 1.5px color-mix(in oklab, var(--ring-escalated) 50%, transparent)" }
          : undefined
      }
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-[14px] font-bold tracking-tight text-foreground">
            {card.scenario_id}
          </h3>
          <p className="mt-0.5 line-clamp-2 text-[11.5px] text-muted-foreground">
            {description ?? ""}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <span
            className="clay-chip rounded-full px-3 py-1 text-[10px] font-bold uppercase tracking-[0.1em]"
            style={{ color: tone }}
          >
            {verdict === "CONFIRMED_CORRECT" ? "confirmed" : verdict.toLowerCase()}
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            {card.channel} · {card.engine_profile}
          </span>
        </div>
      </header>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5">
          {Array.from({ length: nd.k }).map((_, i) => (
            <i
              key={i}
              className="block h-3 w-3 rounded-full"
              style={{
                background:
                  i < nd.passes ? "var(--ring-accepted)" : "var(--ring-escalated)",
                opacity: i < nd.passes ? 1 : 0.9,
              }}
            />
          ))}
        </div>
        <span className="text-[12px] font-bold tabular-nums text-foreground">
          {nd.passes}/{nd.k}
        </span>
        <span className="text-[11px] font-semibold text-muted-foreground">
          pass^{nd.k} {nd.pass_k ? "✓" : "✗"}
        </span>
        {judge.agreement_with_oracle !== null && (
          <span
            className="clay-chip ml-auto rounded-full px-2.5 py-1 text-[10px] font-bold"
            style={{ color: unstable ? "var(--ring-callout)" : "var(--ring-accepted)" }}
            title={unstable ? "LLM judge quarantined — excluded from averages" : "LLM judge agrees with the oracle"}
          >
            judge {judge.agreement_with_oracle}%{unstable ? " · UNSTABLE" : ""}
          </span>
        )}
      </div>

      <div className="grid grid-cols-3 gap-2">
        <Stat label="turns" value={metricText(metric(card, "turns_used"))} />
        <Stat label="ttfa p50" value={metricText(metric(card, "ttfa_p50_ms"))} />
        <Stat label="turn p95" value={metricText(metric(card, "full_turn_p95_ms"))} />
      </div>

      {blocking.length > 0 && (
        <div className="rounded-2xl px-3 py-2 text-[11px] font-semibold"
          style={{ background: "color-mix(in oklab, var(--ring-escalated) 10%, transparent)", color: "var(--ring-escalated)" }}>
          GATE: {blocking.map((d) => `${d.name} ${String(d.baseline)} → ${String(d.current)}`).join(" · ")}
        </div>
      )}

      <div className="mt-auto flex items-center justify-between gap-2 pt-1">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="clay-pill flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-semibold text-muted-foreground transition-transform hover:-translate-y-0.5"
        >
          <ChevronDown
            className="h-3.5 w-3.5 transition-transform"
            style={{ transform: open ? "rotate(180deg)" : undefined }}
            strokeWidth={2.6}
          />
          all metrics
        </button>
        {onQuickRun && (
          <button
            type="button"
            disabled={busy}
            onClick={() => onQuickRun(card.scenario_id)}
            className="clay-pill flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-semibold text-router transition-transform hover:-translate-y-0.5 disabled:opacity-40"
          >
            <Play className="h-3.5 w-3.5" strokeWidth={2.6} /> quick run
          </button>
        )}
      </div>

      {open && (
        <div className="clay-canvas rounded-2xl p-3">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-left text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                <th className="pb-1.5">metric</th>
                <th className="pb-1.5">role</th>
                <th className="pb-1.5 text-right">value</th>
                <th className="pb-1.5 text-right">vs baseline</th>
              </tr>
            </thead>
            <tbody>
              {card.metrics.map((m) => {
                const delta = deltaByName.get(m.name);
                return (
                  <tr key={m.name} className="border-t border-black/5">
                    <td className="py-1.5 font-medium text-foreground/85">{m.name}</td>
                    <td className="py-1.5">
                      <span
                        className="rounded-full px-2 py-0.5 text-[9.5px] font-bold uppercase"
                        style={{
                          color: m.role === "gate" ? "var(--ring-router)" : "var(--muted-foreground)",
                          background:
                            m.role === "gate"
                              ? "color-mix(in oklab, var(--ring-router) 12%, transparent)"
                              : "color-mix(in oklab, var(--foreground) 5%, transparent)",
                        }}
                      >
                        {m.role}
                      </span>
                    </td>
                    <td className="py-1.5 text-right font-semibold tabular-nums text-foreground">
                      {metricText(m)}
                    </td>
                    <td className="py-1.5 text-right tabular-nums"
                      style={{ color: DIRECTION_TONE[delta?.direction ?? "same"] }}>
                      {delta ? `${deltaGlyph(delta.direction)} ${delta.direction === "same" ? "" : String(delta.baseline ?? "—")}` : ""}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}
