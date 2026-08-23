import { useState } from "react";
import { FlaskConical, Loader2 } from "lucide-react";
import { startRun, type HealthInfo, type ScenarioInfo } from "@/lib/evals-api";

const MODEL_FIELDS = [
  { key: "llm_model", label: "voice agent LLM", hint: "the model taking the calls",
    suggestions: ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o"] },
  { key: "workplane_model", label: "SMS agent model", hint: "pydantic-ai model string",
    suggestions: ["openai:gpt-4.1-mini", "openai:gpt-4.1", "openai:gpt-4o-mini"] },
  { key: "persona_model", label: "persona model", hint: "plays the nurse",
    suggestions: ["openai:gpt-4.1-mini", "openai:gpt-4.1"] },
  { key: "judge_model", label: "judge model", hint: "grades transcripts",
    suggestions: ["anthropic:claude-sonnet-4-6", "openai:gpt-4.1-mini", "google:gemini-3.5-flash"] },
] as const;

export function BenchmarkForm({
  scenarios,
  health,
  disabled,
  onStarted,
}: {
  scenarios: ScenarioInfo[];
  health: HealthInfo | undefined;
  disabled: boolean;
  onStarted: (runId: string) => void;
}) {
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [k, setK] = useState(3);
  const [label, setLabel] = useState("");
  const [models, setModels] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const submit = async () => {
    setError(null);
    setStarting(true);
    try {
      const overrides: Record<string, string> = {};
      for (const [key, value] of Object.entries(models)) {
        if (value.trim()) overrides[key] = value.trim();
      }
      if (label.trim()) overrides.label = label.trim();
      const { run_id } = await startRun({
        kind: "benchmark",
        scenarios: picked.size ? [...picked] : undefined,
        k,
        overrides,
      });
      onStarted(run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  };

  return (
    <section className="clay-panel rounded-[32px] p-5">
      <header className="mb-1 flex items-center gap-2">
        <FlaskConical className="h-4 w-4 text-router" strokeWidth={2.4} />
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Experiment sandbox
        </span>
      </header>
      <p className="mb-4 text-[11.5px] text-muted-foreground">
        Swap any model per area and run the same graded scenarios. Overrides live for one
        run against the eval database — production config never changes.
      </p>

      <div className="mb-4 grid gap-3 sm:grid-cols-2">
        {MODEL_FIELDS.map((field) => (
          <label key={field.key} className="block">
            <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              {field.label}
            </span>
            <input
              list={`suggest-${field.key}`}
              value={models[field.key] ?? ""}
              onChange={(e) => setModels((m) => ({ ...m, [field.key]: e.target.value }))}
              placeholder={health?.defaults[field.key] ?? field.hint}
              className="clay-input mt-1 w-full rounded-xl px-3 py-2 text-[12px] font-medium"
            />
            <datalist id={`suggest-${field.key}`}>
              {field.suggestions.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          </label>
        ))}
      </div>

      <div className="mb-4">
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          scenarios (empty = all)
        </span>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {scenarios.map((s) => (
            <button
              key={s.scenario_id}
              type="button"
              onClick={() => toggle(s.scenario_id)}
              className={`rounded-full px-3 py-1.5 text-[11px] font-semibold transition-all ${
                picked.has(s.scenario_id) ? "clay-pill-active text-router" : "clay-pill text-muted-foreground"
              }`}
            >
              {s.scenario_id.replace(/^co-\d+-/, "")}
              <span className="ml-1 opacity-60">{s.channel}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="block">
          <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            trials (pass^k)
          </span>
          <div className="clay-pill mt-1 flex items-center gap-1 rounded-full p-1">
            {[1, 2, 3, 5].map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setK(n)}
                className={`rounded-full px-3 py-1.5 text-[11px] font-bold tabular-nums transition-all ${
                  k === n ? "clay-pill-active text-router" : "text-muted-foreground"
                }`}
              >
                {n}
              </button>
            ))}
          </div>
        </label>
        <label className="block min-w-[180px] flex-1">
          <span className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            experiment label
          </span>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. gpt-4.1 generator"
            className="clay-input mt-1 w-full rounded-xl px-3 py-2 text-[12px] font-medium"
          />
        </label>
        <button
          type="button"
          disabled={disabled || starting}
          onClick={submit}
          className="clay-pill-active flex items-center gap-2 rounded-full px-5 py-2.5 text-[12px] font-bold text-router transition-transform hover:-translate-y-0.5 disabled:opacity-40"
        >
          {starting ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.6} /> : <FlaskConical className="h-4 w-4" strokeWidth={2.6} />}
          run experiment
        </button>
      </div>
      {disabled && (
        <p className="mt-2 text-[11px] font-semibold" style={{ color: "var(--ring-callout)" }}>
          a run is already in progress — one experiment at a time
        </p>
      )}
      {error && (
        <p className="mt-2 text-[11px] font-semibold" style={{ color: "var(--ring-escalated)" }}>
          {error}
        </p>
      )}
    </section>
  );
}
