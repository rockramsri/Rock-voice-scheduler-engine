/** Initials avatar with a name-hashed hue; falls back to an image when avatar_url is set. */
import { avatarHue, initials } from "@/lib/workflow-store";

export function NurseAvatar({
  name,
  url,
  size = 30,
  ring,
  className = "",
}: {
  name: string;
  url?: string;
  size?: number;
  ring?: boolean;
  className?: string;
}) {
  const hue = avatarHue(name || "nurse");
  const style: React.CSSProperties = {
    width: size,
    height: size,
    fontSize: Math.max(9, size * 0.36),
    background: `oklch(0.93 0.06 ${hue})`,
    color: `oklch(0.42 0.13 ${hue})`,
    boxShadow: ring
      ? `var(--clay-out), 0 0 0 2px oklch(0.985 0.002 260)`
      : "var(--clay-out)",
  };
  if (url) {
    return (
      <img
        src={url}
        alt={name}
        style={{ width: size, height: size, boxShadow: style.boxShadow }}
        className={`shrink-0 rounded-full object-cover ${className}`}
      />
    );
  }
  return (
    <span
      style={style}
      className={`grid shrink-0 place-items-center rounded-full font-bold tracking-tight ${className}`}
      aria-hidden
    >
      {initials(name)}
    </span>
  );
}
