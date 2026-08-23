import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight, GitCompareArrows } from "lucide-react";
import { fetchCompare, type SuiteSummary } from "@/lib/evals-api";

const SHOWN = [
  "oracle_verdict", "pass_k", "turns_used",
  "ttfa_p50_ms", "full_turn_p95_ms", "judge_oracle_agreement",
];

const DIRECTION_TONE: Record<string, string> = {
  better: "var(--ring-accepted)",
  worse: "var(--ring-escalated)",
  same: "var(--muted-foreground)",
  missing: "var(--ring-callout)",
};

function show(value: unknown): string {
  if (value === null || value === undefined) return "MISSING";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(1);
  return String(value);
}

export function CompareSuites({ suites }: { suites: SuiteSummary[] }) {
  const [left, setLeft] = useState<string>("");
  const [right, setRight] = useState<string>("");

  const compare = useQuery({
    queryKey: ["evals-compare", left, right],
    queryFn: () => fetchCompare(left, right),
    enabled: !!left && !!right && left !== right,
  });

  const name = (s: SuiteSummary) =>
    `${s.suite_run_id}${s.label ? ` · ${s.label}` : s.kind !== "suite" ? ` · ${s.kind}` : ""}`;

  return (
    <section className="clay-panel rounded-[32px] p-5">
      <header className="mb-3 flex items-center gap-2">
        <GitCompareArrows className="h-4 w-4 text-router" strokeWidth={2.4} />
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Compare two runs
        </span>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {[
          { value: left, set: setLeft, label: "baseline / A" },
          { value: right, set: setRight, label: "candidate / B" },
        ].map((side, i) => (
          <label key={side.label} className={`min-w-[220px] flex-1 ${i === 1 ? "order-3" : ""}`}>
            <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              {side.label}
            </span>
            <select
              value={side.value}
              onChange={(e) => side.set(e.target.value)}
              className="clay-input mt-1 w-full appearance-none rounded-xl px-3 py-2 text-[12px] font-medium"
            >
              <option value="">pick a suite…</option>
              {suites.map((s) => (
                <option key={s.suite_run_id} value={s.suite_run_id}>
                  {name(s)}
                </option>
              ))}
            </select>
          </label>
        ))}
        <button
          type="button"
          aria-label="Swap sides"
          onClick={() => { setLeft(right); setRight(left); }}
          className="clay-pill order-2 mt-4 grid h-9 w-9 place-items-center rounded-full text-muted-foreground transition-transform hover:-translate-y-0.5"
        >
          <ArrowLeftRight className="h-4 w-4" strokeWidth={2.4} />
        </button>
      </div>

      {compare.data && (
        <div className="flex flex-col gap-3">
          {compare.data.scenarios.map((row) => (
            <div key={row.scenario_id} className="clay-row rounded-2xl p-3.5">
              <p className="mb-2 text-[12px] font-bold text-foreground">{row.scenario_id}</p>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3">
                {row.deltas
                  .filter((d) => SHOWN.includes(d.name))
                  .map((d) => (
                    <div key={d.name} className="flex items-baseline justify-between gap-2 text-[11px]">
                      <span className="truncate text-muted-foreground">{d.name}</span>
                      <span className="whitespace-nowrap font-semibold tabular-nums">
                        <span className="text-foreground/70">{show(d.baseline)}</span>
                        <span className="mx-1 text-muted-foreground">→</span>
                        {/* direction is computed from A's perspective; color B */}
                        <span style={{ color: DIRECTION_TONE[d.direction] }}>{show(d.current)}</span>
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          ))}
          {compare.data.scenarios.length === 0 && (
            <p className="text-[11.5px] text-muted-foreground">no scenarios in common between these two suites</p>
          )}
        </div>
      )}
      {left && right && left === right && (
        <p className="text-[11.5px] text-muted-foreground">pick two different suites</p>
      )}
      {compare.isError && (
        <p className="text-[11.5px] font-semibold" style={{ color: "var(--ring-escalated)" }}>
          {String(compare.error)}
        </p>
      )}
    </section>
  );
}
