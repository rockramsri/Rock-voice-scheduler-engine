import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, X } from "lucide-react";
import { fetchSuite, type ScenarioInfo } from "@/lib/evals-api";
import { ScorecardCard } from "./ScorecardCard";
import { Modal, TranscriptModal } from "./TranscriptModal";

/** A run's deck, popped open: the full scorecard grid + per-card transcripts. */
export function SuitePopup({
  suiteId,
  scenarios,
  onClose,
}: {
  suiteId: string;
  scenarios: ScenarioInfo[];
  onClose: () => void;
}) {
  const [transcriptFor, setTranscriptFor] = useState<string | null>(null);
  const suite = useQuery({
    queryKey: ["evals-suite", suiteId],
    queryFn: () => fetchSuite(suiteId),
  });
  const info = new Map(scenarios.map((s) => [s.scenario_id, s]));

  return (
    <>
      <Modal onClose={onClose} wide>
        <header className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-[15px] font-bold tracking-tight text-foreground">
              suite {suiteId}
            </h3>
            {suite.data && (
              <p className="mt-1 text-[12px] text-muted-foreground">{suite.data.headline}</p>
            )}
            {suite.data?.meta?.overrides && Object.keys(suite.data.meta.overrides).length > 0 && (
              <p className="mt-1 text-[11px] font-semibold text-router">
                {Object.entries(suite.data.meta.overrides).map(([k, v]) => `${k}=${v}`).join(" · ")}
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} aria-label="Close suite"
            className="clay-pill grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted-foreground">
            <X className="h-4 w-4" strokeWidth={2.4} />
          </button>
        </header>

        {suite.isLoading && (
          <p className="flex items-center gap-2 text-[12px] text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.4} /> loading scorecards…
          </p>
        )}
        {suite.isError && (
          <p className="text-[12px] font-semibold" style={{ color: "var(--ring-escalated)" }}>
            {String(suite.error)}
          </p>
        )}

        {suite.data && (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {suite.data.scorecards.map((card) => (
              <ScorecardCard
                key={card.scenario_id}
                card={card}
                deltas={suite.data!.baseline_deltas[card.scenario_id]}
                description={info.get(card.scenario_id)?.description}
                turnBudget={info.get(card.scenario_id)?.max_turn_budget}
                onTranscripts={(id) => setTranscriptFor(id)}
              />
            ))}
          </div>
        )}
      </Modal>

      {transcriptFor && (
        <TranscriptModal
          suiteId={suiteId}
          scenarioId={transcriptFor}
          onClose={() => setTranscriptFor(null)}
        />
      )}
    </>
  );
}
