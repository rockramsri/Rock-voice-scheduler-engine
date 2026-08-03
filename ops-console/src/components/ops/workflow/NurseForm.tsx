/**
 * Editable nurse profile form — shared by the workflow builder rows and the
 * standalone single-profile popup. Pure presentation + local validation; the
 * parent owns the value and decides when to persist.
 */
import { Trash2, ShieldAlert, GripVertical } from "lucide-react";
import {
  CHANNELS,
  type Channel,
  type NurseErrors,
  type NurseProfile,
} from "@/lib/workflow-store";
import { NurseAvatar } from "./Avatar";

const CHANNEL_COLOR: Record<Channel, string> = {
  sms: "var(--ring-router)",
  whatsapp: "var(--ring-accepted)",
  voice: "var(--ring-calling)",
};

function Field({
  label,
  children,
  error,
  hint,
}: {
  label: string;
  children: React.ReactNode;
  error?: string | undefined;
  hint?: string | undefined;
}) {
  return (
    <label className="block min-w-0">
      <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </span>
      {children}
      {error ? (
        <span className="mt-1 block text-[10.5px] font-medium text-declined">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-[10.5px] text-muted-foreground">{hint}</span>
      ) : null}
    </label>
  );
}

export function NurseForm({
  nurse,
  errors,
  onChange,
  onRemove,
  dragHandleProps,
  compact,
}: {
  nurse: NurseProfile;
  errors: NurseErrors;
  onChange: (n: NurseProfile) => void;
  onRemove?: () => void;
  dragHandleProps?: React.HTMLAttributes<HTMLSpanElement>;
  compact?: boolean;
}) {
  const set = <K extends keyof NurseProfile>(k: K, v: NurseProfile[K]) =>
    onChange({ ...nurse, [k]: v });

  const toggleChannel = (c: Channel) => {
    const has = nurse.preferences.channels.includes(c);
    const next = has
      ? nurse.preferences.channels.filter((x) => x !== c)
      : [...nurse.preferences.channels, c];
    onChange({ ...nurse, preferences: { channels: next } });
  };

  return (
    <div className={compact ? "space-y-3" : "clay-card rounded-[20px] p-4 space-y-3"}>
      <div className="flex items-center gap-3">
        {dragHandleProps ? (
          <span
            {...dragHandleProps}
            className="cursor-grab text-muted-foreground/60 active:cursor-grabbing"
            title="Drag to reorder (offer priority tiebreak, display only)"
          >
            <GripVertical className="h-4 w-4" />
          </span>
        ) : null}
        <NurseAvatar name={nurse.name || "?"} url={nurse.avatar_url} size={38} />
        <div className="min-w-0 flex-1">
          <input
            value={nurse.name}
            onChange={(e) => set("name", e.target.value)}
            placeholder="Nurse name"
            className="clay-input w-full rounded-full px-3 py-1.5 text-[13px] font-semibold"
          />
          {errors.name ? (
            <span className="mt-1 block text-[10.5px] font-medium text-declined">
              {errors.name}
            </span>
          ) : null}
        </div>
        {!nurse.license_ok ? (
          <span
            className="clay-chip flex items-center gap-1 rounded-full px-2 py-1 text-[10px] font-semibold text-escalated"
            title="Unlicensed nurses are never offered shifts"
          >
            <ShieldAlert className="h-3 w-3" /> unlicensed
          </span>
        ) : null}
        {onRemove ? (
          <button
            type="button"
            onClick={onRemove}
            aria-label="Remove nurse from workflow"
            title="Removes membership, not the person"
            className="clay-pill grid h-8 w-8 place-items-center rounded-full text-muted-foreground hover:text-declined"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label="Phone (identity)"
          error={errors.phone}
          hint="E.164 — the number that calls the agency line"
        >
          <input
            value={nurse.phone}
            onChange={(e) => set("phone", e.target.value)}
            placeholder="+12015550142"
            inputMode="tel"
            className="clay-input w-full rounded-full px-3 py-1.5 text-[12.5px] tabular-nums"
          />
        </Field>
        <Field label="Specialty">
          <input
            value={nurse.specialties.join(", ")}
            onChange={(e) =>
              set(
                "specialties",
                e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
              )
            }
            placeholder="wound care"
            className="clay-input w-full rounded-full px-3 py-1.5 text-[12.5px]"
          />
        </Field>
        <Field label="Area">
          <input
            value={nurse.areas.join(", ")}
            onChange={(e) =>
              set("areas", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))
            }
            placeholder="Jersey City"
            className="clay-input w-full rounded-full px-3 py-1.5 text-[12.5px]"
          />
        </Field>
        <Field label="Avatar image URL (optional)">
          <input
            value={nurse.avatar_url}
            onChange={(e) => set("avatar_url", e.target.value)}
            placeholder="leave blank for initials"
            className="clay-input w-full rounded-full px-3 py-1.5 text-[12.5px]"
          />
        </Field>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Pay level">
          <div className="clay-pill flex items-center gap-1 rounded-full p-1">
            {[1, 2, 3].map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => set("pay_level", p as 1 | 2 | 3)}
                className={`flex-1 rounded-full px-2 py-1 text-[11px] font-semibold transition-all ${
                  nurse.pay_level === p ? "clay-pill-active text-router" : "text-muted-foreground"
                }`}
              >
                {"$".repeat(p)}
              </button>
            ))}
          </div>
        </Field>
        <Field label={`Reliability · ${Math.round(nurse.reliability * 100)}%`}>
          <input
            type="range"
            min={0}
            max={100}
            value={Math.round(nurse.reliability * 100)}
            onChange={(e) => set("reliability", Number(e.target.value) / 100)}
            className="mt-2 w-full accent-[var(--ring-router)]"
          />
        </Field>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Comfortable channels
          </span>
          <div className="flex gap-1.5">
            {CHANNELS.map((c) => {
              const on = nurse.preferences.channels.includes(c);
              return (
                <button
                  key={c}
                  type="button"
                  onClick={() => toggleChannel(c)}
                  title="the outreach ladder only uses channels the nurse opted into"
                  className={`rounded-full px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-[0.06em] transition-all ${
                    on ? "clay-pill-active" : "clay-chip opacity-55"
                  }`}
                  style={{ color: on ? CHANNEL_COLOR[c] : "var(--muted-foreground)" }}
                  aria-pressed={on}
                >
                  {c}
                </button>
              );
            })}
          </div>
          {errors.channels ? (
            <span className="mt-1 block text-[10.5px] font-medium text-declined">
              {errors.channels}
            </span>
          ) : null}
        </div>

        <button
          type="button"
          onClick={() => set("license_ok", !nurse.license_ok)}
          aria-pressed={nurse.license_ok}
          className={`clay-pill flex items-center gap-2 rounded-full px-3 py-1.5 text-[11px] font-semibold ${
            nurse.license_ok ? "text-accepted" : "text-escalated"
          }`}
        >
          <i
            className="block h-2 w-2 rounded-full"
            style={{
              background: nurse.license_ok ? "var(--ring-accepted)" : "var(--ring-escalated)",
            }}
          />
          {nurse.license_ok ? "licensed" : "not licensed"}
        </button>
      </div>
    </div>
  );
}
