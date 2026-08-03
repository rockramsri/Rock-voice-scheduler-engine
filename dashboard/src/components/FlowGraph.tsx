// The live story graph: callout -> outreach -> prospects -> outcome.
// Round nodes, smoothstep lineage edges with staggered elbows so lines
// never pile on top of each other; hover a node for the glass detail card.

import { Background, BackgroundVariant, Controls, MiniMap, ReactFlow,
         type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import type { Nurse, Offer, Shift } from "../types";
import { nodeTypes } from "./GraphNodes";

const EDGE_COLOR: Record<string, string> = {
  scored: "#c3c8dd", messaged: "#38bdf8", calling: "#f59e0b",
  accepted: "#10b981", declined: "#f43f5e", no_answer: "#c3c8dd",
};

const COL = { root: 0, stage: 250, nurse: 520, outcome: 800 };
const ROW = 128;

interface Props {
  shift: Shift | null;
  offers: Offer[];
  nursesById: Map<string, Nurse>;
}

export default function FlowGraph({ shift, offers, nursesById }: Props) {
  const { nodes, edges } = useMemo(() => build(shift, offers, nursesById),
    [shift, offers, nursesById]);

  if (!shift) {
    return <div className="empty">Quiet for now — when a workflow fires, its story grows here.</div>;
  }
  return (
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView
               fitViewOptions={{ padding: 0.3 }} proOptions={{ hideAttribution: true }}
               minZoom={0.3} maxZoom={2.2} defaultEdgeOptions={{ type: "smoothstep" }}>
      <Background variant={BackgroundVariant.Dots} gap={24} size={1.4} color="#d6dae8" />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable bgColor="rgba(255,255,255,.75)"
               maskColor="rgba(230,233,244,.7)" nodeColor="#c9cee2" />
    </ReactFlow>
  );
}

function build(shift: Shift | null, offers: Offer[], nursesById: Map<string, Nurse>) {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  if (!shift) return { nodes, edges };

  const ranked = [...offers].sort((a, b) => b.score - a.score);
  const midY = ((Math.max(ranked.length, 1) - 1) * ROW) / 2;
  const calloutNurse = shift.callout_nurse_id ? nursesById.get(shift.callout_nurse_id) : null;
  const when = new Date(shift.starts_at).toLocaleString([], {
    weekday: "short", hour: "numeric", minute: "2-digit" });
  const live = ["callout", "offers_out"].includes(shift.status);

  nodes.push({
    id: "root", type: "root", position: { x: COL.root, y: midY },
    data: {
      nurseName: calloutNurse?.name ?? "Unknown", avatarUrl: calloutNurse?.avatar_url,
      reason: shift.callout_reason, patient: shift.patients?.name,
      shiftLabel: `${shift.specialty} · ${when} · ${shift.area}`,
    },
  });
  nodes.push({
    id: "stage", type: "stage", position: { x: COL.stage, y: midY },
    data: {
      label: shift.status === "callout" ? "scoring" : "outreach",
      rung: shift.rung, live,
      plan: `${ranked.length} prospects ranked`,
    },
  });
  edges.push({
    id: "e-root", source: "root", target: "stage", animated: live,
    style: { stroke: "#8b7cf8", strokeWidth: 2 },
  });

  ranked.forEach((offer, i) => {
    const nurse = nursesById.get(offer.nurse_id);
    const id = `n-${offer.id}`;
    nodes.push({
      id, type: "nurse", position: { x: COL.nurse, y: i * ROW },
      data: {
        name: nurse?.name ?? "?", avatarUrl: nurse?.avatar_url, score: offer.score,
        state: offer.state, reason: offer.reason,
        touches: offer.rung > 0
          ? `${offer.last_channel ?? ""} · rung ${offer.rung}` : "not contacted yet",
      },
    });
    edges.push({
      id: `e-${offer.id}`, source: "stage", target: id, type: "smoothstep",
      animated: ["messaged", "calling"].includes(offer.state),
      pathOptions: { borderRadius: 22, offset: 14 + i * 10 },
      label: offer.last_channel ?? undefined,
      labelStyle: { fill: "#7a819c", fontSize: 10, fontWeight: 600 },
      labelBgStyle: { fill: "rgba(255,255,255,.85)", rx: 6 },
      style: { stroke: EDGE_COLOR[offer.state] ?? "#c3c8dd", strokeWidth: 2 },
    } as Edge);
  });

  if (shift.status === "filled" && shift.nurse_id) {
    const winner = nursesById.get(shift.nurse_id);
    const winOffer = ranked.findIndex((o) => o.nurse_id === shift.nurse_id);
    nodes.push({
      id: "outcome", type: "outcome",
      position: { x: COL.outcome, y: winOffer >= 0 ? winOffer * ROW : midY },
      data: { kind: "filled", nurseName: winner?.name, avatarUrl: winner?.avatar_url },
    });
    edges.push({
      id: "e-outcome", type: "smoothstep",
      source: winOffer >= 0 ? `n-${ranked[winOffer].id}` : "stage", target: "outcome",
      animated: true, pathOptions: { borderRadius: 22 },
      style: { stroke: "#10b981", strokeWidth: 2.5 },
    } as Edge);
  } else if (shift.status === "escalated") {
    nodes.push({
      id: "outcome", type: "outcome", position: { x: COL.outcome, y: midY },
      data: { kind: "escalated", reason: "prospects exhausted or quiet hours" },
    });
    edges.push({
      id: "e-outcome", source: "stage", target: "outcome", type: "smoothstep",
      animated: true, pathOptions: { borderRadius: 22, offset: 30 },
      style: { stroke: "#f43f5e", strokeWidth: 2.5 },
    } as Edge);
  }
  return { nodes, edges };
}
