/**
 * Raised event log with story/live/all filters. The list scrolls INSIDE the
 * panel; clicking a row pins its story in the graph.
 */
import { AlertCircle, Check, MessageSquare, PhoneCall, Share2 } from "lucide-react";
import type { StoryEvent } from "@/lib/ops-story";

const ICON = {
  call: PhoneCall,
  sms: MessageSquare,
  whatsapp: MessageSquare,
  router: Share2,
  alert: AlertCircle,
  ok: Check,
};

const TONE: Record<string, string> = {
  call: "var(--ring-calling)",
  sms: "var(--ring-router)",
  whatsapp: "var(--ring-accepted)",
  router: "var(--ring-router)",
  alert: "var(--ring-escalated)",
  ok: "var(--ring-accepted)",
};

export function EventLog({
  events,
  filter,
  onFilter,
  onPick,
}: {
  events: StoryEvent[];
  filter: string;
  onFilter: (f: string) => void;
  onPick?: (shiftId: string) => void;
}) {
  return (
    <section className="clay-panel flex min-h-0 flex-1 flex-col rounded-[28px] p-5">
      <header className="mb-4 flex shrink-0 items-center justify-between gap-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Events
        </h2>
        <div className="flex items-center gap-1.5">
          {["this story", "live", "all"].map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => onFilter(f)}
              className={`rounded-full px-3 py-1.5 text-[11px] font-semibold transition-all ${
                filter === f ? "clay-pill-active text-router" : "clay-pill text-muted-foreground"
              }`}
            >
              {f}
            </button>
          ))}
          <span className="ml-2 text-[11px] font-medium text-muted-foreground">
            {events.length} events
          </span>
        </div>
      </header>

      <ol className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">
        {events.map((e) => {
          const Icon = ICON[e.tag];
          return (
            <li key={e.id}>
              <button
                type="button"
                onClick={() => e.shiftId && onPick?.(e.shiftId)}
                className="clay-row animate-row-in flex w-full items-center gap-3 rounded-2xl px-3.5 py-3 text-left"
              >
                <span
                  className="grid h-8 w-8 shrink-0 place-items-center rounded-xl"
                  style={{ background: `color-mix(in oklab, ${TONE[e.tag]} 16%, transparent)` }}
                >
                  <Icon className="h-4 w-4" style={{ color: TONE[e.tag] }} strokeWidth={2.4} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-foreground">
                    {e.title}
                  </span>
                  <span className="block truncate text-[11.5px] text-muted-foreground">
                    {e.detail}
                  </span>
                </span>
                <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                  {e.time}
                </span>
              </button>
            </li>
          );
        })}
        {events.length === 0 && (
          <li className="py-8 text-center text-[12.5px] text-muted-foreground">
            {filter === "this story"
              ? "No events for this story yet."
              : "Waiting for activity…"}
          </li>
        )}
      </ol>
    </section>
  );
}
