import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, FastForward, Pause, Phone, Play, Radio, RotateCcw } from "lucide-react";
import { StoryGraph } from "@/components/ops/StoryGraph";
import { EventLog } from "@/components/ops/EventLog";
import { WorkflowRail } from "@/components/ops/WorkflowRail";
import { useLiveData } from "@/hooks/use-live-data";
import { AGENCY_PHONE, supabase } from "@/lib/supabase";
import { shiftCaption, toGraph, toStoryEvents, type FlowMode } from "@/lib/live-story";
import { buildStory, type Outcome } from "@/lib/ops-story";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Rock Scheduler — Voice Shift Ops Console" },
      {
        name: "description",
        content:
          "Live ops console for AI voice shift backfill: callout lineage graph, ladder outreach across SMS, WhatsApp and calls, and an audited event stream.",
      },
    ],
  }),
  component: Index,
});

const STATUS_TONE: Record<string, string> = {
  callout: "var(--ring-callout)",
  offers_out: "var(--ring-router)",
  filled: "var(--ring-accepted)",
  escalated: "var(--ring-escalated)",
  scheduled: "var(--edge-idle)",
};

type Mode = "live" | "demo";

function Index() {
  const data = useLiveData();
  const [mode, setMode] = useState<Mode>("live");
  const [flow, setFlow] = useState<FlowMode>("detailed");
  const [filter, setFilter] = useState("this story");
  const [selected, setSelected] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [ffBusy, setFfBusy] = useState(false);
  const mountedAt = useRef(new Date().toISOString()).current;

  // Demo player state (scripted beats from the design reference).
  const [outcome, setOutcome] = useState<Outcome>("accept");
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const story = useMemo(() => buildStory(outcome), [outcome]);
  const last = story.length - 1;
  const beat = story[Math.min(step, last)]!;

  useEffect(() => {
    if (mode !== "demo" || !playing) return;
    if (step >= last) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setStep((s) => s + 1), 2200);
    return () => clearTimeout(t);
  }, [mode, playing, step, last]);

  const nursesById = useMemo(
    () => new Map(data.nurses.map((n) => [n.id, n])), [data.nurses]);

  const latestStory = useMemo(() => {
    const ev = data.events.find((e) => e.shift_id);
    return ev?.shift_id ?? data.shifts.find((s) => s.callout_at)?.id ?? null;
  }, [data.events, data.shifts]);

  const focusedId = pinned ?? latestStory;
  const shift = data.shifts.find((s) => s.id === focusedId) ?? null;
  const liveGraph = useMemo(
    () => (shift
      ? toGraph(shift, data.offers.filter((o) => o.shift_id === shift.id), nursesById,
                data.events.filter((e) => e.shift_id === shift.id), flow)
      : null),
    [shift, data.offers, nursesById, data.events, flow]);

  const allLiveEvents = useMemo(
    () => toStoryEvents(data.events, nursesById), [data.events, nursesById]);
  const shownEvents = useMemo(() => {
    if (mode === "demo") {
      const demoEvents = story.slice(0, step + 1).flatMap((b) => b.events).reverse();
      return filter === "live" ? demoEvents.slice(0, 3) : demoEvents;
    }
    if (filter === "this story") return allLiveEvents.filter((e) => !!focusedId && e.shiftId === focusedId);
    if (filter === "live") {
      const cutoff = new Date(mountedAt).toLocaleTimeString([], { hour12: false });
      return allLiveEvents.filter((e) => e.time >= cutoff);
    }
    return allLiveEvents;
  }, [mode, story, step, allLiveEvents, filter, focusedId, mountedAt]);

  const graphBeat = mode === "demo"
    ? beat
    : { key: shift?.id ?? "empty", caption: "", events: [],
        nodes: liveGraph?.nodes ?? [], edges: liveGraph?.edges ?? [] };

  const caption = mode === "demo"
    ? beat.caption
    : shift ? shiftCaption(shift)
    : `Quiet — call ${AGENCY_PHONE} as a registered nurse to start a story`;

  const fastForward = async () => {
    setFfBusy(true);
    try {
      await supabase.rpc("ff_shifts");
    } finally {
      setTimeout(() => setFfBusy(false), 900);
    }
  };

  return (
    <main className="flex h-screen flex-col overflow-hidden px-5 py-6 lg:px-8">
      <header className="mx-auto mb-6 grid w-full max-w-[1600px] shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl"
            style={{ boxShadow: "var(--clay-out)" }}
          >
            <span className="flex items-end gap-[3px]">
              <i className="block h-2 w-[3px] rounded-full bg-router" />
              <i className="block h-4 w-[3px] rounded-full bg-calling" />
              <i className="block h-3 w-[3px] rounded-full bg-router" />
            </span>
          </span>
          <div className="min-w-0">
            <h1 className="truncate text-[19px] font-bold tracking-tight text-foreground">
              Rock Scheduler
            </h1>
            <p className="truncate text-[11.5px] text-muted-foreground">
              voice shift ops · Rockram Home Health Care
            </p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <a
            href={`tel:${AGENCY_PHONE.replace(/[^+\d]/g, "")}`}
            title="The agency line — call it as a registered nurse to start a story"
            className="clay-pill flex items-center gap-2 rounded-full px-4 py-2.5 text-[12px] font-semibold text-foreground transition-transform hover:-translate-y-0.5"
          >
            <Phone className="h-4 w-4 text-accepted" strokeWidth={2.4} />
            <span className="tabular-nums">{AGENCY_PHONE}</span>
          </a>
          <div className="clay-pill flex items-center gap-1 rounded-full p-1">
            {(["live", "demo"] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`rounded-full px-3 py-1.5 text-[11px] font-semibold transition-all ${
                  mode === m ? "clay-pill-active text-router" : "text-muted-foreground"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
          {mode === "live" && pinned && (
            <button
              type="button"
              onClick={() => setPinned(null)}
              className="clay-pill flex items-center gap-2 rounded-full px-4 py-2.5 text-[12px] font-semibold text-router transition-transform hover:-translate-y-0.5"
            >
              <Radio className="h-4 w-4" strokeWidth={2.4} /> back to live
            </button>
          )}
          {mode === "live" ? (
            <button
              type="button"
              onClick={fastForward}
              className={`flex items-center gap-2 rounded-full px-4 py-2.5 text-[12px] font-semibold transition-transform hover:-translate-y-0.5 ${
                ffBusy ? "clay-pill-active text-router" : "clay-pill text-foreground"
              }`}
            >
              <FastForward className="h-4 w-4 text-router" strokeWidth={2.4} />
              {ffBusy ? "skipping waits…" : "fast-forward"}
            </button>
          ) : (
            <div className="clay-pill flex items-center gap-1 rounded-full p-1">
              {(["accept", "escalate"] as Outcome[]).map((o) => (
                <button
                  key={o}
                  type="button"
                  onClick={() => {
                    setOutcome(o);
                    setStep((s) => Math.min(s, 4));
                  }}
                  className={`rounded-full px-3 py-1.5 text-[11px] font-semibold transition-all ${
                    outcome === o ? "clay-pill-active text-router" : "text-muted-foreground"
                  }`}
                >
                  {o === "accept" ? "best case" : "worst case"}
                </button>
              ))}
            </div>
          )}
          <span className="clay-pill flex items-center gap-2 rounded-full px-4 py-2.5 text-[12px] font-semibold text-foreground">
            <i className="block h-2 w-2 animate-pulse rounded-full bg-accepted" /> live
          </span>
        </div>
      </header>

      <div className="mx-auto grid w-full max-w-[1600px] min-h-0 flex-1 gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
        <WorkflowRail workflows={data.workflows} nurses={data.nurses}
                      agencyId={data.agencyId} refresh={data.refresh} />

        <div className="flex min-h-0 min-w-0 flex-col gap-5">
          <section className="clay-panel shrink-0 rounded-[32px] p-5">
            <div className="mb-4 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4">
              <div className="min-w-0">
                <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                  Story
                </span>
                <p className="mt-1 truncate text-[13px] font-medium text-foreground/80">
                  {caption}
                </p>
              </div>
              {mode === "demo" ? (
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setStep((s) => Math.max(0, s - 1))}
                    className="clay-pill grid h-9 w-9 place-items-center rounded-full text-muted-foreground"
                    aria-label="Previous beat"
                  >
                    <ChevronLeft className="h-4 w-4" strokeWidth={2.4} />
                  </button>
                  <button
                    type="button"
                    onClick={() => setPlaying((p) => !p)}
                    className="clay-pill-active flex items-center gap-2 rounded-full px-4 py-2 text-[12px] font-semibold text-router"
                  >
                    {playing ? (
                      <Pause className="h-4 w-4" strokeWidth={2.6} />
                    ) : (
                      <Play className="h-4 w-4" strokeWidth={2.6} />
                    )}
                    {playing ? "pause" : "play"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setStep(0);
                      setPlaying(false);
                      setSelected(null);
                    }}
                    className="clay-pill grid h-9 w-9 place-items-center rounded-full text-muted-foreground"
                    aria-label="Reset story"
                  >
                    <RotateCcw className="h-4 w-4" strokeWidth={2.4} />
                  </button>
                </div>
              ) : (
                <div className="flex shrink-0 items-center gap-2">
                  <div className="clay-pill flex items-center gap-1 rounded-full p-1">
                    {(["detailed", "normal"] as FlowMode[]).map((f) => (
                      <button
                        key={f}
                        type="button"
                        onClick={() => setFlow(f)}
                        className={`rounded-full px-3 py-1.5 text-[11px] font-semibold transition-all ${
                          flow === f ? "clay-pill-active text-router" : "text-muted-foreground"
                        }`}
                      >
                        {f} flow
                      </button>
                    ))}
                  </div>
                  {shift && (
                    <span
                      className="clay-chip rounded-full px-3 py-1.5 text-[11px] font-bold uppercase tracking-[0.1em]"
                      style={{ color: STATUS_TONE[shift.status] ?? "var(--ring-router)" }}
                    >
                      {shift.status.replaceAll("_", " ")}
                    </span>
                  )}
                </div>
              )}
            </div>

            <StoryGraph beat={graphBeat} selected={selected} onSelect={setSelected} />

            {mode === "demo" && (
              <div className="mt-4 flex items-center gap-2">
                {story.map((b, i) => (
                  <button
                    key={b.key}
                    type="button"
                    onClick={() => setStep(i)}
                    aria-label={b.key}
                    className="h-1.5 flex-1 rounded-full transition-all"
                    style={{
                      background:
                        i <= step
                          ? "var(--ring-router)"
                          : "color-mix(in oklab, var(--foreground) 8%, transparent)",
                    }}
                  />
                ))}
              </div>
            )}
          </section>

          <EventLog events={shownEvents} filter={filter} onFilter={setFilter}
                    onPick={(shiftId) => mode === "live" && setPinned(shiftId)} />
        </div>
      </div>
    </main>
  );
}
