import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { CircleCheck, CircleX, Loader2, Wrench, X } from "lucide-react";
import { fetchTranscripts, type Trial } from "@/lib/evals-api";
import { scenarioAccent, shortName, VERDICT_TONE } from "./cardStyle";

/** Generic clay overlay used by the transcript + deck popups. */
export function Modal({
  onClose,
  children,
  z = 50,
  wide,
}: {
  onClose: () => void;
  children: ReactNode;
  z?: number;
  wide?: boolean;
}) {
  return (
    <div
      className="fixed inset-0 grid place-items-center p-4"
      style={{ zIndex: z, background: "oklch(0.3 0.03 262 / 0.35)", backdropFilter: "blur(3px)" }}
      onClick={onClose}
    >
      <div
        className={`clay-panel max-h-[88vh] w-full overflow-y-auto rounded-[32px] p-5 ${wide ? "max-w-[1200px]" : "max-w-[760px]"}`}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

function Bubbles({ trial }: { trial: Trial }) {
  const order: { type: "turn" | "tool"; i: number }[] = [];
  // Interleave: tools between the user turn and agent reply is unknown from disk,
  // so show turns in order and pin tool chips after the user turn that triggered them.
  const turns = trial.turns ?? [];
  const tools = trial.tools ?? [];
  let toolCursor = 0;
  turns.forEach((t, i) => {
    order.push({ type: "turn", i });
    if (t.role === "user" && toolCursor < tools.length && turns[i + 1]?.role === "agent") {
      order.push({ type: "tool", i: toolCursor });
      toolCursor += 1;
    }
  });
  for (; toolCursor < tools.length; toolCursor += 1) order.push({ type: "tool", i: toolCursor });

  return (
    <div className="flex flex-col gap-2.5">
      {order.map((entry, idx) =>
        entry.type === "tool" ? (
          <div key={`tool-${idx}`} className="flex justify-center">
            <span className="clay-chip flex items-center gap-1.5 rounded-full px-3 py-1 text-[10.5px] font-bold text-router">
              <Wrench className="h-3 w-3" strokeWidth={2.6} />
              {tools[entry.i]!.name}
              {tools[entry.i]!.args ? ` ${JSON.stringify(tools[entry.i]!.args)}` : ""}
            </span>
          </div>
        ) : (
          <div key={`turn-${idx}`}
            className={`flex ${turns[entry.i]!.role === "agent" ? "justify-end" : "justify-start"}`}>
            <div className="max-w-[80%] rounded-2xl px-3.5 py-2 text-[12.5px] leading-relaxed"
              style={turns[entry.i]!.role === "agent"
                ? { background: "color-mix(in oklab, var(--ring-router) 12%, white)" }
                : { background: "oklch(0.985 0.002 260)", boxShadow: "var(--clay-out)" }}>
              <p className="mb-0.5 text-[9.5px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
                {turns[entry.i]!.role === "agent" ? "rock (agent)" : "nurse (persona)"}
              </p>
              {turns[entry.i]!.text}
            </div>
          </div>
        ),
      )}
      {turns.length === 0 && (
        <p className="text-[11.5px] text-muted-foreground">
          no transcript stored for this trial (older run — only the last trial of pre-update suites kept artifacts)
        </p>
      )}
    </div>
  );
}

export function TranscriptModal({
  suiteId,
  scenarioId,
  onClose,
}: {
  suiteId: string;
  scenarioId: string;
  onClose: () => void;
}) {
  const [picked, setPicked] = useState(0);
  const query = useQuery({
    queryKey: ["evals-transcripts", suiteId, scenarioId],
    queryFn: () => fetchTranscripts(suiteId, scenarioId),
  });
  const trials = query.data?.trials ?? [];
  const trial = trials[Math.min(picked, Math.max(0, trials.length - 1))];

  return (
    <Modal onClose={onClose} z={60}>
      <header className="mb-4 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl"
            style={{
              color: scenarioAccent(scenarioId),
              background: `color-mix(in oklab, ${scenarioAccent(scenarioId)} 12%, white)`,
            }}>
            <span className="text-[13px] font-black">{trials.length || "…"}</span>
          </span>
          <div className="min-w-0">
            <h3 className="truncate text-[15px] font-bold capitalize tracking-tight text-foreground">
              {shortName(scenarioId)} — transcripts
            </h3>
            <p className="truncate text-[11px] text-muted-foreground">
              suite {suiteId} · every trial, straight from the evidence folders
            </p>
          </div>
        </div>
        <button type="button" onClick={onClose} aria-label="Close transcripts"
          className="clay-pill grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted-foreground">
          <X className="h-4 w-4" strokeWidth={2.4} />
        </button>
      </header>

      {query.isLoading && (
        <p className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.4} /> loading evidence…
        </p>
      )}
      {query.isError && (
        <p className="text-[12px] font-semibold" style={{ color: "var(--ring-escalated)" }}>
          {String(query.error)}
        </p>
      )}

      {trials.length > 0 && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            {trials.map((t, i) => {
              const ok = t.verdict === "CONFIRMED_CORRECT";
              const known = t.verdict !== undefined && t.verdict !== null;
              return (
                <button key={t.folder} type="button" onClick={() => setPicked(i)}
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-bold transition-all ${
                    i === picked ? "clay-pill-active text-router" : "clay-pill text-muted-foreground"
                  }`}>
                  {known ? (
                    ok ? <CircleCheck className="h-3.5 w-3.5" style={{ color: "var(--ring-accepted)" }} strokeWidth={2.6} />
                      : <CircleX className="h-3.5 w-3.5" style={{ color: "var(--ring-escalated)" }} strokeWidth={2.6} />
                  ) : null}
                  trial {t.run_idx}
                </button>
              );
            })}
            {trial?.ttfa_ms !== undefined && trial?.ttfa_ms !== null && (
              <span className="ml-auto text-[11px] tabular-nums text-muted-foreground">
                first answer {Math.round(trial.ttfa_ms)}ms
              </span>
            )}
          </div>

          {trial && (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
              <div className="clay-canvas dot-grid max-h-[52vh] overflow-y-auto rounded-[24px] p-4">
                <Bubbles trial={trial} />
                {trial.verdict && (
                  <div className="mt-3 flex items-center gap-2">
                    <span className="clay-chip rounded-full px-3 py-1 text-[10px] font-bold uppercase"
                      style={{ color: VERDICT_TONE[trial.verdict] ?? "var(--ring-callout)" }}>
                      {trial.verdict}
                    </span>
                    {trial.failed?.map((line) => (
                      <span key={line} className="text-[10.5px] font-semibold" style={{ color: "var(--ring-escalated)" }}>
                        {line}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <aside className="flex flex-col gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                  LLM judge{trial.judge?.model ? ` · ${trial.judge.model.split(":").pop()}` : ""}
                </span>
                {(trial.judge?.answers ?? []).map((a) => (
                  <div key={a.question} className="clay-row rounded-2xl p-3">
                    <p className="text-[11px] font-semibold text-foreground/85">{a.question}</p>
                    <p className="mt-1 text-[10.5px] font-bold uppercase"
                      style={{ color: a.verdict ? "var(--ring-accepted)" : "var(--ring-escalated)" }}>
                      {a.verdict ? "yes" : "no"}
                    </p>
                    <p className="mt-1 text-[10.5px] italic leading-relaxed text-muted-foreground">
                      “{a.quote}”
                    </p>
                  </div>
                ))}
                {!trial.judge && (
                  <p className="text-[11px] text-muted-foreground">no judge rubric on this scenario</p>
                )}
              </aside>
            </div>
          )}
        </>
      )}
      {!query.isLoading && trials.length === 0 && !query.isError && (
        <p className="text-[12px] text-muted-foreground">no evidence folders found for this card</p>
      )}
    </Modal>
  );
}
