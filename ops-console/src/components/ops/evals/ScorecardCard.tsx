import { useState } from "react";
import { ChevronDown, MessageSquareText, Mic, MessagesSquare, Play } from "lucide-react";
import {
  metric,
  metricText,
  type MetricDelta,
  type Scorecard,
} from "@/lib/evals-api";
import { GradientBar, MetricInfo } from "./MetricBits";
import { scenarioAccent, scenarioGradient, shortName, VERDICT_TONE } from "./cardStyle";

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

function num(card: Scorecard, name: string): number | null {
  const m = metric(card, name);
  return typeof m?.value === "number" ? m.value : null;
}

export function ScorecardCard({
  card,
  deltas,
  description,
  turnBudget,
  onQuickRun,
  onTranscripts,
  busy,
}: {
  card: Scorecard;
  deltas?: MetricDelta[] | undefined;
  description?: string | undefined;
  turnBudget?: number | null | undefined;
  onQuickRun?: ((scenarioId: string) => void) | undefined;
  onTranscripts?: ((scenarioId: string) => void) | undefined;
  busy?: boolean | undefined;
}) {
  const [open, setOpen] = useState(false);
  const verdict = String(card.deterministic["oracle_verdict"] ?? "UNRESOLVED");
  const nd = card.nondeterministic;
  const judge = nd.judge;
  const unstable = judge.stability === "UNSTABLE";
  const deltaByName = new Map((deltas ?? []).map((d) => [d.name, d]));
  const blocking = (deltas ?? []).filter((d) => d.blocks);

  const ttfa = num(card, "ttfa_p50_ms");
  const p95 = num(card, "full_turn_p95_ms");
  const turns = num(card, "turns_used");
  const budget = turnBudget ?? null;
  const ChannelIcon = card.channel === "sms" ? MessageSquareText : Mic;

  return (
    <article
      className="clay-card flex flex-col overflow-hidden rounded-[24px]"
      style={
        blocking.length
          ? { boxShadow: "var(--clay-out), inset 0 0 0 2px color-mix(in oklab, var(--ring-escalated) 55%, transparent)" }
          : undefined
      }
    >
      {/* quiet accent strip — tells scenarios apart without shouting */}
      <div className="h-1.5 w-full" style={{ background: scenarioGradient(card.scenario_id) }} />
      <div className="px-5 pb-3 pt-3.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              {card.scenario_id.split("-").slice(0, 2).join("-")} · {card.channel} · {card.engine_profile}
            </p>
            <h3 className="mt-0.5 truncate text-[15px] font-bold capitalize tracking-tight text-foreground">
              {shortName(card.scenario_id)}
            </h3>
          </div>
          <span
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl"
            style={{
              color: scenarioAccent(card.scenario_id),
              background: `color-mix(in oklab, ${scenarioAccent(card.scenario_id)} 12%, white)`,
            }}
          >
            <ChannelIcon className="h-4.5 w-4.5" strokeWidth={2.4} />
          </span>
        </div>
        <div className="mt-2 flex items-center gap-2">
          <span
            className="clay-chip rounded-full px-2.5 py-0.5 text-[9.5px] font-bold uppercase tracking-[0.1em]"
            style={{ color: VERDICT_TONE[verdict] ?? "var(--ring-callout)" }}
          >
            {verdict === "CONFIRMED_CORRECT" ? "confirmed" : verdict.toLowerCase()}
          </span>
          <div className="flex items-center gap-1">
            {Array.from({ length: nd.k }).map((_, i) => (
              <i key={i} className="block h-2.5 w-2.5 rounded-full"
                style={{
                  background: i < nd.passes
                    ? "var(--ring-accepted)"
                    : "color-mix(in oklab, var(--ring-escalated) 75%, white)",
                }} />
            ))}
          </div>
          <span className="text-[11px] font-bold tabular-nums text-muted-foreground">
            pass^{nd.k} {nd.pass_k ? "✓" : "✗"}
          </span>
        </div>
        {description && (
          <p className="mt-1.5 line-clamp-2 text-[11px] leading-snug text-muted-foreground">{description}</p>
        )}
      </div>

      {/* clay body — bars carry the numbers */}
      <div className="flex flex-1 flex-col gap-2.5 px-5 pb-4 pt-1">
        <div className="grid grid-cols-[112px_minmax(0,1fr)] items-center gap-x-2 gap-y-2">
          <span className="flex items-center gap-1 text-[10.5px] font-semibold text-muted-foreground">
            trials passed <MetricInfo name="pass_k" />
          </span>
          <GradientBar value={nd.passes} max={nd.k} text={`${nd.passes}/${nd.k}`}
            tone={nd.pass_k ? "good" : "bad"} />

          <span className="flex items-center gap-1 text-[10.5px] font-semibold text-muted-foreground">
            judge match <MetricInfo name="judge_oracle_agreement" />
          </span>
          <GradientBar value={judge.agreement_with_oracle} max={100}
            text={judge.agreement_with_oracle === null ? "MISSING"
              : `${judge.agreement_with_oracle}%${unstable ? " · UNSTABLE" : ""}`}
            tone={unstable ? "warn" : "good"} />

          <span className="flex items-center gap-1 text-[10.5px] font-semibold text-muted-foreground">
            turns{budget ? ` / ${budget}` : ""} <MetricInfo name="turns_used" />
          </span>
          <GradientBar value={turns} max={budget ?? Math.max(4, turns ?? 4)}
            text={turns === null ? "MISSING" : `${turns}${budget ? ` of ${budget}` : ""}`}
            tone={budget && turns !== null && turns > budget ? "bad" : "brand"} />

          <span className="flex items-center gap-1 text-[10.5px] font-semibold text-muted-foreground">
            first answer <MetricInfo name="ttfa_p50_ms" />
          </span>
          <GradientBar value={ttfa} max={2000}
            text={ttfa === null ? "MISSING" : `${Math.round(ttfa)}ms`}
            tone={ttfa !== null && ttfa > 1500 ? "warn" : "brand"} />

          <span className="flex items-center gap-1 text-[10.5px] font-semibold text-muted-foreground">
            slowest turn <MetricInfo name="full_turn_p95_ms" />
          </span>
          <GradientBar value={p95} max={3000}
            text={p95 === null ? "MISSING" : `${Math.round(p95)}ms`}
            tone={p95 !== null && p95 > 2500 ? "warn" : "brand"} />
        </div>

        {blocking.length > 0 && (
          <div className="rounded-2xl px-3 py-2 text-[11px] font-semibold"
            style={{ background: "color-mix(in oklab, var(--ring-escalated) 10%, transparent)", color: "var(--ring-escalated)" }}>
            GATE: {blocking.map((d) => `${d.name} ${String(d.baseline)} → ${String(d.current)}`).join(" · ")}
          </div>
        )}

        <div className="mt-auto flex items-center gap-2 pt-1">
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="clay-pill flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-semibold text-muted-foreground transition-transform hover:-translate-y-0.5"
          >
            <ChevronDown className="h-3.5 w-3.5 transition-transform"
              style={{ transform: open ? "rotate(180deg)" : undefined }} strokeWidth={2.6} />
            all metrics
          </button>
          {onTranscripts && (
            <button
              type="button"
              onClick={() => onTranscripts(card.scenario_id)}
              className="clay-pill flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-semibold text-router transition-transform hover:-translate-y-0.5"
            >
              <MessagesSquare className="h-3.5 w-3.5" strokeWidth={2.6} /> transcripts
            </button>
          )}
          {onQuickRun && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onQuickRun(card.scenario_id)}
              className="clay-pill ml-auto flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-semibold text-router transition-transform hover:-translate-y-0.5 disabled:opacity-40"
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
                      <td className="py-1.5 font-medium text-foreground/85">
                        <span className="mr-1">{m.name}</span>
                        <MetricInfo name={m.name} />
                      </td>
                      <td className="py-1.5">
                        <span className="rounded-full px-2 py-0.5 text-[9.5px] font-bold uppercase"
                          style={{
                            color: m.role === "gate" ? "var(--ring-router)" : "var(--muted-foreground)",
                            background: m.role === "gate"
                              ? "color-mix(in oklab, var(--ring-router) 12%, transparent)"
                              : "color-mix(in oklab, var(--foreground) 5%, transparent)",
                          }}>
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
      </div>
    </article>
  );
}
