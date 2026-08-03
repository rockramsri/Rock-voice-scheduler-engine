/**
 * Lineage canvas: dot grid, smoothstep edges with travelling packets, clay nodes.
 *
 * The canvas owns a camera (pan + zoom). Nodes live in a world-pixel layer that
 * is transformed as a whole, so SVG edges and HTML nodes can never drift apart.
 * Layout runs through `resolveOverlaps` so live data can never stack nodes.
 *
 * Node kinds:
 *   puck (72px) – people & outcomes   → <ClayNode>
 *   pip  (36px) – one outreach attempt → <ClayStagePip>
 * Edge endpoints are trimmed by the RADIUS of the node they touch, so a
 * puck→pip connector still lands cleanly on both rims.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Focus, Minus, Plus, Workflow } from "lucide-react";
import { type Beat, type GraphNode } from "@/lib/ops-story";
import {
  type Camera,
  boundsOf,
  centerCamera,
  clampZoom,
  fitCamera,
  resolveOverlaps,
} from "@/lib/graph-layout";
import { ClayNode } from "./ClayNode";
import { ClayStagePip } from "./ClayStagePip";

const radiusOf = (n: GraphNode) => (n.kind === "pip" ? 22 : 40);

const STROKE: Record<string, string> = {
  idle: "var(--edge-idle)",
  attempted: "var(--edge-idle)",
  sms: "var(--ring-router)",
  whatsapp: "var(--ring-accepted)",
  call: "var(--ring-calling)",
  declined: "var(--ring-declined)",
  stood: "var(--ring-idle)",
  locked: "var(--ring-accepted)",
};

function path(a: GraphNode, b: GraphNode) {
  const sx = a.x + radiusOf(a);
  const tx = b.x - radiusOf(b);
  const dx = Math.max(36, (tx - sx) * 0.5);
  return `M ${sx},${a.y} C ${sx + dx},${a.y} ${tx - dx},${b.y} ${tx},${b.y}`;
}

export function StoryGraph({
  beat,
  selected,
  onSelect,
}: {
  beat: Beat;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [cam, setCam] = useState<Camera>({ x: 0, y: 0, z: 1 });
  const [manual, setManual] = useState(false);
  const [animate, setAnimate] = useState(true);

  const nodes = useMemo(() => resolveOverlaps(beat.nodes), [beat.nodes]);
  const empty = nodes.length === 0;
  const at = (id: string) => nodes.find((n) => n.id === id);

  // Track viewport size so the camera can frame content precisely.
  useLayoutEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const r = entry!.contentRect;
      setSize({ w: r.width, h: r.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Reserve room for the camera control bar at the bottom.
  const vh = Math.max(0, size.h - 56);

  const fitAll = useCallback(
    (smooth = true) => {
      if (!size.w || nodes.length === 0) return;
      setAnimate(smooth);
      setManual(false);
      setCam(fitCamera(boundsOf(nodes), size.w, vh));
    },
    [nodes, size.w, vh],
  );

  // Auto-frame: follow the story unless the operator has taken the wheel.
  useEffect(() => {
    if (manual || !size.w || nodes.length === 0) return;
    setAnimate(true);
    const focus = selected ? nodes.find((n) => n.id === selected) : null;
    setCam(
      focus
        ? centerCamera(focus.x, focus.y, size.w, vh, focus.kind === "pip" ? 1.6 : 1.35)
        : fitCamera(boundsOf(nodes), size.w, vh),
    );
  }, [nodes, selected, size.w, vh, manual]);

  // Wheel zoom anchored at the cursor (non-passive so pinch never scrolls the page).
  const camRef = useRef(cam);
  camRef.current = cam;

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const dy = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 100 : 1);
      const cur = camRef.current;
      const next = clampZoom(cur.z * Math.exp(-dy * 0.0018));
      if (next === cur.z) return;
      const rect = el.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const k = next / cur.z;
      setAnimate(false);
      setManual(true);
      setCam({ x: px - (px - cur.x) * k, y: py - (py - cur.y) * k, z: next });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  // Drag to pan.
  const drag = useRef<{ id: number; x: number; y: number; cam: Camera } | null>(null);

  const onPointerDown = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest("button[data-node]")) return;
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, cam: camRef.current };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setAnimate(false);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    setManual(true);
    setCam({ x: d.cam.x + (e.clientX - d.x), y: d.cam.y + (e.clientY - d.y), z: d.cam.z });
  };

  const endDrag = (e: React.PointerEvent) => {
    if (drag.current?.id === e.pointerId) drag.current = null;
  };

  const zoomBy = (factor: number) => {
    const cur = camRef.current;
    const next = clampZoom(cur.z * factor);
    if (next === cur.z) return;
    const px = size.w / 2;
    const py = vh / 2;
    const k = next / cur.z;
    setAnimate(true);
    setManual(true);
    setCam({ x: px - (px - cur.x) * k, y: py - (py - cur.y) * k, z: next });
  };

  return (
    <div
      className={`clay-canvas relative overflow-hidden rounded-[28px] ${
        empty ? "clay-canvas-empty" : ""
      }`}
    >
      <div className="dot-grid pointer-events-none absolute inset-0" />

      <div
        ref={viewportRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        className="relative h-[430px] w-full touch-none select-none lg:h-[500px]"
        style={{ cursor: drag.current ? "grabbing" : "grab" }}
      >
        <div
          className="absolute left-0 top-0 origin-top-left"
          style={{
            transform: `translate(${cam.x}px, ${cam.y}px) scale(${cam.z})`,
            transition: animate ? "transform 700ms cubic-bezier(0.22, 1, 0.36, 1)" : "none",
          }}
        >
          <svg className="absolute left-0 top-0 overflow-visible" width={1} height={1}>
            {beat.edges.map((e) => {
              const a = at(e.from);
              const b = at(e.to);
              if (!a || !b) return null;
              const d = path(a, b);
              const color = STROKE[e.kind];
              const live = e.kind === "sms" || e.kind === "whatsapp" || e.kind === "call";
              const faint = e.kind === "attempted" || e.kind === "stood";
              const mx = (a.x + b.x) / 2;
              const my = (a.y + b.y) / 2 + (a.y === b.y ? -14 : 0);

              return (
                <g key={e.id} className="animate-edge-in">
                  <path
                    id={`p-${e.id}`}
                    d={d}
                    fill="none"
                    stroke={color}
                    strokeWidth={faint ? 1.75 : 2}
                    opacity={faint ? 0.75 : 1}
                    {...(faint ? { strokeDasharray: "6 6" } : {})}
                  />
                  {e.kind === "declined" && (
                    <path d={d} fill="none" stroke={color} strokeWidth={2} strokeDasharray="1 7" />
                  )}
                  {live && (
                    <>
                      <path
                        d={d}
                        fill="none"
                        stroke={color}
                        strokeWidth={2.5}
                        strokeDasharray="10 10"
                        className="animate-dash"
                        opacity={0.9}
                      />
                      <circle r={4} fill={color}>
                        <animateMotion dur="1.9s" repeatCount="indefinite" path={d} />
                      </circle>
                    </>
                  )}
                  {e.kind === "locked" && (
                    <path
                      d={d}
                      fill="none"
                      stroke={color}
                      strokeWidth={5}
                      opacity={0.18}
                      strokeLinecap="round"
                    />
                  )}
                  {e.label && (
                    <foreignObject x={mx - 52} y={my - 13} width={104} height={26}>
                      <div className="flex justify-center">
                        <span
                          className="clay-chip rounded-full px-2.5 py-[3px] text-[10px] font-semibold uppercase tracking-[0.08em]"
                          style={{ color }}
                        >
                          {e.label}
                        </span>
                      </div>
                    </foreignObject>
                  )}
                </g>
              );
            })}
          </svg>

          {nodes.map((n) =>
            n.kind === "pip" ? (
              <ClayStagePip
                key={n.id}
                node={n}
                selected={selected === n.id}
                onSelect={onSelect}
              />
            ) : (
              <ClayNode key={n.id} node={n} selected={selected === n.id} onSelect={onSelect} />
            ),
          )}
        </div>

        {empty && (
          <div className="pointer-events-none absolute inset-0 grid place-items-center p-6">
            <div className="clay-empty grid max-w-[340px] place-items-center gap-2 rounded-[24px] px-8 py-9 text-center">
              <Workflow className="h-7 w-7 text-router/70" strokeWidth={1.8} />
              <p className="text-[13px] font-semibold text-foreground">No lineage yet</p>
              <p className="text-[11.5px] leading-relaxed text-muted-foreground">
                Nodes appear here as callouts arrive and the outreach ladder starts firing.
              </p>
            </div>
          </div>
        )}

        {/* Camera controls */}
        <div className="absolute bottom-4 right-4 flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => zoomBy(1 / 1.25)}
            aria-label="Zoom out"
            className="clay-pill grid h-9 w-9 place-items-center rounded-full text-muted-foreground"
          >
            <Minus className="h-4 w-4" strokeWidth={2.6} />
          </button>
          <span className="clay-pill grid h-9 min-w-[54px] place-items-center rounded-full text-[11px] font-semibold tabular-nums text-foreground/70">
            {Math.round(cam.z * 100)}%
          </span>
          <button
            type="button"
            onClick={() => zoomBy(1.25)}
            aria-label="Zoom in"
            className="clay-pill grid h-9 w-9 place-items-center rounded-full text-muted-foreground"
          >
            <Plus className="h-4 w-4" strokeWidth={2.6} />
          </button>
          <button
            type="button"
            onClick={() => fitAll()}
            aria-label="Fit graph"
            className={`clay-pill flex h-9 items-center gap-1.5 rounded-full px-3 text-[11px] font-semibold ${
              manual ? "text-router" : "text-muted-foreground"
            }`}
          >
            <Focus className="h-4 w-4" strokeWidth={2.4} /> fit
          </button>
        </div>
      </div>
    </div>
  );
}
