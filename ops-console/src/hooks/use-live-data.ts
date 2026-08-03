/**
 * One hook owns all data: initial fetch + Supabase Realtime merges.
 * The graph, log, and rail all re-render from this state.
 */
import { useEffect, useState } from "react";
import { supabase, type EventRow, type Nurse, type Offer, type Shift,
         type Workflow } from "@/lib/supabase";

export interface LiveData {
  nurses: Nurse[];
  workflows: Workflow[];
  shifts: Shift[];
  offers: Offer[];
  events: EventRow[];
  agencyId: string;
  refresh: () => void;
}

function upsert<T extends { id: string | number }>(rows: T[], row: T): T[] {
  const i = rows.findIndex((r) => r.id === row.id);
  if (i === -1) return [...rows, row];
  const next = rows.slice();
  next[i] = { ...next[i], ...row };
  return next;
}

/**
 * Apply one realtime change. On DELETE, payload.new is `{}`, so upserting it
 * would briefly insert a nameless row (and crash consumers that read row.name);
 * remove by payload.old.id instead.
 */
function applyChange<T extends { id: string | number }>(
  rows: T[],
  p: { eventType: string; new: Record<string, unknown>; old: Record<string, unknown> },
): T[] {
  if (p.eventType === "DELETE") {
    const id = p.old?.["id"] as T["id"] | undefined;
    return id === undefined ? rows : rows.filter((r) => r.id !== id);
  }
  return upsert(rows, p.new as unknown as T);
}

export function useLiveData(): LiveData {
  const [nurses, setNurses] = useState<Nurse[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [shifts, setShifts] = useState<Shift[]>([]);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [agencyId, setAgencyId] = useState("");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [ag, nu, wf, sh, of, ev] = await Promise.all([
        supabase.from("agencies").select("id").limit(1),
        supabase.from("nurses").select("*").order("name"),
        supabase.from("workflows").select("*").order("created_at", { ascending: false }),
        supabase.from("shifts").select("*, patients(name, area)").order("starts_at"),
        supabase.from("offers").select("*"),
        supabase.from("events").select("*").order("id", { ascending: false }).limit(300),
      ]);
      if (cancelled) return;
      setAgencyId((ag.data?.[0] as { id: string } | undefined)?.id ?? "");
      setNurses((nu.data as Nurse[]) ?? []);
      setWorkflows((wf.data as Workflow[]) ?? []);
      setShifts((sh.data as Shift[]) ?? []);
      setOffers((of.data as Offer[]) ?? []);
      setEvents((ev.data as EventRow[]) ?? []);
    })();
    return () => {
      cancelled = true;
    };
  }, [tick]);

  useEffect(() => {
    const channel = supabase
      .channel("live")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "events" },
        (p) => setEvents((rows) => [p.new as EventRow, ...rows].slice(0, 500)))
      .on("postgres_changes", { event: "*", schema: "public", table: "shifts" },
        (p) => setShifts((rows) => applyChange(rows, p)))
      .on("postgres_changes", { event: "*", schema: "public", table: "offers" },
        (p) => setOffers((rows) => applyChange(rows, p)))
      .on("postgres_changes", { event: "*", schema: "public", table: "nurses" },
        (p) => setNurses((rows) => applyChange(rows, p)))
      .on("postgres_changes", { event: "*", schema: "public", table: "workflows" },
        (p) => setWorkflows((rows) => applyChange(rows, p)))
      .subscribe();
    return () => {
      void supabase.removeChannel(channel);
    };
  }, []);

  return { nurses, workflows, shifts, offers, events, agencyId,
           refresh: () => setTick((t) => t + 1) };
}
