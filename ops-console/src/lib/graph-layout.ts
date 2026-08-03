/**
 * Layout helpers for the lineage canvas.
 *
 * Coordinates are derived deterministically in `ops-story.frame()`, but live
 * data can still crowd a lane (a prospect with more stages than its neighbour,
 * a manual re-lane, etc). These helpers (a) push overlapping nodes apart and
 * (b) compute the camera transform needed to frame a set of nodes.
 *
 * Pucks (72px person/outcome nodes) and pips (36px attempt nodes) have very
 * different footprints, so separation is computed per PAIR from each node's own
 * half-extents rather than from one global gap.
 */
import type { GraphNode } from "@/lib/ops-story";

/** Visual half-extents including the caption block underneath each node. */
export const HALF = {
  puck: { w: 80, h: 76 },
  pip: { w: 60, h: 46 },
} as const;

const halfOf = (n: { kind?: "puck" | "pip" }) => (n.kind === "pip" ? HALF.pip : HALF.puck);

export type Box = { x: number; y: number; w: number; h: number };

/**
 * Deterministic relaxation: repeatedly separate any pair of nodes whose
 * bounding boxes overlap, along whichever axis needs the smaller correction.
 * Pips are lighter than pucks, so a puck/pip collision moves the pip ~2x more —
 * that keeps prospect lanes anchored while attempt chains flex.
 */
export function resolveOverlaps(nodes: GraphNode[], iterations = 80): GraphNode[] {
  const pts = nodes.map((n) => ({ x: n.x, y: n.y }));
  const halves = nodes.map(halfOf);
  const mass = nodes.map((n) => (n.kind === "pip" ? 0.5 : 1));

  for (let it = 0; it < iterations; it++) {
    let moved = false;

    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const a = pts[i]!;
        const b = pts[j]!;
        const gapX = halves[i]!.w + halves[j]!.w;
        const gapY = halves[i]!.h + halves[j]!.h;
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        // Break perfect coincidence so the push has a direction.
        if (dx === 0 && dy === 0) {
          dx = (j - i) * 0.5;
          dy = (i % 2 === 0 ? 1 : -1) * 0.5;
        }
        const ox = gapX - Math.abs(dx);
        const oy = gapY - Math.abs(dy);
        if (ox <= 0 || oy <= 0) continue;

        moved = true;
        const wa = mass[j]! / (mass[i]! + mass[j]!); // share of the correction for a
        const wb = 1 - wa;
        // Correct along the cheaper axis (normalised by the required gap).
        if (ox / gapX < oy / gapY) {
          const s = dx >= 0 ? 1 : -1;
          a.x -= ox * wa * s;
          b.x += ox * wb * s;
        } else {
          const s = dy >= 0 ? 1 : -1;
          a.y -= oy * wa * s;
          b.y += oy * wb * s;
        }
      }
    }

    if (!moved) break;
  }

  return nodes.map((n, i) => ({ ...n, x: pts[i]!.x, y: pts[i]!.y }));
}

/** Bounding box around a set of nodes, including their label footprint. */
export function boundsOf(nodes: { x: number; y: number; kind?: "puck" | "pip" }[], pad = 40): Box {
  if (nodes.length === 0) return { x: 0, y: 0, w: 1, h: 1 };
  const minX = Math.min(...nodes.map((n) => n.x - halfOf(n).w)) - pad;
  const maxX = Math.max(...nodes.map((n) => n.x + halfOf(n).w)) + pad;
  const minY = Math.min(...nodes.map((n) => n.y - halfOf(n).h)) - pad;
  const maxY = Math.max(...nodes.map((n) => n.y + halfOf(n).h)) + pad;
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
}

export type Camera = { x: number; y: number; z: number };

export const MIN_ZOOM = 0.3;
export const MAX_ZOOM = 2.5;

export const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

/** Camera that fits `box` inside a `vw` x `vh` viewport, centred. */
export function fitCamera(box: Box, vw: number, vh: number, maxZoom = 1.15): Camera {
  if (vw <= 0 || vh <= 0) return { x: 0, y: 0, z: 1 };
  const z = clampZoom(Math.min(vw / box.w, vh / box.h, maxZoom));
  return {
    x: (vw - box.w * z) / 2 - box.x * z,
    y: (vh - box.h * z) / 2 - box.y * z,
    z,
  };
}

/** Camera centred on a single point at a given zoom. */
export function centerCamera(px: number, py: number, vw: number, vh: number, z: number): Camera {
  const zoom = clampZoom(z);
  return { x: vw / 2 - px * zoom, y: vh / 2 - py * zoom, z: zoom };
}
