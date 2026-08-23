import { useEffect, useMemo, useRef, useState } from "react";
import { CircleCheck, CircleX, Loader2, Wrench, X } from "lucide-react";
import { EVALS_API, type RunEvent } from "@/lib/evals-api";

interface TrialView {
  turns: { role: string; text: string }[];
  tools: { name: string; args: unknown }[];
  order: { type: "turn" | "tool"; index: number }[];
  verdict?: string;
  ttfa_ms?: number;
  failed?: string[];
  judge?: boolean | null;
}

interface ScenarioView {
  id: string;
  channel?: string;
  k: number;
  trials: Map<number, TrialView>;
  done: boolean;
}

interface RunView {
  status: string;
  stages: { name: string; status: string; summary?: string }[];
  logs: string[];
  scenarios: Map<string, ScenarioView>;
  verdict?: string;
  suiteId?: string;
  error?: string;
  gateBlocks: { scenario: string; metric: string }[];
}

function fold(events: RunEvent[]): RunView {
  const view: RunView = { status: "running", stages: [], logs: [], scenarios: new Map(), gateBlocks: [] };
  for (const e of events) {
    const sid = e.scenario as string | undefined;
    const idx = e.run_idx as number | undefined;
    const scenario = sid ? view.scenarios.get(sid) : undefined;
    const trial = scenario && idx !== undefined ? scenario.trials.get(idx) : undefined;
    switch (e.kind) {
      case "stage": {
        const existing = view.stages.find((s) => s.name === e.name);
        if (existing) {
          existing.status = e.status as string;
          existing.summary = e.summary as string | undefined;
        } else {
          view.stages.push({ name: e.name as string, status: e.status as string });
        }
        break;
      }
      case "log":
        view.logs.push(e.line as string);
        if (view.logs.length > 200) view.logs.shift();
        break;
      case "scenario_start":
        view.scenarios.set(sid!, {
          id: sid!, channel: e.channel as string, k: (e.k as number) ?? 1,
          trials: new Map(), done: false,
        });
        break;
      case "run_start":
        view.scenarios.get(sid!)?.trials.set(idx!, { turns: [], tools: [], order: [] });
        break;
      case "turn":
        if (trial) {
          trial.turns.push({ role: e.role as string, text: e.text as string });
          trial.order.push({ type: "turn", index: trial.turns.length - 1 });
        }
        break;
      case "tool":
        if (trial) {
          trial.tools.push({ name: e.name as string, args: e.args });
          trial.order.push({ type: "tool", index: trial.tools.length - 1 });
        }
        break;
      case "run_result":
        if (trial) {
          trial.verdict = e.verdict as string;
          trial.ttfa_ms = e.ttfa_ms as number;
          trial.failed = e.failed as string[];
          trial.judge = e.judge_all_yes as boolean | null;
        }
        break;
      case "scenario_done":
        if (scenario) scenario.done = true;
        break;
      case "run_done":
        view.status = "done";
        view.verdict = e.verdict as string;
        view.suiteId = e.suite_id as string;
        view.gateBlocks = (e.gate_blocks as RunView["gateBlocks"]) ?? [];
        break;
      case "run_error":
        view.status = "error";
        view.error = e.error as string;
        break;
    }
  }
  return view;
}

const VERDICT_TONE: Record<string, string> = {
  GREEN: "var(--ring-accepted)",
  REGRESSION: "var(--ring-escalated)",
  BLOCKED: "var(--ring-escalated)",
};

export function LiveRun({ runId, onClose }: { runId: string; onClose: () => void }) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [picked, setPicked] = useState<{ scenario: string; idx: number } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setEvents([]);
    setPicked(null);
    const source = new EventSource(`${EVALS_API}/api/runs/${runId}/stream`);
    source.onmessage = (msg) => {
      const event = JSON.parse(msg.data as string) as RunEvent;
      setEvents((prev) => [...prev, event]);
    };
    source.addEventListener("end", () => source.close());
    source.onerror = () => source.close();
    return () => source.close();
  }, [runId]);

  const view = useMemo(() => fold(events), [events]);

  // Follow the newest trial unless the user picked one.
  const active = useMemo(() => {
    if (picked) return picked;
    let last: { scenario: string; idx: number } | null = null;
    for (const s of view.scenarios.values()) {
      for (const idx of s.trials.keys()) last = { scenario: s.id, idx };
    }
    return last;
  }, [picked, view]);

  const activeTrial = active
    ? view.scenarios.get(active.scenario)?.trials.get(active.idx)
    : undefined;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [events.length]);

  return (
    <section className="clay-panel rounded-[32px] p-5">
      <header className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          {view.status === "running" ? (
            <Loader2 className="h-4 w-4 animate-spin text-router" strokeWidth={2.6} />
          ) : view.status === "error" || view.verdict === "BLOCKED" || view.verdict === "REGRESSION" ? (
            <CircleX className="h-4 w-4 text-escalated" strokeWidth={2.6} />
          ) : (
            <CircleCheck className="h-4 w-4 text-accepted" strokeWidth={2.6} />
          )}
          <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            {view.status === "running" ? "Simulation running" : "Simulation finished"}
          </span>
          {view.verdict && (
            <span className="clay-chip rounded-full px-3 py-1 text-[10px] font-bold uppercase tracking-[0.1em]"
              style={{ color: VERDICT_TONE[view.verdict] ?? "var(--ring-callout)" }}>
              {view.verdict}
            </span>
          )}
          {view.suiteId && (
            <span className="text-[10.5px] tabular-nums text-muted-foreground">suite {view.suiteId}</span>
          )}
        </div>
        <button type="button" onClick={onClose} aria-label="Close live view"
          className="clay-pill grid h-8 w-8 place-items-center rounded-full text-muted-foreground transition-transform hover:-translate-y-0.5">
          <X className="h-4 w-4" strokeWidth={2.4} />
        </button>
      </header>

      {view.error && (
        <p className="mb-3 rounded-2xl px-3 py-2 text-[12px] font-semibold"
          style={{ background: "color-mix(in oklab, var(--ring-escalated) 10%, transparent)", color: "var(--ring-escalated)" }}>
          {view.error}
        </p>
      )}

      {view.stages.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {view.stages.map((stage) => (
            <span key={stage.name} className="clay-chip flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-semibold"
              style={{
                color: stage.status === "passed" ? "var(--ring-accepted)"
                  : stage.status === "failed" ? "var(--ring-escalated)" : "var(--ring-router)",
              }}>
              {stage.status === "running" && <Loader2 className="h-3 w-3 animate-spin" strokeWidth={2.6} />}
              {stage.name}{stage.summary ? ` — ${stage.summary}` : ""}
            </span>
          ))}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="flex flex-col gap-2.5">
          {[...view.scenarios.values()].map((scenario) => (
            <div key={scenario.id} className="clay-row rounded-2xl px-3.5 py-3">
              <p className="truncate text-[12px] font-bold text-foreground">{scenario.id}</p>
              <div className="mt-2 flex items-center gap-1.5">
                {Array.from({ length: scenario.k }).map((_, i) => {
                  const trial = scenario.trials.get(i);
                  const isActive = active?.scenario === scenario.id && active.idx === i;
                  const bg = !trial ? "color-mix(in oklab, var(--foreground) 10%, transparent)"
                    : !trial.verdict ? "var(--ring-calling)"
                    : trial.verdict === "CONFIRMED_CORRECT" ? "var(--ring-accepted)" : "var(--ring-escalated)";
                  return (
                    <button key={i} type="button"
                      onClick={() => setPicked({ scenario: scenario.id, idx: i })}
                      aria-label={`${scenario.id} trial ${i}`}
                      className={`h-3.5 w-3.5 rounded-full transition-transform hover:scale-125 ${
                        trial && !trial.verdict ? "animate-pip-breathe" : ""
                      }`}
                      style={{ background: bg, outline: isActive ? "2px solid var(--ring-router)" : "none", outlineOffset: 1.5 }}
                    />
                  );
                })}
                <span className="ml-auto text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  {scenario.channel}
                </span>
              </div>
            </div>
          ))}
          {view.scenarios.size === 0 && view.status === "running" && (
            <p className="px-1 text-[11.5px] text-muted-foreground">warming up…</p>
          )}
        </div>

        <div ref={scrollRef} className="clay-canvas dot-grid max-h-[420px] min-h-[220px] overflow-y-auto rounded-[24px] p-4">
          {activeTrial ? (
            <div className="flex flex-col gap-2.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                {active!.scenario} · trial {active!.idx}
              </p>
              {activeTrial.order.map((entry, i) =>
                entry.type === "tool" ? (
                  <div key={i} className="flex justify-center">
                    <span className="clay-chip flex items-center gap-1.5 rounded-full px-3 py-1 text-[10.5px] font-bold text-router">
                      <Wrench className="h-3 w-3" strokeWidth={2.6} />
                      {activeTrial.tools[entry.index]!.name}
                      {activeTrial.tools[entry.index]!.args
                        ? ` ${JSON.stringify(activeTrial.tools[entry.index]!.args)}`
                        : ""}
                    </span>
                  </div>
                ) : (
                  <div key={i} className={`flex ${activeTrial.turns[entry.index]!.role === "agent" ? "justify-end" : "justify-start"}`}>
                    <div className="max-w-[78%] rounded-2xl px-3.5 py-2 text-[12.5px] leading-relaxed animate-row-in"
                      style={activeTrial.turns[entry.index]!.role === "agent"
                        ? { background: "color-mix(in oklab, var(--ring-router) 12%, white)", color: "var(--foreground)" }
                        : { background: "oklch(0.985 0.002 260)", boxShadow: "var(--clay-out)", color: "var(--foreground)" }}>
                      <p className="mb-0.5 text-[9.5px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
                        {activeTrial.turns[entry.index]!.role === "agent" ? "rock (agent)" : "nurse (persona)"}
                      </p>
                      {activeTrial.turns[entry.index]!.text}
                    </div>
                  </div>
                ),
              )}
              {activeTrial.verdict && (
                <div className="mt-1 flex items-center gap-2">
                  <span className="clay-chip rounded-full px-3 py-1 text-[10px] font-bold uppercase"
                    style={{ color: activeTrial.verdict === "CONFIRMED_CORRECT" ? "var(--ring-accepted)" : "var(--ring-escalated)" }}>
                    {activeTrial.verdict}
                  </span>
                  {activeTrial.ttfa_ms !== undefined && activeTrial.ttfa_ms !== null && (
                    <span className="text-[10.5px] tabular-nums text-muted-foreground">ttfa {activeTrial.ttfa_ms}ms</span>
                  )}
                  {activeTrial.judge !== null && activeTrial.judge !== undefined && (
                    <span className="text-[10.5px] font-semibold"
                      style={{ color: activeTrial.judge ? "var(--ring-accepted)" : "var(--ring-callout)" }}>
                      judge {activeTrial.judge ? "yes" : "no"}
                    </span>
                  )}
                </div>
              )}
              {activeTrial.failed?.map((line) => (
                <p key={line} className="text-[11px] font-semibold" style={{ color: "var(--ring-escalated)" }}>
                  FAIL {line}
                </p>
              ))}
            </div>
          ) : view.logs.length > 0 ? (
            <div className="font-mono text-[10.5px] leading-relaxed text-muted-foreground">
              {view.logs.slice(-40).map((line, i) => (
                <p key={i}>{line}</p>
              ))}
            </div>
          ) : (
            <p className="text-[11.5px] text-muted-foreground">waiting for the first turn…</p>
          )}
        </div>
      </div>
    </section>
  );
}
