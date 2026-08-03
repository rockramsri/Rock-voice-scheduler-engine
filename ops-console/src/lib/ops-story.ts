/**
 * Rock Scheduler — demo story model (TREE / ladder growth).
 *
 * A callout story is a sequence of beats. Each beat is a full snapshot of the
 * lineage graph (nodes + edges) plus the events emitted at that moment.
 *
 * ── SHAPE OF THE GRAPH ────────────────────────────────────────────────────────
 *   callout nurse ──▶ outreach router ──▶ prospect puck ──▶ [stage pip]* ──▶ outcome
 *
 * Every outreach ATTEMPT is its own node (a "pip"), so the escalating effort is
 * readable at a glance:  prospect → [SMS] → [WhatsApp] → [Calling…] → [✓]
 * A branch that dies (nurse replied NO / no answer / stood down) keeps its pips
 * but grows no further and is capped with a terminal dead pip.
 *
 * ── INTEGRATING LIVE DATA (for the next agent) ───────────────────────────────
 * Do NOT rebuild the layout by hand. Feed realtime rows into `frame()`:
 *   • offer_sent(prospect, channel, outcome, time) → push a Stage
 *       outcome "sent"/"delivered" while newest → state "attempted"
 *   • offer_call(dialing)      → push Stage { channel: "call", state: "active" }
 *   • offer_call(no_answer)    → set that Stage.state = "dead", prospect terminal
 *   • offer_response(yes)      → set Stage.state = "success", add the outcome node
 *   • offer_response(no)       → Stage.state = "dead", prospect.state = "declined"
 *   • stand_down(prospect)     → append Stage { channel: "stand", state: "dead" }
 * Then call `frame(prospects, { outcome })` for a fresh {nodes, edges} snapshot.
 * Positions are derived deterministically from lane index + stage index, so the
 * graph GROWS to the right without any node ever jumping lanes.
 */

export type NodeState =
  | "scheduled"
  | "callout"
  | "router"
  | "messaged"
  | "calling"
  | "declined"
  | "accepted"
  | "escalated";

export type EdgeKind =
  | "idle"
  | "sms"
  | "whatsapp"
  | "call"
  | "attempted"
  | "declined"
  | "locked"
  | "stood";

/** Channel of a single outreach attempt. `stand` = terminal stood-down cap. */
export type StageChannel = "sms" | "whatsapp" | "call" | "stand";

/**
 * Stage lifecycle:
 *  waiting   – queued, not fired yet          (idle ring, hollow)
 *  attempted – fired, no reply / soft failure (idle ring, dashed edge)
 *  active    – in flight right now            (channel ring + pulse ripple)
 *  success   – nurse said YES                 (green ring, check)
 *  dead      – NO / no answer / stood down    (red ring, ✗, branch stops)
 */
export type StageState = "waiting" | "attempted" | "active" | "success" | "dead";

export type Stage = {
  channel: StageChannel;
  state: StageState;
  /** Short caption under the pip, e.g. "sms · no reply". */
  label: string;
  /** Ladder rung this attempt belongs to (1-based). */
  rung: number;
  time: string;
  /** Hover-card body, one fact per line. */
  detail: string[];
};

export type GraphNode = {
  id: string;
  label: string;
  sub: string;
  initials?: string;
  glyph?: "router" | "check" | "alert";
  x: number;
  y: number;
  state: NodeState;
  badge?: string | undefined;
  /** puck = 72px person/outcome node, pip = 36px attempt node. */
  kind?: "puck" | "pip";
  channel?: StageChannel;
  stageState?: StageState;
  /** Hover card lines. */
  tooltip?: string[];
};

export type GraphEdge = {
  id: string;
  from: string;
  to: string;
  kind: EdgeKind;
  label?: string;
};

export type StoryEvent = {
  id: string;
  time: string;
  title: string;
  detail: string;
  tag: "call" | "sms" | "whatsapp" | "router" | "alert" | "ok";
  /** Live feed only: which shift this event belongs to (demo beats omit it). */
  shiftId?: string | null;
};

export type Beat = {
  key: string;
  caption: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  events: StoryEvent[];
};

export const CANVAS = { w: 1320, h: 560 };

/* ── Geometry spec ─────────────────────────────────────────────────────────── */

/** Column x positions. Stage pips march right from PROSPECT_X in STAGE_DX steps. */
export const GEO = {
  calloutX: 100,
  routerX: 300,
  prospectX: 520,
  stageDX: 148,
  /** Outcome column sits one full stage-step past the longest chain. */
  outcomeGap: 190,
  laneY: 250,
  laneGap: 168,
  maxStages: 4,
};

const laneOf = (i: number, n: number) => GEO.laneY + (i - (n - 1) / 2) * GEO.laneGap;
const stageX = (i: number) => GEO.prospectX + (i + 1) * GEO.stageDX;

/* ── Prospect model ────────────────────────────────────────────────────────── */

export type Prospect = {
  id: string;
  name: string;
  initials: string;
  /** Dispatch score 0–1 (shown on the puck hover card). */
  score: number;
  sub: string;
  state: NodeState;
  stages: Stage[];
};

const STAGE_RING: Record<StageState, NodeState> = {
  waiting: "scheduled",
  attempted: "messaged",
  active: "calling",
  success: "accepted",
  dead: "declined",
};

const EDGE_FOR: Record<StageState, (c: StageChannel) => EdgeKind> = {
  waiting: () => "idle",
  attempted: () => "attempted",
  active: (c) => (c === "call" ? "call" : c === "whatsapp" ? "whatsapp" : "sms"),
  success: () => "locked",
  dead: () => "declined",
};

type FrameOpts = {
  callout: GraphNode;
  router?: GraphNode | undefined;
  /** Terminal node on the right ("Shift filled" / "Escalated"). */
  outcome?: { id: string; label: string; sub: string; ok: boolean; from: string } | undefined;
};

/**
 * Derive a full graph snapshot from the prospect list. Pure + deterministic:
 * same prospects in ⇒ same coordinates out, so streaming updates never reflow.
 */
export function frame(prospects: Prospect[], opts: FrameOpts) {
  const nodes: GraphNode[] = [opts.callout];
  const edges: GraphEdge[] = [];

  if (opts.router) {
    nodes.push(opts.router);
    edges.push({ id: "e-callout-router", from: opts.callout.id, to: opts.router.id, kind: "idle" });
  }

  const n = prospects.length;
  prospects.forEach((p, i) => {
    const y = laneOf(i, n);
    nodes.push({
      id: p.id,
      label: p.name,
      sub: p.sub,
      initials: p.initials,
      x: GEO.prospectX,
      y,
      state: p.state,
      kind: "puck",
      tooltip: [
        `match score · ${Math.round(p.score * 100)}%`,
        `attempts · ${p.stages.filter((s) => s.channel !== "stand").length}`,
        ...p.stages.map((s) => `${s.time} · ${s.label}`),
      ],
    });

    if (opts.router) {
      const first = p.stages[0];
      edges.push({
        id: `e-r-${p.id}`,
        from: opts.router.id,
        to: p.id,
        kind: first ? "idle" : "idle",
      });
    }

    let prev = p.id;
    p.stages.forEach((s, si) => {
      const id = `${p.id}-s${si}`;
      nodes.push({
        id,
        label: s.channel === "stand" ? "stood down" : s.channel,
        sub: s.label,
        x: stageX(si),
        y,
        state: STAGE_RING[s.state],
        kind: "pip",
        channel: s.channel,
        stageState: s.state,
        tooltip: [`rung ${s.rung} · ${s.channel}`, `${s.time}`, ...s.detail],
      });
      edges.push({
        id: `e-${prev}-${id}`,
        from: prev,
        to: id,
        kind: s.channel === "stand" ? "stood" : EDGE_FOR[s.state](s.channel),
        ...(si === 0 && s.state !== "attempted" ? { label: s.channel } : {}),
      });
      prev = id;
    });
  });

  if (opts.outcome) {
    const longest = Math.max(0, ...prospects.map((p) => p.stages.length));
    const x = stageX(longest - 1) + GEO.outcomeGap;
    nodes.push({
      id: opts.outcome.id,
      label: opts.outcome.label,
      sub: opts.outcome.sub,
      glyph: opts.outcome.ok ? "check" : "alert",
      x,
      y: GEO.laneY,
      state: opts.outcome.ok ? "accepted" : "escalated",
      kind: "puck",
      tooltip: [opts.outcome.sub],
    });
    edges.push({
      id: "e-outcome",
      from: opts.outcome.from,
      to: opts.outcome.id,
      kind: opts.outcome.ok ? "locked" : "call",
    });
  }

  return { nodes, edges };
}

/* ── Demo story ────────────────────────────────────────────────────────────── */

const ev = (
  time: string,
  title: string,
  detail: string,
  tag: StoryEvent["tag"],
): StoryEvent => ({ id: `${time}-${title}-${detail}`, time, title, detail, tag });

const callout = (sub: string, state: NodeState, badge?: string): GraphNode => ({
  id: "maria",
  label: "Maria Alvarez",
  sub,
  initials: "MA",
  x: GEO.calloutX,
  y: GEO.laneY,
  state,
  kind: "puck",
  ...(badge ? { badge } : {}),
  tooltip: ["callout · flu", "shift · wound care 08:00–16:00", "lead time · 4h"],
});

const router = (sub: string): GraphNode => ({
  id: "outreach",
  label: "outreach",
  sub,
  glyph: "router",
  x: GEO.routerX,
  y: GEO.laneY,
  state: "router",
  kind: "puck",
  tooltip: ["ladder · URGENT", "rungs · sms → whatsapp → voice"],
});

const stage = (
  channel: StageChannel,
  state: StageState,
  label: string,
  rung: number,
  time: string,
  ...detail: string[]
): Stage => ({ channel, state, label, rung, time, detail });

const P = (
  id: string,
  name: string,
  initials: string,
  score: number,
  state: NodeState,
  sub: string,
  stages: Stage[],
): Prospect => ({ id, name, initials, score, state, sub, stages });

export type Outcome = "accept" | "escalate";

export function buildStory(outcome: Outcome): Beat[] {
  const base: Beat[] = [];

  base.push({
    key: "idle",
    caption: "Shift scheduled — Robert Rivera, wound care, 08:00–16:00",
    ...frame([], { callout: callout("assigned", "scheduled") }),
    events: [ev("11:42:00", "Shift scheduled", "Maria Alvarez assigned", "ok")],
  });

  base.push({
    key: "callout",
    caption: "Inbound call on +1 929 730-7867 — front desk takes the callout",
    ...frame([], { callout: callout("called out", "callout", "1") }),
    events: [
      ev("11:48:02", "Inbound call", "front desk answered · 41s", "call"),
      ev("11:48:44", "Callout recorded", "reason: flu · shift unassigned", "alert"),
    ],
  });

  base.push({
    key: "scored",
    caption: "Prospects scored · lead time 4h · URGENT ladder queued",
    ...frame(
      [
        P("james", "James Okafor", "JO", 0.77, "scheduled", "queued · rung 1", []),
        P("fatima", "Fatima Diallo", "FD", 0.64, "scheduled", "queued · rung 1", []),
        P("priya", "Priya Nair", "PN", 0.58, "scheduled", "queued · rung 1", []),
      ],
      { callout: callout("called out", "callout"), router: router("3 prospects · rung 1") },
    ),
    events: [
      ev("11:48:46", "Shift claimed", "dispatch-worker-1 · SKIP LOCKED", "router"),
      ev("11:48:46", "Prospects scored", "James .77 · Fatima .64 · Priya .58", "router"),
    ],
  });

  base.push({
    key: "rung1",
    caption: "Rung 1 — SMS burst, one attempt node per prospect",
    ...frame(
      [
        P("james", "James Okafor", "JO", 0.77, "messaged", "rung 1 sent", [
          stage("sms", "active", "sms · delivered", 1, "11:48:47", "twilio · delivered", "awaiting reply"),
        ]),
        P("fatima", "Fatima Diallo", "FD", 0.64, "messaged", "rung 1 sent", [
          stage("sms", "active", "sms · delivered", 1, "11:48:47", "twilio · delivered", "awaiting reply"),
        ]),
        P("priya", "Priya Nair", "PN", 0.58, "messaged", "rung 1 failed", [
          stage("sms", "attempted", "sms · failed", 1, "11:48:47", "carrier reject 30008", "will escalate"),
        ]),
      ],
      { callout: callout("called out", "callout"), router: router("rung 1 · sent") },
    ),
    events: [
      ev("11:48:47", "Offer sent", "James Okafor · SMS", "sms"),
      ev("11:48:47", "Offer sent", "Fatima Diallo · SMS", "sms"),
      ev("11:48:48", "Offer failed", "Priya Nair · SMS carrier reject", "alert"),
    ],
  });

  base.push({
    key: "rung2",
    caption: "Rung 2 — no replies, WhatsApp grows off each live branch",
    ...frame(
      [
        P("james", "James Okafor", "JO", 0.77, "messaged", "rung 2 sent", [
          stage("sms", "attempted", "sms · no reply", 1, "11:48:47", "delivered", "10m timeout"),
          stage("whatsapp", "active", "whatsapp · read", 2, "11:53:10", "read 11:53:44"),
        ]),
        P("fatima", "Fatima Diallo", "FD", 0.64, "declined", "declined", [
          stage("sms", "attempted", "sms · replied", 1, "11:48:47", "delivered"),
          stage("stand", "dead", "replied NO", 1, "11:52:02", "“covering elsewhere”", "pruned from ladder"),
        ]),
        P("priya", "Priya Nair", "PN", 0.58, "messaged", "rung 2 sent", [
          stage("sms", "attempted", "sms · failed", 1, "11:48:47", "carrier reject 30008"),
          stage("whatsapp", "active", "whatsapp · sent", 2, "11:53:10", "delivered"),
        ]),
      ],
      { callout: callout("called out", "callout"), router: router("rung 2 · whatsapp") },
    ),
    events: [
      ev("11:52:02", "Declined", "Fatima Diallo · replied NO", "alert"),
      ev("11:53:10", "Offer sent", "James Okafor · WhatsApp", "whatsapp"),
      ev("11:53:10", "Offer sent", "Priya Nair · WhatsApp", "whatsapp"),
    ],
  });

  base.push({
    key: "rung3",
    caption: "Rung 3 — AI voice call, one prospect on the line at a time",
    ...frame(
      [
        P("james", "James Okafor", "JO", 0.77, "calling", "on the call", [
          stage("sms", "attempted", "sms · no reply", 1, "11:48:47", "delivered"),
          stage("whatsapp", "attempted", "whatsapp · read", 2, "11:53:10", "read, no reply"),
          stage("call", "active", "ringing…", 3, "11:58:52", "outbound SIP", "livekit agent live"),
        ]),
        P("fatima", "Fatima Diallo", "FD", 0.64, "declined", "declined", [
          stage("sms", "attempted", "sms · replied", 1, "11:48:47", "delivered"),
          stage("stand", "dead", "replied NO", 1, "11:52:02", "“covering elsewhere”"),
        ]),
        P("priya", "Priya Nair", "PN", 0.58, "messaged", "queued for voice", [
          stage("sms", "attempted", "sms · failed", 1, "11:48:47", "carrier reject 30008"),
          stage("whatsapp", "attempted", "whatsapp · no reply", 2, "11:53:10", "delivered"),
          stage("call", "waiting", "queued", 3, "11:59:—", "next in voice queue"),
        ]),
      ],
      { callout: callout("called out", "callout"), router: router("rung 3 · voice") },
    ),
    events: [
      ev("11:58:52", "Offer call", "James Okafor · outbound SIP", "call"),
      ev("11:58:52", "Queued", "Priya Nair · voice rung", "router"),
    ],
  });

  if (outcome === "accept") {
    base.push({
      key: "filled",
      caption: "First YES wins — lock_shift() atomic, losing branches stood down",
      ...frame(
        [
          P("james", "James Okafor", "JO", 0.77, "accepted", "accepted", [
            stage("sms", "attempted", "sms · no reply", 1, "11:48:47", "delivered"),
            stage("whatsapp", "attempted", "whatsapp · read", 2, "11:53:10", "read, no reply"),
            stage("call", "attempted", "answered · 39s", 3, "11:58:52", "AI agent · offer read"),
            stage("stand", "success", "said YES", 3, "11:59:31", "lock_shift() ok", "audited"),
          ]),
          P("fatima", "Fatima Diallo", "FD", 0.64, "declined", "declined", [
            stage("sms", "attempted", "sms · replied", 1, "11:48:47", "delivered"),
            stage("stand", "dead", "replied NO", 1, "11:52:02", "“covering elsewhere”"),
          ]),
          P("priya", "Priya Nair", "PN", 0.58, "declined", "stood down", [
            stage("sms", "attempted", "sms · failed", 1, "11:48:47", "carrier reject 30008"),
            stage("whatsapp", "attempted", "whatsapp · no reply", 2, "11:53:10", "delivered"),
            stage("stand", "dead", "stood down", 3, "11:59:31", "shift filled by James"),
          ]),
        ],
        {
          callout: callout("released", "callout"),
          router: router("resolved · rung 3"),
          outcome: {
            id: "filled",
            label: "Shift filled",
            sub: "locked · audited",
            ok: true,
            from: "james-s3",
          },
        },
      ),
      events: [
        ev("11:59:31", "Accepted", "James Okafor said YES on the call", "ok"),
        ev("11:59:31", "Shift locked", "lock_shift() · no double booking", "ok"),
        ev("11:59:32", "Stood down", "Priya Nair · shift already filled", "router"),
      ],
    });
  } else {
    base.push({
      key: "escalated",
      caption: "Every branch dead — human coordinator paged",
      ...frame(
        [
          P("james", "James Okafor", "JO", 0.77, "declined", "no answer", [
            stage("sms", "attempted", "sms · no reply", 1, "11:48:47", "delivered"),
            stage("whatsapp", "attempted", "whatsapp · read", 2, "11:53:10", "read, no reply"),
            stage("call", "dead", "no answer · 3 rings", 3, "11:58:52", "voicemail dropped"),
          ]),
          P("fatima", "Fatima Diallo", "FD", 0.64, "declined", "declined", [
            stage("sms", "attempted", "sms · replied", 1, "11:48:47", "delivered"),
            stage("stand", "dead", "replied NO", 1, "11:52:02", "“covering elsewhere”"),
          ]),
          P("priya", "Priya Nair", "PN", 0.58, "declined", "no answer", [
            stage("sms", "attempted", "sms · failed", 1, "11:48:47", "carrier reject 30008"),
            stage("whatsapp", "attempted", "whatsapp · no reply", 2, "11:53:10", "delivered"),
            stage("call", "dead", "no answer", 3, "12:01:40", "2 rings · hung up"),
          ]),
        ],
        {
          callout: callout("called out", "callout"),
          router: router("exhausted"),
          outcome: {
            id: "escalated",
            label: "Escalated",
            sub: "coordinator paged",
            ok: false,
            from: "outreach",
          },
        },
      ),
      events: [
        ev("12:02:10", "No answer", "James Okafor · 3 rings", "alert"),
        ev("12:02:11", "Escalated", "no prospects left · human paged", "alert"),
      ],
    });
  }

  return base;
}
