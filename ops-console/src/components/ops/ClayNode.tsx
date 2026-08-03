/**
 * A single lineage node: clay puck, status ring, optional call ripple.
 * Positioned in world pixels; the graph camera handles pan/zoom.
 *
 * Pucks are the 72px "people & outcomes" nodes (callout nurse, router,
 * prospects, Shift filled / Escalated). Attempt nodes render as
 * <ClayStagePip> instead.
 */
import { AlertCircle, Check, Share2 } from "lucide-react";
import { type GraphNode } from "@/lib/ops-story";
import { HoverCard } from "./HoverCard";

const RING: Record<string, string> = {
  scheduled: "var(--ring-idle)",
  callout: "var(--ring-callout)",
  router: "var(--ring-router)",
  messaged: "var(--ring-router)",
  calling: "var(--ring-calling)",
  declined: "var(--ring-declined)",
  accepted: "var(--ring-accepted)",
  escalated: "var(--ring-escalated)",
};

const TEXT: Record<string, string> = {
  scheduled: "text-muted-foreground",
  callout: "text-callout",
  router: "text-router",
  messaged: "text-router",
  calling: "text-calling",
  declined: "text-declined",
  accepted: "text-accepted",
  escalated: "text-escalated",
};

export function ClayNode({
  node,
  selected,
  onSelect,
}: {
  node: GraphNode;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const ring = RING[node.state];

  return (
    <button
      type="button"
      data-node
      onClick={() => onSelect(node.id)}
      className="group absolute h-[72px] w-[72px] animate-node-pop outline-none"
      style={{ left: node.x, top: node.y }}
    >
      <span className="relative grid h-full w-full place-items-center">
        {node.state === "calling" && (
          <>
            <span className="clay-ripple" />
            <span className="clay-ripple [animation-delay:0.8s]" />
          </>
        )}
        <span
          className="clay-puck relative grid h-[72px] w-[72px] place-items-center rounded-full transition-transform duration-300 group-hover:-translate-y-0.5"
          style={{
            boxShadow: `var(--clay-out), 0 12px 26px color-mix(in oklab, ${ring} 26%, transparent), inset 0 0 0 3px ${ring}`,
          }}
        >
          {node.glyph === "router" && <Share2 className="h-6 w-6 text-router" strokeWidth={2.2} />}
          {node.glyph === "check" && <Check className="h-7 w-7 text-accepted" strokeWidth={3} />}
          {node.glyph === "alert" && (
            <AlertCircle className="h-7 w-7 text-escalated" strokeWidth={2.4} />
          )}
          {node.initials && (
            <span className="text-[15px] font-semibold tracking-tight text-foreground/80">
              {node.initials}
            </span>
          )}
        </span>
        {node.badge && (
          <span className="clay-badge absolute -right-0.5 -top-0.5 grid h-5 w-5 place-items-center rounded-full text-[11px] font-semibold">
            {node.badge}
          </span>
        )}
        {selected && (
          <span
            className="pointer-events-none absolute -inset-2 rounded-full"
            style={{ boxShadow: `0 0 0 1.5px ${ring}` }}
          />
        )}
      </span>

      <span className="pointer-events-none absolute left-1/2 top-full mt-3 -translate-x-1/2 text-center">
        <span className="block whitespace-nowrap text-[13px] font-semibold tracking-tight text-foreground">
          {node.label}
        </span>
        <span
          className={`mt-0.5 block whitespace-nowrap text-[11.5px] font-medium ${TEXT[node.state]}`}
        >
          {node.sub}
        </span>
      </span>

      {/* Puck hover card: identity-level facts (score, attempt count, timeline). */}
      <HoverCard title={node.label} accent={ring!} lines={node.tooltip ?? []} />
    </button>
  );
}
