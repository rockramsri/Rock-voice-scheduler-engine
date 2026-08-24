import type { ReactNode } from "react";
import { scenarioGradient, shortName } from "./cardStyle";

/**
 * A run rendered as a fanned deck of scenario playing-cards.
 * Click pops the deck open (the parent decides what "open" shows).
 */
export function ScenarioDeck({
  scenarioIds,
  title,
  subtitle,
  trailing,
  onOpen,
}: {
  scenarioIds: string[];
  title: string;
  subtitle?: string;
  trailing?: ReactNode;
  onOpen: () => void;
}) {
  const shown = scenarioIds.slice(0, 6);
  const n = shown.length || 1;
  const mid = (n - 1) / 2;

  return (
    <button
      type="button"
      onClick={onOpen}
      className="clay-row group grid w-full grid-cols-[190px_minmax(0,1fr)_auto] items-center gap-4 rounded-[24px] px-4 py-3 text-left transition-transform hover:-translate-y-0.5"
    >
      <div className="relative h-[92px]" aria-hidden>
        {shown.map((id, i) => {
          const angle = (i - mid) * 7;
          const lift = Math.abs(i - mid) * 5;
          return (
            <div
              key={id}
              className="absolute left-1/2 top-1/2 h-[76px] w-[58px] overflow-hidden rounded-xl transition-transform duration-300 group-hover:[transform:translate(-50%,-50%)_rotate(var(--r))_translateY(-6px)]"
              style={{
                "--r": `${angle}deg`,
                transform: `translate(-50%, -50%) translateX(${(i - mid) * 16}px) translateY(${lift}px) rotate(${angle}deg)`,
                zIndex: i,
                boxShadow: "3px 5px 12px oklch(0.6 0.03 262 / 0.22)",
              } as React.CSSProperties}
            >
              <div className="h-full w-full bg-white">
                <div className="h-[26%] w-full" style={{ background: scenarioGradient(id) }} />
                <div className="px-1.5 pt-1">
                  <p className="truncate text-[6.5px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {id.split("-").slice(0, 2).join("-")}
                  </p>
                  <p className="line-clamp-3 text-[7.5px] font-bold capitalize leading-tight text-foreground/85">
                    {shortName(id)}
                  </p>
                </div>
              </div>
            </div>
          );
        })}
        {scenarioIds.length > 6 && (
          <span className="clay-chip absolute -right-1 bottom-0 z-10 rounded-full px-2 py-0.5 text-[9px] font-bold text-muted-foreground">
            +{scenarioIds.length - 6}
          </span>
        )}
      </div>

      <div className="min-w-0">
        <p className="truncate text-[13px] font-bold tracking-tight text-foreground">{title}</p>
        {subtitle && <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">{subtitle}</p>}
        <p className="mt-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-router opacity-0 transition-opacity group-hover:opacity-100">
          click to fan out ↗
        </p>
      </div>

      <div className="flex shrink-0 flex-col items-end gap-1.5">{trailing}</div>
    </button>
  );
}
