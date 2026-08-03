/** Mock-profile gallery popup — click a card to inject it into a nurse slot. */
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { MOCK_PROFILES, uid, type NurseProfile } from "@/lib/workflow-store";
import { NurseAvatar } from "./Avatar";

export function MockGallery({
  open,
  onOpenChange,
  onInject,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onInject: (n: NurseProfile) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="clay-panel max-h-[85vh] overflow-y-auto rounded-[28px] border-0 sm:max-w-[720px]">
        <DialogHeader>
          <DialogTitle className="text-[16px] font-bold">Inject a mock profile</DialogTitle>
          <DialogDescription className="text-[12px]">
            Each card includes a next-shift tag. On save, that shift is written to the live
            calendar so callouts work end-to-end. Add your real phone; duplicates are fine.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 sm:grid-cols-2">
          {MOCK_PROFILES.map((p) => (
            <button
              key={p.name}
              type="button"
              onClick={() => {
                const next = {
                  ...p,
                  id: uid(),
                  preferences: { channels: [...p.preferences.channels] },
                };
                if (p.demo_shift) next.demo_shift = { ...p.demo_shift };
                onInject(next);
                onOpenChange(false);
              }}
              className="clay-card rounded-[20px] p-3 text-left transition-transform hover:-translate-y-0.5"
            >
              <div className="flex items-center gap-3">
                <NurseAvatar name={p.name} size={38} />
                <div className="min-w-0">
                  <span className="block truncate text-[13px] font-semibold text-foreground">
                    {p.name}
                  </span>
                  <span className="block truncate text-[11px] text-muted-foreground">
                    {p.specialties[0]} · {p.areas[0]}
                  </span>
                </div>
              </div>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {p.demo_shift && (
                  <span
                    className="clay-chip rounded-full px-2 py-0.5 text-[10px] font-semibold"
                    style={{
                      color: p.demo_shift.offset_days === 0
                        ? "var(--ring-escalated)"
                        : "var(--ring-accepted)",
                    }}
                  >
                    shift {p.demo_shift.label}
                  </span>
                )}
                <span className="clay-chip rounded-full px-2 py-0.5 text-[10px] font-semibold text-router">
                  {"$".repeat(p.pay_level)}
                </span>
                <span className="clay-chip rounded-full px-2 py-0.5 text-[10px] font-semibold text-calling">
                  {Math.round(p.reliability * 100)}% reliable
                </span>
                <span
                  className="clay-chip rounded-full px-2 py-0.5 text-[10px] font-semibold"
                  style={{
                    color: p.license_ok ? "var(--ring-accepted)" : "var(--ring-escalated)",
                  }}
                >
                  {p.license_ok ? "licensed" : "unlicensed"}
                </span>
              </div>
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
