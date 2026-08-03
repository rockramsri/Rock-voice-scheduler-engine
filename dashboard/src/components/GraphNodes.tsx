// Round icon nodes: the graph stays minimal — a circle tells the state,
// hovering raises a glass card with the full detail.

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { avatarFor } from "../avatar";

type Data = Record<string, any>;

function Hover({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div className="hovercard">
      <div className="hc-title">{title}</div>
      {rows.filter(([, v]) => v).map(([k, v]) => (
        <div className="hc-row" key={k}>
          <span>{k}</span>
          <b>{v}</b>
        </div>
      ))}
    </div>
  );
}

export function RootNode({ data }: NodeProps) {
  const d = data as Data;
  return (
    <div className="orb-wrap pop">
      <Handle type="source" position={Position.Right} />
      <div className="orb ring-red">
        <img src={avatarFor(d.nurseName, d.avatarUrl)} />
        <span className="orb-badge red">!</span>
      </div>
      <div className="orb-label">{d.nurseName?.split(" ")[0]}</div>
      <div className="orb-sub">called out</div>
      <Hover title={`Callout — ${d.nurseName}`}
             rows={[["reason", d.reason ? `"${d.reason}"` : ""],
                    ["shift", d.shiftLabel], ["patient", d.patient]]} />
    </div>
  );
}

export function StageNode({ data }: NodeProps) {
  const d = data as Data;
  return (
    <div className="orb-wrap pop">
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <div className={`orb icon ${d.live ? "ring-pulse" : "ring-purple"}`}>
        <svg viewBox="0 0 24 24" width="22" height="22">
          <path d="M4 12h10m0 0-4-4m4 4-4 4M20 5v14" fill="none"
                stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </div>
      <div className="orb-label">{d.label}</div>
      <div className="orb-sub">rung {d.rung}</div>
      <Hover title="Outreach engine"
             rows={[["status", d.live ? "working" : "settled"],
                    ["current rung", String(d.rung)], ["plan", d.plan]]} />
    </div>
  );
}

const STATE_TEXT: Record<string, string> = {
  scored: "queued", messaged: "waiting reply", calling: "on call",
  accepted: "accepted", declined: "declined", no_answer: "no answer",
};

export function NurseNode({ data }: NodeProps) {
  const d = data as Data;
  return (
    <div className="orb-wrap pop">
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <div className={`orb ring-${d.state}`}>
        <img src={avatarFor(d.name, d.avatarUrl)} />
        {d.state === "calling" && <span className="pulse-ring" />}
        <span className={`orb-dot dot-${d.state}`} />
      </div>
      <div className="orb-label">{d.name?.split(" ")[0]}</div>
      <div className="orb-sub">{STATE_TEXT[d.state] ?? d.state}</div>
      <Hover title={d.name}
             rows={[["state", STATE_TEXT[d.state] ?? d.state],
                    ["match score", `${Math.round(d.score * 100)}%`],
                    ["why", d.reason],
                    ["touches", d.touches]]} />
    </div>
  );
}

export function OutcomeNode({ data }: NodeProps) {
  const d = data as Data;
  const filled = d.kind === "filled";
  return (
    <div className="orb-wrap pop">
      <Handle type="target" position={Position.Left} />
      <div className={`orb icon ${filled ? "ring-accepted glow-green" : "ring-declined glow-red"}`}>
        {filled ? (
          <svg viewBox="0 0 24 24" width="24" height="24">
            <path d="m5 13 4 4L19 7" fill="none" stroke="currentColor"
                  strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" width="24" height="24">
            <path d="M12 5v9m0 4h.01" fill="none" stroke="currentColor"
                  strokeWidth="2.5" strokeLinecap="round" />
          </svg>
        )}
      </div>
      <div className="orb-label">{filled ? "Filled" : "Escalated"}</div>
      <div className="orb-sub">{filled ? d.nurseName?.split(" ")[0] : "human paged"}</div>
      <Hover title={filled ? "Shift filled" : "Escalated to coordinator"}
             rows={[["by", d.nurseName ?? ""], ["reason", d.reason ?? ""]]} />
    </div>
  );
}

export const nodeTypes = {
  root: RootNode,
  stage: StageNode,
  nurse: NurseNode,
  outcome: OutcomeNode,
};
