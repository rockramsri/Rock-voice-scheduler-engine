// Left panel: register/edit workflows. A workflow = named scenario mapping
// real phone numbers onto nurse profiles (typed in, or mock-injected) with
// per-nurse channel preferences. Saves write straight to Supabase; the
// backend picks nurses up from the same tables on the next callout.

import { useState } from "react";
import { avatarFor } from "../avatar";
import { ALL_CHANNELS, MOCK_PROFILES } from "../mock";
import { supabase } from "../supabase";
import type { Nurse, Workflow } from "../types";

interface Draft {
  id?: string;
  name: string;
  nurses: NurseDraft[];
}
interface NurseDraft {
  id?: string;
  name: string;
  phone: string;
  specialty: string;
  area: string;
  channels: string[];
}

const EMPTY_NURSE: NurseDraft = { name: "", phone: "", specialty: "wound care",
                                  area: "Jersey City", channels: [...ALL_CHANNELS] };

interface Props {
  workflows: Workflow[];
  nurses: Nurse[];
  agencyId: string;
  refresh: () => void;
}

export default function WorkflowPanel({ workflows, nurses, agencyId, refresh }: Props) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const byId = new Map(nurses.map((n) => [n.id, n]));

  const startNew = () => setDraft({ name: `Workflow ${workflows.length + 1}`,
                                    nurses: [{ ...EMPTY_NURSE }, { ...EMPTY_NURSE }, { ...EMPTY_NURSE }] });
  const startEdit = (wf: Workflow) => setDraft({
    id: wf.id, name: wf.name,
    nurses: wf.nurse_ids.map((id) => {
      const n = byId.get(id);
      return n ? { id: n.id, name: n.name, phone: n.phone, specialty: n.specialties[0] ?? "",
                   area: n.areas[0] ?? "", channels: n.preferences?.channels ?? [...ALL_CHANNELS] }
               : { ...EMPTY_NURSE };
    }),
  });

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const ids: string[] = [];
      for (const nd of draft.nurses) {
        if (!nd.phone.trim() || !nd.name.trim()) continue;
        const row = {
          agency_id: agencyId, name: nd.name.trim(), phone: nd.phone.trim(),
          specialties: [nd.specialty], areas: [nd.area],
          preferences: { channels: nd.channels },
          availability: Array.from({ length: 7 }, (_, dow) =>
            ({ dow, start: "07:00", end: "20:00" })),
        };
        const { data } = await supabase.from("nurses")
          .upsert(row, { onConflict: "phone" }).select("id").single();
        if (data) ids.push(data.id);
      }
      const wfRow = { agency_id: agencyId, name: draft.name, nurse_ids: ids };
      if (draft.id) await supabase.from("workflows").update(wfRow).eq("id", draft.id);
      else await supabase.from("workflows").insert(wfRow);
      setDraft(null);
      refresh();
    } finally {
      setSaving(false);
    }
  };

  if (draft) {
    return (
      <div className="panel-body">
        <input className="input title" value={draft.name}
               onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        {draft.nurses.map((nd, i) => (
          <NurseEditor key={i} nd={nd} index={i}
            onChange={(next) => setDraft({ ...draft,
              nurses: draft.nurses.map((x, j) => (j === i ? next : x)) })}
            onRemove={() => setDraft({ ...draft,
              nurses: draft.nurses.filter((_, j) => j !== i) })} />
        ))}
        <button className="btn ghost" onClick={() =>
          setDraft({ ...draft, nurses: [...draft.nurses, { ...EMPTY_NURSE }] })}>
          + add nurse
        </button>
        <div className="row gap">
          <button className="btn primary" disabled={saving} onClick={save}>
            {saving ? "Saving..." : "Save workflow"}
          </button>
          <button className="btn ghost" onClick={() => setDraft(null)}>Cancel</button>
        </div>
        <p className="hint">Saving upserts each nurse by phone number — a nurse calling
          from a registered number is recognized instantly.</p>
      </div>
    );
  }

  return (
    <div className="panel-body">
      <button className="btn primary wide" onClick={startNew}>+ Register workflow</button>
      {workflows.map((wf) => (
        <button key={wf.id} className="wf-card" onClick={() => startEdit(wf)}>
          <div className="t">{wf.name}</div>
          <div className="s">{wf.kind} · {wf.nurse_ids.length} nurses</div>
          <div className="avatars">
            {wf.nurse_ids.slice(0, 5).map((id) => {
              const n = byId.get(id);
              return n ? <img key={id} className="avatar sm" title={n.name}
                              src={avatarFor(n.name, n.avatar_url)} /> : null;
            })}
          </div>
        </button>
      ))}
      {workflows.length === 0 && <div className="empty">No workflows yet.</div>}
    </div>
  );
}

function NurseEditor({ nd, index, onChange, onRemove }:
  { nd: NurseDraft; index: number; onChange: (n: NurseDraft) => void; onRemove: () => void }) {
  const injectMock = () => {
    const mock = MOCK_PROFILES[index % MOCK_PROFILES.length];
    onChange({ ...nd, name: mock.name, specialty: mock.specialties[0], area: mock.areas[0] });
  };
  return (
    <div className="nurse-editor">
      <div className="row gap">
        <img className="avatar md" src={avatarFor(nd.name || "?")} />
        <input className="input" placeholder="Nurse name" value={nd.name}
               onChange={(e) => onChange({ ...nd, name: e.target.value })} />
        <button className="btn tiny" title="Fill with a mock profile" onClick={injectMock}>mock</button>
        <button className="btn tiny danger" onClick={onRemove}>x</button>
      </div>
      <input className="input" placeholder="+1 phone (real, E.164)" value={nd.phone}
             onChange={(e) => onChange({ ...nd, phone: e.target.value })} />
      <div className="row gap">
        <input className="input half" placeholder="specialty" value={nd.specialty}
               onChange={(e) => onChange({ ...nd, specialty: e.target.value })} />
        <input className="input half" placeholder="area" value={nd.area}
               onChange={(e) => onChange({ ...nd, area: e.target.value })} />
      </div>
      <div className="row gap chips">
        {ALL_CHANNELS.map((ch) => (
          <label key={ch} className={`chip ${nd.channels.includes(ch) ? "on" : ""}`}>
            <input type="checkbox" checked={nd.channels.includes(ch)}
                   onChange={(e) => onChange({ ...nd,
                     channels: e.target.checked
                       ? [...nd.channels, ch]
                       : nd.channels.filter((c) => c !== ch) })} />
            {ch}
          </label>
        ))}
        <span className="hint">comfortable channels</span>
      </div>
    </div>
  );
}
