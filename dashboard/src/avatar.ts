// Initials avatars as data-URI SVGs: zero network calls, deterministic
// color per name. A nurse's avatar_url (if set) always wins.

const PALETTE = ["#7c6cf6", "#4fc3f7", "#66bb6a", "#ffa726", "#ef5350", "#ab47bc", "#26a69a"];

export function avatarFor(name: string, avatarUrl?: string): string {
  if (avatarUrl) return avatarUrl;
  const initials = name
    .split(/\s+/)
    .map((w) => w[0] ?? "")
    .join("")
    .slice(0, 2)
    .toUpperCase();
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) & 0xffff;
  const color = PALETTE[hash % PALETTE.length];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96">
    <rect width="96" height="96" rx="48" fill="${color}"/>
    <text x="48" y="60" font-family="Inter,system-ui,sans-serif" font-size="36"
      font-weight="700" fill="#0d0d12" text-anchor="middle">${initials}</text>
  </svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}
