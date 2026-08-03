// Layout: left = workflow registration; right = live story graph (60%)
// over the event feed (40%). The graph follows the newest activity until
// an operator pins a story; Fast-forward skips ladder waits for demos.

import { useMemo, useRef, useState } from "react";
import EventLog, { type Filter } from "./components/EventLog";
import FlowGraph from "./components/FlowGraph";
import WorkflowPanel from "./components/WorkflowPanel";
import { useLiveData } from "./hooks";
import { supabase } from "./supabase";

export default function App() {
  const data = useLiveData();
  const [pinnedShift, setPinnedShift] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("story");
  const [ffBusy, setFfBusy] = useState(false);
  const mountedAt = useRef(new Date().toISOString()).current;

  const nursesById = useMemo(
    () => new Map(data.nurses.map((n) => [n.id, n])), [data.nurses]);

  const latestStoryShift = useMemo(() => {
    const ev = data.events.find((e) => e.shift_id);
    return ev?.shift_id ?? data.shifts.find((s) => s.callout_at)?.id ?? null;
  }, [data.events, data.shifts]);

  const focusedShiftId = pinnedShift ?? latestStoryShift;
  const shift = data.shifts.find((s) => s.id === focusedShiftId) ?? null;
  const shiftOffers = data.offers.filter((o) => o.shift_id === focusedShiftId);

  const fastForward = async () => {
    setFfBusy(true);
    try {
      await supabase.rpc("ff_shifts");
    } finally {
      setTimeout(() => setFfBusy(false), 900);
    }
  };

  return (
    <div className="app">
      <header>
        <div className="brand">
          <span className="logo" />
          Rock Scheduler <span className="dim">ops</span>
        </div>
        <div className="row gap">
          <button className={`btn ff ${ffBusy ? "busy" : ""}`} onClick={fastForward}
                  title="Skip the ladder waits (demo)">
            {ffBusy ? "skipping…" : ">> fast-forward"}
          </button>
          <div className="live-dot"><span />live
          </div>
        </div>
      </header>
      <main>
        <aside className="panel">
          <div className="panel-head">Workflows</div>
          <WorkflowPanel workflows={data.workflows} nurses={data.nurses}
                         agencyId={data.agencyId} refresh={data.refresh} />
        </aside>
        <section className="right">
          <div className="panel graph-panel">
            <div className="panel-head row space">
              <span>
                Story
                {shift && (
                  <span className={`pill st-${shift.status}`}>{shift.status}</span>
                )}
              </span>
              {pinnedShift && (
                <button className="btn tiny" onClick={() => setPinnedShift(null)}>
                  back to live
                </button>
              )}
            </div>
            <div className="graph-wrap">
              <FlowGraph shift={shift} offers={shiftOffers} nursesById={nursesById} />
            </div>
          </div>
          <div className="panel log-panel">
            <div className="panel-head">Events</div>
            <EventLog events={data.events} nursesById={nursesById}
                      focusedShift={focusedShiftId} mountedAt={mountedAt}
                      filter={filter} onFilter={setFilter}
                      onFocus={(id) => setPinnedShift(id)} />
          </div>
        </section>
      </main>
    </div>
  );
}
