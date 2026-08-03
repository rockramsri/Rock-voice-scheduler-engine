// Raised card list: collapsed rows show one clean line; click to expand
// the detail. Filters keep the feed scoped — Story (focused shift),
// Live (since the dashboard opened), All.

import { useState } from "react";
import type { EventRow, Nurse } from "../types";

export type Filter = "story" | "live" | "all";

const KIND_META: Record<string, { icon: string; cls: string; title: string }> = {
  callout_recorded: { icon: "!", cls: "red", title: "Callout" },
  shift_status_changed: { icon: "~", cls: "purple", title: "Status change" },
  prospects_scored: { icon: "#", cls: "purple", title: "Prospects scored" },
  offer_sent: { icon: ">", cls: "blue", title: "Offer sent" },
  offer_call: { icon: "C", cls: "amber", title: "Offer call" },
  offer_response: { icon: "<", cls: "green", title: "Response" },
  shift_filled: { icon: "OK", cls: "green", title: "Shift filled" },
  escalated: { icon: "!!", cls: "red", title: "Escalated" },
};

interface Props {
  events: EventRow[];
  nursesById: Map<string, Nurse>;
  focusedShift: string | null;
  mountedAt: string;
  filter: Filter;
  onFilter: (f: Filter) => void;
  onFocus: (shiftId: string) => void;
}

export default function EventLog({ events, nursesById, focusedShift, mountedAt,
                                   filter, onFilter, onFocus }: Props) {
  const [open, setOpen] = useState<number | null>(null);

  const visible = events.filter((ev) => {
    if (filter === "story") return !!focusedShift && ev.shift_id === focusedShift;
    if (filter === "live") return ev.at >= mountedAt;
    return true;
  });

  return (
    <div className="log-col">
      <div className="filter-bar">
        {(["story", "live", "all"] as Filter[]).map((f) => (
          <button key={f} className={`chip ${filter === f ? "on" : ""}`}
                  onClick={() => onFilter(f)}>
            {f === "story" ? "this story" : f}
          </button>
        ))}
        <span className="hint">{visible.length} events</span>
      </div>
      <div className="log">
        {visible.map((ev) => {
          const meta = KIND_META[ev.kind] ?? { icon: "·", cls: "gray", title: ev.kind };
          const nurse = ev.nurse_id ? nursesById.get(ev.nurse_id) : null;
          const expanded = open === ev.id;
          return (
            <div key={ev.id} className={`log-card slide ${expanded ? "open" : ""}`}
                 onClick={() => setOpen(expanded ? null : ev.id)}>
              <div className="log-line">
                <span className={`badge ${meta.cls}`}>{meta.icon}</span>
                <span className="log-title">
                  {meta.title}
                  {nurse && <span className="log-who"> · {nurse.name}</span>}
                </span>
                <span className="log-time">
                  {new Date(ev.at).toLocaleTimeString([], { hour12: false })}
                </span>
              </div>
              {expanded && (
                <div className="log-detail-grid">
                  <Detail k="actor" v={ev.actor} />
                  <Detail k="channel" v={ev.channel} />
                  <Detail k="rung" v={ev.rung != null ? String(ev.rung) : null} />
                  <Detail k="outcome" v={ev.outcome} />
                  {Object.entries(ev.payload ?? {}).map(([k, v]) => (
                    <Detail key={k} k={k} v={String(v)} />
                  ))}
                  {ev.shift_id && (
                    <button className="btn tiny" onClick={(e) => {
                      e.stopPropagation();
                      onFocus(ev.shift_id!);
                    }}>focus this story</button>
                  )}
                </div>
              )}
            </div>
          );
        })}
        {visible.length === 0 && (
          <div className="empty">
            {filter === "story" ? "No events for this story yet." : "Waiting for activity…"}
          </div>
        )}
      </div>
    </div>
  );
}

function Detail({ k, v }: { k: string; v: string | null }) {
  if (!v) return null;
  return (
    <div className="hc-row">
      <span>{k}</span>
      <b>{v}</b>
    </div>
  );
}
