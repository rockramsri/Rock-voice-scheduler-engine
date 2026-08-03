/**
 * ClayStagePip — one outreach ATTEMPT in a prospect's ladder chain.
 *
 * Deliberately smaller than a puck (36px vs 72px): a prospect can accumulate up
 * to 4 of these, and at 6 prospects the canvas still reads as "one lane per
 * person, effort escalating rightwards" without the camera zooming out past
 * legibility. Captions are tiny and only show on the current/terminal states at
 * low zoom (the parent fades them via CSS var --pip-caption).
 *
 * State language (ring tokens shared with pucks):
 *   waiting   – hollow idle ring, dimmed          (queued, not fired)
 *   attempted – idle ring, solid fill             (fired, no reply / soft fail)
 *   active    – channel colour + pulsing ripple   (in flight right now)
 *   success   – accepted green + check            (nurse said YES)
 *   dead      – declined red + ✗                  (NO / no answer / stood down)
 */
import { MessageSquare, MessageCircle, Phone, Check, X, Ban } from "lucide-react";
import type { GraphNode, StageChannel, StageState } from "@/lib/ops-story";
import { HoverCard } from "./HoverCard";

const RING: Record<StageState, string> = {
  waiting: "var(--ring-idle)",
  attempted: "var(--ring-idle)",
  active: "var(--ring-calling)",
  success: "var(--ring-accepted)",
  dead: "var(--ring-declined)",
};

const CHANNEL_RING: Record<StageChannel, string> = {
  sms: "var(--ring-router)",
  whatsapp: "var(--ring-accepted)",
  call: "var(--ring-calling)",
  stand: "var(--ring-idle)",
};

const CAPTION: Record<StageState, string> = {
  waiting: "text-muted-foreground/70",
  attempted: "text-muted-foreground",
  active: "text-calling",
  success: "text-accepted",
  dead: "text-declined",
};

function Glyph({ node, color }: { node: GraphNode; color: string }) {
  const s = node.stageState;
  const cls = "h-[15px] w-[15px]";
  const style = { color };
  if (s === "success") return <Check className={cls} strokeWidth={3.2} style={style} />;
  if (s === "dead")
    return node.channel === "stand" ? (
      <Ban className={cls} strokeWidth={2.6} style={style} />
    ) : (
      <X className={cls} strokeWidth={3.2} style={style} />
    );
  if (node.channel === "call") return <Phone className={cls} strokeWidth={2.6} style={style} />;
  if (node.channel === "whatsapp")
    return <MessageCircle className={cls} strokeWidth={2.6} style={style} />;
  return <MessageSquare className={cls} strokeWidth={2.6} style={style} />;
}

export function ClayStagePip({
  node,
  selected,
  onSelect,
}: {
  node: GraphNode;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const state = node.stageState ?? "attempted";
  const channel = node.channel ?? "sms";
  // Live attempts carry their channel colour; resolved ones carry outcome colour.
  const ring = state === "active" ? CHANNEL_RING[channel] : RING[state];
  const faded = state === "waiting";

  return (
    <button
      type="button"
      data-node
      onClick={() => onSelect(node.id)}
      className="group absolute h-9 w-9 animate-pip-pop outline-none"
      style={{ left: node.x, top: node.y }}
    >
      <span className="relative grid h-full w-full place-items-center">
        {state === "active" && (
          <>
            <span className="clay-ripple-sm" style={{ borderColor: ring }} />
            <span
              className="clay-ripple-sm [animation-delay:0.7s]"
              style={{ borderColor: ring }}
            />
          </>
        )}
        <span
          className={`clay-puck relative grid h-9 w-9 place-items-center rounded-full transition-transform duration-300 group-hover:-translate-y-0.5 ${
            faded ? "opacity-60" : ""
          } ${state === "active" ? "animate-pip-breathe" : ""}`}
          style={{
            boxShadow: `var(--clay-out-sm), 0 6px 14px color-mix(in oklab, ${ring} 24%, transparent), inset 0 0 0 2.5px ${
              faded ? `color-mix(in oklab, ${ring} 55%, transparent)` : ring
            }`,
          }}
        >
          <Glyph node={node} color={ring} />
        </span>
        {selected && (
          <span
            className="pointer-events-none absolute -inset-1.5 rounded-full"
            style={{ boxShadow: `0 0 0 1.5px ${ring}` }}
          />
        )}
      </span>

      <span className="pointer-events-none absolute left-1/2 top-full mt-2 -translate-x-1/2 text-center">
        <span
          className={`block whitespace-nowrap text-[10px] font-semibold tracking-tight ${CAPTION[state]}`}
        >
          {node.sub}
        </span>
      </span>

      {/* Stage hover card: attempt-level facts (rung, timestamp, outcome detail). */}
      <HoverCard title={node.label} accent={ring} lines={node.tooltip ?? []} compact />
    </button>
  );
}
