/**
 * Shared hover card for graph nodes.
 *
 * Rendered inside the world layer, so it scales with the camera — deliberate:
 * it keeps its visual relationship to the node at any zoom level.
 * Pointer-events are off so the card never blocks a click on the node.
 */
export function HoverCard({
  title,
  lines,
  accent,
  compact = false,
}: {
  title: string;
  lines: string[];
  accent: string;
  compact?: boolean;
}) {
  if (lines.length === 0) return null;

  return (
    <span
      className={`clay-hovercard pointer-events-none absolute bottom-full left-1/2 z-30 mb-3 -translate-x-1/2 rounded-2xl px-3 py-2 text-left opacity-0 transition-all duration-200 group-hover:-translate-y-0.5 group-hover:opacity-100 ${
        compact ? "min-w-[136px]" : "min-w-[168px]"
      }`}
    >
      <span
        className="block whitespace-nowrap text-[11px] font-bold uppercase tracking-[0.1em]"
        style={{ color: accent }}
      >
        {title}
      </span>
      {lines.map((l) => (
        <span
          key={l}
          className="mt-0.5 block whitespace-nowrap text-[11px] font-medium leading-[1.5] text-muted-foreground"
        >
          {l}
        </span>
      ))}
    </span>
  );
}
