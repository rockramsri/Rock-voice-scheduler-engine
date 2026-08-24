/** Shared look for scenario cards + decks — calm clay surfaces, one quiet
 * pastel accent per scenario. Information layer, not a shiny layer:
 * saturated color is reserved for semantic status (verdict, pass/fail). */

const ACCENT_HUES = [190, 280, 160, 55, 250, 320, 220, 20];

function hue(id: string): number {
  let hash = 0;
  for (const ch of id) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return ACCENT_HUES[hash % ACCENT_HUES.length]!;
}

/** Soft pastel strip — enough to tell scenarios apart at a glance, no glare. */
export function scenarioGradient(id: string): string {
  const h = hue(id);
  return `linear-gradient(135deg, oklch(0.88 0.055 ${h}), oklch(0.82 0.07 ${h + 25}))`;
}

/** Slightly deeper single tone for tiny icon chips / accents. */
export function scenarioAccent(id: string): string {
  return `oklch(0.62 0.1 ${hue(id)})`;
}

export function shortName(id: string): string {
  return id.replace(/^co-\d+-/, "").replaceAll("-", " ");
}

export const VERDICT_TONE: Record<string, string> = {
  CONFIRMED_CORRECT: "var(--ring-accepted)",
  REGRESSION: "var(--ring-escalated)",
  UNRESOLVED: "var(--ring-callout)",
};
