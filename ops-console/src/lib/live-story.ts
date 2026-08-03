/**
 * Adapters: live Supabase rows -> the graph/event shapes the console draws.
 * Pure functions, so every realtime update re-derives the picture.
 *
 * Two flow modes, user-switchable in the story header:
 *   normal   – one puck per prospect, state caption (the classic view)
 *   detailed – every outreach attempt is its own stage pip; the tree grows
 *              rightwards (sms → whatsapp → call → outcome) via frame()
 */
import type { EventRow, Nurse, Offer, Shift } from "@/lib/supabase";
import {
  GEO, frame,
  type GraphEdge, type GraphNode, type NodeState, type Prospect,
  type Stage, type StageChannel, type StoryEvent,
} from "@/lib/ops-story";

export type FlowMode = "normal" | "detailed";

const OFFER_STATE: Record<string, NodeState> = {
  scored: "scheduled", messaged: "messaged", calling: "calling",
  accepted: "accepted", declined: "declined", no_answer: "declined",
  stood_down: "declined",
};

const OFFER_SUB: Record<string, string> = {
  scored: "queued", messaged: "waiting reply", calling: "on the call",
  accepted: "accepted", declined: "declined", no_answer: "no answer",
  stood_down: "stood down",
};

function initials(name: string): string {
  return name.split(/\s+/).map((w) => w[0] ?? "").join("").slice(0, 2).toUpperCase();
}

const laneOf = (i: number, n: number) => GEO.laneY + (i - (n - 1) / 2) * GEO.laneGap;

const hhmmss = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour12: false });

export function shiftCaption(shift: Shift): string {
  const when = new Date(shift.starts_at).toLocaleString([], {
    weekday: "short", hour: "numeric", minute: "2-digit",
  });
  return `${shift.patients?.name ?? shift.area} · ${shift.specialty} · ${when}`;
}

/* ── shared builders ─────────────────────────────────────────────────────── */

function calloutNode(shift: Shift, nursesById: Map<string, Nurse>): GraphNode {
  const nurse = shift.callout_nurse_id ? nursesById.get(shift.callout_nurse_id) : null;
  return {
    id: "callout",
    label: nurse?.name ?? "Unknown",
    sub: shift.callout_reason ? `called out · ${shift.callout_reason}` : "called out",
    initials: initials(nurse?.name ?? "?"),
    x: GEO.calloutX, y: GEO.laneY, state: "callout", kind: "puck", badge: "!",
    tooltip: [
      ...(shift.callout_reason ? [`reason · ${shift.callout_reason}`] : []),
      ...(shift.callout_at ? [`at · ${hhmmss(shift.callout_at)}`] : []),
      `shift · ${shift.specialty} in ${shift.area}`,
    ],
  };
}

function routerNode(shift: Shift, prospectCount: number): GraphNode {
  return {
    id: "outreach",
    label: "outreach",
    sub: shift.status === "callout" ? "scoring…" : `rung ${shift.rung}`,
    glyph: "router", x: GEO.routerX, y: GEO.laneY, state: "router", kind: "puck",
    tooltip: [
      `prospects · ${prospectCount}`,
      "ladder · sms → whatsapp → voice",
      `status · ${shift.status.replaceAll("_", " ")}`,
    ],
  };
}

/** Chronological outreach attempts (offer_sent / offer_call) per nurse. */
function attemptsByNurse(shift: Shift, events: EventRow[]) {
  const map = new Map<string, EventRow[]>();
  for (const ev of [...events].reverse()) { // feed is newest-first
    if (ev.shift_id !== shift.id || !ev.nurse_id) continue;
    if (ev.kind !== "offer_sent" && ev.kind !== "offer_call") continue;
    const list = map.get(ev.nurse_id) ?? [];
    list.push(ev);
    map.set(ev.nurse_id, list);
  }
  return map;
}

/* ── detailed mode: attempts -> Stage[] -> frame() ───────────────────────── */

function stagesOf(offer: Offer, tries: EventRow[]): Stage[] {
  const stages: Stage[] = tries.map((ev, i) => {
    const channel: StageChannel =
      ev.channel === "voice" || ev.channel === "call" ? "call"
      : ev.channel === "whatsapp" ? "whatsapp" : "sms";
    const ok = ev.outcome === "sent" || ev.outcome === "dialing";
    return {
      channel,
      state: "attempted",
      label: ok
        ? `${channel} · ${channel === "call" ? "dialed" : "sent"}`
        : `${channel} · failed`,
      rung: ev.rung ?? i + 1,
      time: hhmmss(ev.at),
      detail: [ev.outcome ?? "?"],
    };
  });

  const last = stages[stages.length - 1];
  const cap = (state: Stage["state"], label: string, detail: string[]) =>
    stages.push({
      channel: "stand", state, label,
      rung: last?.rung ?? 1,
      time: offer.responded_at ? hhmmss(offer.responded_at) : (last?.time ?? ""),
      detail,
    });

  switch (offer.state) {
    case "accepted":
      cap("success", "said YES", ["lock_shift() ok", "audited"]);
      break;
    case "declined":
      cap("dead", "replied NO", ["pruned from ladder"]);
      break;
    case "stood_down":
      cap("dead", "stood down", ["shift filled by someone else"]);
      break;
    case "no_answer":
      if (last?.channel === "call") {
        last.state = "dead";
        last.label = "call · no answer";
      } else {
        cap("dead", "no answer", []);
      }
      break;
    case "calling":
      if (last?.channel === "call") {
        last.state = "active";
        last.label = "ringing…";
      }
      break;
    case "messaged":
      if (last && last.state === "attempted" && !last.label.endsWith("failed")) {
        last.state = "active";
      }
      break;
  }
  return stages;
}

function toDetailedGraph(shift: Shift, ranked: Offer[], nursesById: Map<string, Nurse>,
                         events: EventRow[]) {
  const attempts = attemptsByNurse(shift, events);
  const prospects: Prospect[] = ranked.map((offer) => {
    const nurse = nursesById.get(offer.nurse_id);
    return {
      id: offer.id,
      name: nurse?.name ?? "?",
      initials: initials(nurse?.name ?? "?"),
      score: offer.score,
      sub: OFFER_SUB[offer.state] ?? offer.state,
      state: OFFER_STATE[offer.state] ?? "scheduled",
      stages: stagesOf(offer, attempts.get(offer.nurse_id) ?? []),
    };
  });

  let outcome;
  if (shift.status === "filled" && shift.nurse_id) {
    const winner = prospects.find(
      (p) => ranked.find((o) => o.id === p.id)?.nurse_id === shift.nurse_id);
    outcome = {
      id: "outcome", label: "Shift filled", sub: "locked · audited", ok: true,
      from: winner && winner.stages.length
        ? `${winner.id}-s${winner.stages.length - 1}`
        : "outreach",
    };
  } else if (shift.status === "escalated") {
    outcome = {
      id: "outcome", label: "Escalated", sub: "coordinator paged", ok: false,
      from: "outreach",
    };
  }

  return frame(prospects, {
    callout: calloutNode(shift, nursesById),
    router: routerNode(shift, prospects.length),
    outcome,
  });
}

/* ── normal mode: the classic one-puck-per-prospect view ─────────────────── */

function toNormalGraph(shift: Shift, ranked: Offer[], nursesById: Map<string, Nurse>,
                       events: EventRow[]) {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const attempts = attemptsByNurse(shift, events);

  nodes.push(calloutNode(shift, nursesById));
  nodes.push(routerNode(shift, ranked.length));
  edges.push({ id: "e-c-o", from: "callout", to: "outreach",
               kind: ["callout", "offers_out"].includes(shift.status) ? "sms" : "idle" });

  const n = ranked.length;
  ranked.forEach((offer, i) => {
    const nurse = nursesById.get(offer.nurse_id);
    const id = `n-${offer.id}`;
    const tries = attempts.get(offer.nurse_id) ?? [];
    nodes.push({
      id, label: nurse?.name ?? "?",
      sub: `${OFFER_SUB[offer.state] ?? offer.state} · ${Math.round(offer.score * 100)}%`,
      initials: initials(nurse?.name ?? "?"),
      x: GEO.prospectX, y: laneOf(i, n),
      state: OFFER_STATE[offer.state] ?? "scheduled", kind: "puck",
      tooltip: [
        `match score · ${Math.round(offer.score * 100)}%`,
        ...tries.map((t) => `${hhmmss(t.at)} · ${t.channel ?? "sms"} — ${t.outcome ?? "?"}`),
        `now · ${OFFER_SUB[offer.state] ?? offer.state}`,
      ],
    });
    const kind: GraphEdge["kind"] =
      offer.state === "accepted" ? "locked"
      : offer.state === "calling" ? "call"
      : ["declined", "no_answer", "stood_down"].includes(offer.state) ? "declined"
      : offer.state === "messaged"
        ? (offer.last_channel?.includes("whatsapp") ? "whatsapp" : "sms")
        : "idle";
    edges.push({
      id: `e-${offer.id}`, from: "outreach", to: id, kind,
      ...(offer.state === "accepted" ? { label: "yes" }
        : offer.state === "no_answer" ? { label: "no answer" }
        : offer.state === "declined" ? { label: "declined" }
        : offer.state === "stood_down" ? { label: "stood down" }
        : offer.rung > 0 && offer.last_channel ? { label: offer.last_channel } : {}),
    });
  });

  if (shift.status === "filled" && shift.nurse_id) {
    const winnerIdx = ranked.findIndex((o) => o.nurse_id === shift.nurse_id);
    nodes.push({
      id: "outcome", label: "Shift filled", sub: "locked · audited", glyph: "check",
      x: GEO.prospectX + 260, y: winnerIdx >= 0 ? laneOf(winnerIdx, n) : GEO.laneY,
      state: "accepted", kind: "puck",
    });
    edges.push({
      id: "e-out", from: winnerIdx >= 0 ? `n-${ranked[winnerIdx]!.id}` : "outreach",
      to: "outcome", kind: "locked",
    });
  } else if (shift.status === "escalated") {
    nodes.push({
      id: "outcome", label: "Escalated", sub: "coordinator paged", glyph: "alert",
      x: GEO.prospectX + 260, y: GEO.laneY, state: "escalated", kind: "puck",
    });
    edges.push({ id: "e-out", from: "outreach", to: "outcome", kind: "call" });
  }

  return { nodes, edges };
}

export function toGraph(shift: Shift, offers: Offer[], nursesById: Map<string, Nurse>,
                        events: EventRow[] = [], mode: FlowMode = "detailed") {
  const ranked = [...offers].sort((a, b) => b.score - a.score);
  return mode === "detailed"
    ? toDetailedGraph(shift, ranked, nursesById, events)
    : toNormalGraph(shift, ranked, nursesById, events);
}

/* ── event feed ──────────────────────────────────────────────────────────── */

const EVENT_META: Record<string, { title: string; tag: StoryEvent["tag"] }> = {
  callout_recorded: { title: "Callout recorded", tag: "alert" },
  shift_status_changed: { title: "Status changed", tag: "router" },
  prospects_scored: { title: "Prospects scored", tag: "router" },
  offer_sent: { title: "Offer sent", tag: "sms" },
  offer_call: { title: "Offer call", tag: "call" },
  offer_response: { title: "Response", tag: "ok" },
  stand_down: { title: "Stood down", tag: "sms" },
  shift_filled: { title: "Shift filled", tag: "ok" },
  escalated: { title: "Escalated", tag: "alert" },
  sms_in: { title: "SMS received", tag: "sms" },
  sms_out: { title: "SMS replied", tag: "sms" },
};

export function toStoryEvents(rows: EventRow[], nursesById: Map<string, Nurse>) {
  return rows.map((ev) => {
    const meta = EVENT_META[ev.kind] ?? { title: ev.kind.replaceAll("_", " "), tag: "router" as const };
    let tag = meta.tag;
    if (ev.kind === "offer_sent" && ev.channel?.includes("whatsapp")) tag = "whatsapp";
    if (ev.kind === "offer_response" && ev.outcome?.startsWith("no")) tag = "alert";
    const nurse = ev.nurse_id ? nursesById.get(ev.nurse_id)?.name : null;
    const p = ev.payload ?? {};
    const detail = [
      nurse, ev.channel, ev.rung != null ? `rung ${ev.rung}` : null, ev.outcome,
      ev.kind === "shift_status_changed" ? `${p["from"]} → ${p["to"]}` : null,
      ev.kind === "prospects_scored" ? String(p["prospects"] ?? "") : null,
      ev.kind === "escalated" ? String(p["reason"] ?? "") : null,
      ev.kind === "callout_recorded" && p["reason"] ? `"${p["reason"]}"` : null,
      ["sms_in", "sms_out"].includes(ev.kind)
        ? `${p["phone"] ?? ""} · "${String(p["text"] ?? "").slice(0, 90)}"` : null,
    ].filter(Boolean).join(" · ");
    return {
      id: String(ev.id),
      time: new Date(ev.at).toLocaleTimeString([], { hour12: false }),
      title: meta.title, detail, tag, shiftId: ev.shift_id,
    };
  });
}
