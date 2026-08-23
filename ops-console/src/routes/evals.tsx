import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  ArrowLeft, CircleCheck, CircleX, Loader2, Radio, ShieldCheck, Trophy,
} from "lucide-react";
import { BenchmarkForm } from "@/components/ops/evals/BenchmarkForm";
import { CompareSuites } from "@/components/ops/evals/CompareSuites";
import { LiveRun } from "@/components/ops/evals/LiveRun";
import { ScorecardCard } from "@/components/ops/evals/ScorecardCard";
import {
  fetchHealth, fetchLatest, fetchRuns, fetchScenarios, fetchSuite,
  fetchSuites, promoteBaseline, startRun,
} from "@/lib/evals-api";

export const Route = createFileRoute("/evals")({
  head: () => ({
    meta: [
      { title: "Rock Scheduler — Eval Lab" },
      {
        name: "description",
        content:
          "Regression checks, scorecards and model benchmarks for the voice shift engine — sandboxed against the eval database.",
      },
    ],
  }),
  component: EvalLab,
});

type Tab = "scorecards" | "benchmark";

function EvalLab() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("scorecards");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [viewSuite, setViewSuite] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [promoted, setPromoted] = useState<string | null>(null);

  const health = useQuery({ queryKey: ["evals-health"], queryFn: fetchHealth, refetchInterval: 4000, retry: false });
  const scenarios = useQuery({ queryKey: ["evals-scenarios"], queryFn: fetchScenarios, enabled: !!health.data });
  const suites = useQuery({ queryKey: ["evals-suites"], queryFn: fetchSuites, refetchInterval: 8000, enabled: !!health.data });
  const latest = useQuery({ queryKey: ["evals-latest"], queryFn: fetchLatest, refetchInterval: 8000, enabled: !!health.data, retry: false });
  const picked = useQuery({
    queryKey: ["evals-suite", viewSuite],
    queryFn: () => fetchSuite(viewSuite!),
    enabled: !!viewSuite && !!health.data,
  });
  const runs = useQuery({ queryKey: ["evals-runs"], queryFn: fetchRuns, refetchInterval: 6000, enabled: !!health.data });

  const offline = health.isError;
  const busy = !!health.data?.busy;
  const suite = viewSuite ? picked.data : latest.data;
  const descriptions = useMemo(
    () => new Map((scenarios.data ?? []).map((s) => [s.scenario_id, s.description])),
    [scenarios.data],
  );

  const begin = async (body: Parameters<typeof startRun>[0]) => {
    setActionError(null);
    try {
      const { run_id } = await startRun(body);
      setActiveRunId(run_id);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  };

  const promote = async () => {
    if (!suite) return;
    setActionError(null);
    try {
      await promoteBaseline(suite.suite_run_id);
      setPromoted(suite.suite_run_id);
      await queryClient.invalidateQueries({ queryKey: ["evals-latest"] });
      await queryClient.invalidateQueries({ queryKey: ["evals-suite"] });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  };

  const gateBlocked = (suite?.gate_blocks?.length ?? 0) > 0;
  const regressions = suite
    ? suite.scorecards.filter((c) => c.deterministic.oracle_verdict === "REGRESSION").length
    : 0;

  return (
    <main className="min-h-screen px-5 py-6 lg:px-8">
      <header className="mx-auto mb-6 grid w-full max-w-[1600px] grid-cols-[minmax(0,1fr)_auto] items-center gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            to="/"
            aria-label="Back to ops console"
            className="clay-pill grid h-11 w-11 shrink-0 place-items-center rounded-2xl text-muted-foreground transition-transform hover:-translate-y-0.5"
          >
            <ArrowLeft className="h-4.5 w-4.5" strokeWidth={2.4} />
          </Link>
          <div className="min-w-0">
            <h1 className="truncate text-[19px] font-bold tracking-tight text-foreground">
              Eval Lab
            </h1>
            <p className="truncate text-[11.5px] text-muted-foreground">
              regression · scorecards · benchmarks — sandboxed on the eval DB, never production
            </p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <div className="clay-pill flex items-center gap-1 rounded-full p-1">
            {(["scorecards", "benchmark"] as Tab[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={`rounded-full px-3 py-1.5 text-[11px] font-semibold transition-all ${
                  tab === t ? "clay-pill-active text-router" : "text-muted-foreground"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
          {busy && health.data?.active_run && activeRunId !== health.data.active_run && (
            <button
              type="button"
              onClick={() => setActiveRunId(health.data!.active_run)}
              className="clay-pill flex items-center gap-2 rounded-full px-4 py-2.5 text-[12px] font-semibold text-router transition-transform hover:-translate-y-0.5"
            >
              <Radio className="h-4 w-4 animate-pulse" strokeWidth={2.4} /> watch live run
            </button>
          )}
          <span className="clay-pill flex items-center gap-2 rounded-full px-4 py-2.5 text-[12px] font-semibold text-foreground">
            <i
              className={`block h-2 w-2 rounded-full ${offline ? "" : "animate-pulse"}`}
              style={{ background: offline ? "var(--ring-escalated)" : busy ? "var(--ring-callout)" : "var(--ring-accepted)" }}
            />
            {offline ? "server offline" : busy ? "running" : "eval server"}
          </span>
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-5">
        {offline && (
          <section className="clay-panel rounded-[32px] p-6 text-center">
            <p className="text-[14px] font-bold text-foreground">The eval server isn't running.</p>
            <p className="mt-1 text-[12px] text-muted-foreground">
              Start it from the engine repo, then this page lights up:
            </p>
            <code className="clay-chip mt-3 inline-block rounded-xl px-4 py-2 font-mono text-[12px] text-router">
              make eval-server
            </code>
          </section>
        )}

        {actionError && (
          <p className="rounded-2xl px-4 py-2.5 text-[12px] font-semibold"
            style={{ background: "color-mix(in oklab, var(--ring-escalated) 10%, transparent)", color: "var(--ring-escalated)" }}>
            {actionError}
          </p>
        )}

        {activeRunId && <LiveRun runId={activeRunId} onClose={() => setActiveRunId(null)} />}

        {!offline && tab === "scorecards" && (
          <>
            {suite && (
              <section className="clay-panel rounded-[32px] p-5">
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2.5">
                      {gateBlocked || regressions ? (
                        <CircleX className="h-5 w-5 shrink-0 text-escalated" strokeWidth={2.6} />
                      ) : (
                        <CircleCheck className="h-5 w-5 shrink-0 text-accepted" strokeWidth={2.6} />
                      )}
                      <span
                        className="clay-chip rounded-full px-3 py-1 text-[10px] font-bold uppercase tracking-[0.1em]"
                        style={{ color: gateBlocked || regressions ? "var(--ring-escalated)" : "var(--ring-accepted)" }}
                      >
                        {gateBlocked ? "gate blocked" : regressions ? "regression" : "merge ok"}
                      </span>
                      <span className="truncate text-[11px] text-muted-foreground">
                        suite {suite.suite_run_id} · git {suite.git_sha} · {suite.engine_profile}
                      </span>
                    </div>
                    <p className="mt-2 text-[13px] font-medium text-foreground/85">{suite.headline}</p>
                    {gateBlocked && (
                      <p className="mt-1.5 text-[11.5px] font-semibold" style={{ color: "var(--ring-escalated)" }}>
                        {suite.gate_blocks.map((b) => `${b.scenario}.${b.metric}: ${String(b.baseline)} → ${String(b.current)}`).join(" · ")}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => begin({ kind: "regression" })}
                      className="clay-pill-active flex items-center gap-2 rounded-full px-5 py-2.5 text-[12px] font-bold text-router transition-transform hover:-translate-y-0.5 disabled:opacity-40"
                    >
                      {busy ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.6} /> : <ShieldCheck className="h-4 w-4" strokeWidth={2.6} />}
                      check regression
                    </button>
                    <button
                      type="button"
                      disabled={busy || regressions > 0 || promoted === suite.suite_run_id}
                      onClick={promote}
                      title="Copy this green suite over evals/baselines/current"
                      className="clay-pill flex items-center gap-2 rounded-full px-4 py-2 text-[11px] font-semibold text-foreground transition-transform hover:-translate-y-0.5 disabled:opacity-40"
                    >
                      <Trophy className="h-3.5 w-3.5 text-callout" strokeWidth={2.4} />
                      {promoted === suite.suite_run_id ? "promoted ✓" : "promote to baseline"}
                    </button>
                  </div>
                </div>
              </section>
            )}

            {suite && (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {suite.scorecards.map((card) => (
                  <ScorecardCard
                    key={card.scenario_id}
                    card={card}
                    deltas={suite.baseline_deltas[card.scenario_id]}
                    description={descriptions.get(card.scenario_id)}
                    busy={busy}
                    onQuickRun={(id) => begin({ kind: "scenario", scenarios: [id], k: 1 })}
                  />
                ))}
              </div>
            )}

            {(suites.data?.length ?? 0) > 0 && (
              <section className="clay-panel rounded-[32px] p-5">
                <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                  Suite history
                </span>
                <div className="mt-3 flex flex-col gap-2">
                  {suites.data!.slice(0, 10).map((s) => {
                    const active = (viewSuite ?? latest.data?.suite_run_id) === s.suite_run_id;
                    return (
                      <button
                        key={s.suite_run_id}
                        type="button"
                        onClick={() => setViewSuite(s.suite_run_id === latest.data?.suite_run_id ? null : s.suite_run_id)}
                        className={`${active ? "clay-card-active" : "clay-row"} grid grid-cols-[auto_auto_minmax(0,1fr)_auto] items-center gap-3 rounded-2xl px-4 py-2.5 text-left transition-transform hover:-translate-y-0.5`}
                      >
                        <span className="font-mono text-[11px] tabular-nums text-foreground">{s.suite_run_id}</span>
                        <span className="clay-chip rounded-full px-2.5 py-0.5 text-[9.5px] font-bold uppercase tracking-[0.1em] text-muted-foreground">
                          {s.label ?? s.kind}
                        </span>
                        <span className="truncate text-[11px] text-muted-foreground">{s.headline}</span>
                        <span
                          className="text-[11px] font-bold tabular-nums"
                          style={{ color: s.regressions ? "var(--ring-escalated)" : "var(--ring-accepted)" }}
                        >
                          {s.pass_k}/{s.n_scenarios} pass^k
                        </span>
                      </button>
                    );
                  })}
                </div>
              </section>
            )}
          </>
        )}

        {!offline && tab === "benchmark" && (
          <>
            <BenchmarkForm
              scenarios={scenarios.data ?? []}
              health={health.data}
              disabled={busy}
              onStarted={(id) => setActiveRunId(id)}
            />
            <CompareSuites suites={suites.data ?? []} />
            {(runs.data?.length ?? 0) > 0 && (
              <section className="clay-panel rounded-[32px] p-5">
                <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                  Runs this session
                </span>
                <div className="mt-3 flex flex-col gap-2">
                  {runs.data!.map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => setActiveRunId(r.id)}
                      className="clay-row grid grid-cols-[auto_auto_minmax(0,1fr)_auto] items-center gap-3 rounded-2xl px-4 py-2.5 text-left transition-transform hover:-translate-y-0.5"
                    >
                      <span className="clay-chip rounded-full px-2.5 py-0.5 text-[9.5px] font-bold uppercase tracking-[0.1em] text-router">
                        {r.kind}
                      </span>
                      <span className="font-mono text-[11px] text-muted-foreground">{r.id}</span>
                      <span className="truncate text-[11px] text-muted-foreground">
                        {(r.config.scenarios ?? ["all scenarios"]).join(", ")}
                        {r.config.k ? ` · k=${r.config.k}` : ""}
                        {Object.keys(r.config.overrides).length
                          ? ` · ${Object.entries(r.config.overrides).map(([k2, v]) => `${k2}=${v}`).join(" ")}`
                          : ""}
                      </span>
                      <span
                        className="text-[11px] font-bold uppercase"
                        style={{
                          color: r.status === "running" ? "var(--ring-calling)"
                            : r.status === "error" || r.verdict === "BLOCKED" || r.verdict === "REGRESSION"
                              ? "var(--ring-escalated)" : "var(--ring-accepted)",
                        }}
                      >
                        {r.status === "done" ? r.verdict ?? "done" : r.status}
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </main>
  );
}
