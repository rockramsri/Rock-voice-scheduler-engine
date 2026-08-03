/** Small popup to edit ONE nurse without opening the whole workflow. */
import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { hasErrors, validateNurse, type NurseProfile } from "@/lib/workflow-store";
import { NurseForm } from "./NurseForm";

export function NurseProfileDialog({
  nurse,
  peers,
  onOpenChange,
  onSave,
}: {
  nurse: NurseProfile | null;
  peers: NurseProfile[]; // for duplicate-phone detection
  onOpenChange: (v: boolean) => void;
  onSave: (n: NurseProfile) => void;
}) {
  const [draft, setDraft] = useState<NurseProfile | null>(nurse);
  useEffect(() => setDraft(nurse), [nurse]);
  if (!draft) return null;

  const errors = validateNurse(draft, [...peers.filter((p) => p.id !== draft.id), draft]);
  const invalid = hasErrors(errors);

  return (
    <Dialog open={Boolean(nurse)} onOpenChange={onOpenChange}>
      <DialogContent className="clay-panel max-h-[85vh] overflow-y-auto rounded-[28px] border-0 sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="text-[16px] font-bold">Edit profile</DialogTitle>
          <DialogDescription className="text-[12px]">
            Changes apply to this person everywhere. Agents identify people by NAME on calls,
            so keep names unique; phones may be shared (handy for solo testing).
          </DialogDescription>
        </DialogHeader>

        <NurseForm nurse={draft} errors={errors} onChange={setDraft} compact />

        <div className="mt-2 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="clay-pill rounded-full px-4 py-2 text-[12px] font-semibold text-muted-foreground"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={invalid}
            onClick={() => {
              onSave(draft);
              onOpenChange(false);
            }}
            className="clay-pill-active rounded-full px-5 py-2 text-[12.5px] font-semibold text-router disabled:opacity-45"
          >
            Save profile
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
