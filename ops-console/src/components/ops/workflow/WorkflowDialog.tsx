/**
 * Create / edit workflow dialog.
 * Owns a DRAFT copy of the workflow + its members; nothing escapes until Save,
 * which calls the single persistence seam in `useWorkflowStore.saveWorkflow`.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Plus, Sparkles, UserPlus, Trash2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  emptyNurse,
  hasErrors,
  uid,
  validateNurse,
  type NurseProfile,
  type Workflow,
} from "@/lib/workflow-store";
import { NurseForm } from "./NurseForm";
import { MockGallery } from "./MockGallery";

export function WorkflowDialog({
  open,
  onOpenChange,
  workflow,
  members,
  saving,
  onSave,
  onDelete,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  workflow: Workflow | null; // null = create mode
  members: NurseProfile[];
  saving: boolean;
  onSave: (w: Workflow, members: NurseProfile[]) => Promise<unknown>;
  onDelete?: (id: string) => void;
}) {
  const isEdit = Boolean(workflow);
  const [name, setName] = useState("");
  const [active, setActive] = useState(true);
  const [draft, setDraft] = useState<NurseProfile[]>([]);
  const [galleryFor, setGalleryFor] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const dragIndex = useRef<number | null>(null);

  // Reset the draft ONLY when the dialog opens (or switches workflow) —
  // `members` gets a fresh array identity on every parent render, and parents
  // re-render constantly (demo autoplay, live realtime events). Depending on
  // it wiped in-progress edits, e.g. a freshly injected mock profile.
  const membersRef = useRef(members);
  membersRef.current = members;

  useEffect(() => {
    if (!open) return;
    const current = membersRef.current;
    setName(workflow?.name ?? "");
    setActive(workflow?.active ?? true);
    setDraft(
      current.length
        ? current.map((m) => ({ ...m, preferences: { channels: [...m.preferences.channels] } }))
        : [emptyNurse(), emptyNurse(), emptyNurse()], // 3 empty slots on create
    );
    setTouched(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, workflow?.id]);

  const filled = draft.filter((n) => n.name.trim() || n.phone.trim());
  const errorsById = useMemo(() => {
    const map: Record<string, ReturnType<typeof validateNurse>> = {};
    for (const n of filled) map[n.id] = validateNurse(n, filled);
    return map;
  }, [filled]);

  const nameError = name.trim() ? "" : "Workflow name is required";
  const anyNurseError = filled.some((n) => hasErrors(errorsById[n.id] ?? {}));
  const blockedReason = !name.trim()
    ? "Name the workflow to save"
    : filled.length === 0
      ? "Add at least one nurse with a phone number"
      : anyNurseError
        ? "Fix the highlighted nurse fields"
        : "";
  const canSave = !blockedReason && !saving;

  const update = (n: NurseProfile) =>
    setDraft((d) => d.map((x) => (x.id === n.id ? n : x)));

  const inject = (slotId: string, profile: NurseProfile) =>
    setDraft((d) => d.map((x) => (x.id === slotId ? { ...profile, id: x.id } : x)));

  const reorder = (from: number, to: number) =>
    setDraft((d) => {
      const copy = [...d];
      const [moved] = copy.splice(from, 1);
      if (moved) copy.splice(to, 0, moved);
      return copy;
    });

  const save = async () => {
    setTouched(true);
    if (!canSave) return;
    const wf: Workflow = workflow
      ? { ...workflow, name: name.trim(), active }
      : {
          id: uid(),
          name: name.trim(),
          kind: "scheduling",
          nurse_ids: [],
          active,
          created_at: new Date().toISOString(),
        };
    await onSave(wf, filled);
    onOpenChange(false);
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="clay-panel max-h-[88vh] overflow-y-auto rounded-[28px] border-0 sm:max-w-[760px]">
          <DialogHeader>
            <DialogTitle className="text-[16px] font-bold">
              {isEdit ? "Edit workflow" : "Register workflow"}
            </DialogTitle>
            <DialogDescription className="text-[12px]">
              A workflow is a roster: the nurses whose real phone numbers the voice agent
              recognises, and the channels each of them opted into.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <label className="block min-w-0">
              <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Workflow name
              </span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Rockram Home Health Care"
                className="clay-input w-full rounded-full px-4 py-2 text-[13px] font-semibold"
              />
              {touched && nameError ? (
                <span className="mt-1 block text-[10.5px] font-medium text-declined">
                  {nameError}
                </span>
              ) : null}
            </label>
            <button
              type="button"
              onClick={() => setActive((a) => !a)}
              aria-pressed={active}
              className={`clay-pill flex items-center gap-2 rounded-full px-4 py-2 text-[12px] font-semibold ${
                active ? "text-accepted" : "text-muted-foreground"
              }`}
            >
              <i
                className="block h-2 w-2 rounded-full"
                style={{ background: active ? "var(--ring-accepted)" : "var(--ring-idle)" }}
              />
              {active ? "active" : "paused"}
            </button>
          </div>

          <div className="mt-2 flex items-center justify-between">
            <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              Nurses · {filled.length} valid
            </span>
            <button
              type="button"
              onClick={() => setDraft((d) => [...d, emptyNurse()])}
              className="clay-pill flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11.5px] font-semibold text-router"
            >
              <Plus className="h-3.5 w-3.5" strokeWidth={2.6} /> Add slot
            </button>
          </div>

          <div className="space-y-3">
            {draft.map((n, i) => {
              const isBlank = !n.name.trim() && !n.phone.trim();
              return (
                <div
                  key={n.id}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => {
                    if (dragIndex.current !== null && dragIndex.current !== i)
                      reorder(dragIndex.current, i);
                    dragIndex.current = null;
                  }}
                >
                  {isBlank ? (
                    <div className="clay-empty flex flex-col items-center gap-3 rounded-[20px] px-4 py-6 text-center">
                      <span className="text-[12px] font-semibold text-foreground/70">
                        Empty nurse slot {i + 1}
                      </span>
                      <div className="flex flex-wrap justify-center gap-2">
                        <button
                          type="button"
                          onClick={() => setGalleryFor(n.id)}
                          className="clay-pill flex items-center gap-1.5 rounded-full px-3.5 py-2 text-[12px] font-semibold text-router"
                        >
                          <Sparkles className="h-3.5 w-3.5" strokeWidth={2.6} /> Inject mock profile
                        </button>
                        <button
                          type="button"
                          onClick={() => update({ ...n, name: "New nurse" })}
                          className="clay-pill flex items-center gap-1.5 rounded-full px-3.5 py-2 text-[12px] font-semibold text-foreground"
                        >
                          <UserPlus className="h-3.5 w-3.5" strokeWidth={2.6} /> Add your own
                        </button>
                        {draft.length > 1 ? (
                          <button
                            type="button"
                            onClick={() => setDraft((d) => d.filter((x) => x.id !== n.id))}
                            aria-label="Remove empty slot"
                            className="clay-pill grid h-9 w-9 place-items-center rounded-full text-muted-foreground"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        ) : null}
                      </div>
                    </div>
                  ) : (
                    <NurseForm
                      nurse={n}
                      errors={touched || n.phone ? (errorsById[n.id] ?? {}) : {}}
                      onChange={update}
                      onRemove={() => setDraft((d) => d.filter((x) => x.id !== n.id))}
                      dragHandleProps={{
                        draggable: true,
                        onDragStart: () => {
                          dragIndex.current = i;
                        },
                      }}
                    />
                  )}
                </div>
              );
            })}
          </div>

          <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
            <span className="text-[11px] text-muted-foreground">
              {blockedReason || "Ready to save"}
            </span>
            <div className="flex items-center gap-2">
              {isEdit && onDelete && workflow ? (
                <button
                  type="button"
                  onClick={() => {
                    onDelete(workflow.id);
                    onOpenChange(false);
                  }}
                  className="clay-pill rounded-full px-4 py-2 text-[12px] font-semibold text-declined"
                >
                  Delete
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                className="clay-pill rounded-full px-4 py-2 text-[12px] font-semibold text-muted-foreground"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={save}
                disabled={!canSave}
                className="clay-pill-active flex items-center gap-2 rounded-full px-5 py-2 text-[12.5px] font-semibold text-router disabled:opacity-45"
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {saving ? "Saving…" : isEdit ? "Save changes" : "Register workflow"}
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <MockGallery
        open={galleryFor !== null}
        onOpenChange={(v) => setGalleryFor(v ? galleryFor : null)}
        onInject={(p) => galleryFor && inject(galleryFor, p)}
      />
    </>
  );
}
