/**
 * Left rail: registered workflows (roster scenarios) for the voice scheduling agent.
 *
 * LOCAL MOCK STATE ONLY — all data lives in `useWorkflowStore` (src/lib/workflow-store.ts).
 * To wire the real backend, replace `persistWorkflow` / `persistDeleteWorkflow` there and
 * seed `workflows` / `nurses` from a loader. This component needs no changes.
 *
 * States covered: rail-empty · rail-list · create-dialog · mock-gallery-popup ·
 * edit-workflow-dialog · edit-single-profile-popup · validation-errors · save-in-progress
 */
import { useState } from "react";
import { Plus, Users, Workflow as WorkflowIcon } from "lucide-react";
import {
  useWorkflowStore,
  type Channel,
  type LiveSource,
  type NurseProfile,
  type Workflow,
} from "@/lib/workflow-store";
import { NurseAvatar } from "./workflow/Avatar";
import { WorkflowDialog } from "./workflow/WorkflowDialog";
import { NurseProfileDialog } from "./workflow/NurseProfileDialog";

const CHANNEL_COLOR: Record<Channel, string> = {
  sms: "var(--ring-router)",
  whatsapp: "var(--ring-accepted)",
  voice: "var(--ring-calling)",
};

export function WorkflowRail(source: LiveSource) {
  const store = useWorkflowStore(source);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Workflow | null>(null);
  const [profile, setProfile] = useState<NurseProfile | null>(null);

  const openCreate = () => {
    setEditing(null);
    setDialogOpen(true);
  };
  const openEdit = (w: Workflow) => {
    setEditing(w);
    setDialogOpen(true);
  };

  return (
    <aside className="flex max-h-[calc(100vh-7rem)] flex-col gap-3">
      <div className="flex items-center justify-between px-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Workflows
        </h2>
        {store.workflows.length ? (
          <span className="clay-chip rounded-full px-2 py-0.5 text-[10px] font-semibold text-router">
            {store.workflows.length}
          </span>
        ) : null}
      </div>

      {/* rail scrolls internally, never the page */}
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-0.5">
        {store.workflows.length === 0 ? (
          <div className="clay-empty flex flex-col items-center gap-3 rounded-[22px] px-5 py-8 text-center">
            <span
              className="grid h-11 w-11 place-items-center rounded-2xl text-router"
              style={{ boxShadow: "var(--clay-out)" }}
            >
              <WorkflowIcon className="h-5 w-5" strokeWidth={2.2} />
            </span>
            <p className="text-[12.5px] font-semibold text-foreground">No workflows yet</p>
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              Register a roster of nurses with their real phone numbers. When one of them calls in
              sick, the agent offers their shift to the rest over their comfortable channels.
            </p>
          </div>
        ) : (
          store.workflows.map((w) => {
            const members = store.membersOf(w);
            return (
              <article
                key={w.id}
                className="clay-card rounded-[22px] px-4 py-3.5 transition-transform hover:-translate-y-0.5"
              >
                <button
                  type="button"
                  onClick={() => openEdit(w)}
                  className="flex w-full items-center gap-3 text-left"
                >
                  <span
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[11px] font-bold text-foreground/70"
                    style={{ boxShadow: "var(--clay-out)" }}
                  >
                    {w.name.slice(0, 2).toUpperCase()}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-semibold text-foreground">
                      {w.name}
                    </span>
                    <span className="block truncate text-[11px] text-muted-foreground">
                      {w.kind} · {members.length} nurse{members.length === 1 ? "" : "s"}
                    </span>
                  </span>
                </button>

                <div className="mt-3 flex items-center justify-between gap-2">
                  <div className="flex items-center">
                    {members.slice(0, 5).map((m, i) => (
                      <button
                        key={m.id}
                        type="button"
                        title={`Edit ${m.name}`}
                        onClick={() => setProfile(m)}
                        style={{ marginLeft: i === 0 ? 0 : -8, zIndex: 10 - i }}
                        className="relative transition-transform hover:-translate-y-0.5"
                      >
                        <NurseAvatar name={m.name} url={m.avatar_url} size={26} ring />
                      </button>
                    ))}
                    {members.length > 5 ? (
                      <span className="ml-1 text-[10.5px] font-semibold text-muted-foreground">
                        +{members.length - 5}
                      </span>
                    ) : (
                      <span className="ml-2 flex items-center gap-1 text-[10.5px] text-muted-foreground">
                        <Users className="h-3 w-3" />
                        {members.length}
                      </span>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => store.toggleWorkflow(w.id, !w.active)}
                    aria-pressed={w.active}
                    className={`clay-pill flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.06em] ${
                      w.active ? "text-accepted" : "text-muted-foreground"
                    }`}
                  >
                    <i
                      className="block h-1.5 w-1.5 rounded-full"
                      style={{
                        background: w.active ? "var(--ring-accepted)" : "var(--ring-idle)",
                      }}
                    />
                    {w.active ? "active" : "paused"}
                  </button>
                </div>

                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {(["sms", "whatsapp", "voice"] as Channel[])
                    .filter((c) => members.some((m) => m.preferences.channels.includes(c)))
                    .map((c) => (
                      <span
                        key={c}
                        className="clay-chip rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.06em]"
                        style={{ color: CHANNEL_COLOR[c] }}
                      >
                        {c}
                      </span>
                    ))}
                </div>
              </article>
            );
          })
        )}
      </div>

      <button
        type="button"
        onClick={openCreate}
        className="clay-card flex shrink-0 items-center justify-center gap-2 rounded-[22px] py-3.5 text-[13px] font-semibold text-router transition-transform hover:-translate-y-0.5"
      >
        <Plus className="h-4 w-4" strokeWidth={2.6} /> Register workflow
      </button>

      <WorkflowDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        workflow={editing}
        members={editing ? store.membersOf(editing) : []}
        saving={store.saving}
        onSave={store.saveWorkflow}
        onDelete={store.deleteWorkflow}
      />

      <NurseProfileDialog
        nurse={profile}
        peers={Object.values(store.nurses)}
        onOpenChange={(v) => !v && setProfile(null)}
        onSave={store.updateNurse}
      />
    </aside>
  );
}
