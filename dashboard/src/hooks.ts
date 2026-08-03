// One hook owns all data: initial fetch + Supabase Realtime merges.
// Everything downstream (graph, log, panel) re-renders from this state.

import { useEffect, useState } from "react";
import { supabase } from "./supabase";
import type { EventRow, Nurse, Offer, Shift, Workflow } from "./types";

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
        supabase.from("events").select("*").order("id", { ascending: false }).limit(250),
      ]);
      if (cancelled) return;
      setAgencyId(ag.data?.[0]?.id ?? "");
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
        (p) => setEvents((rows) => [p.new as EventRow, ...rows].slice(0, 400)))
      .on("postgres_changes", { event: "*", schema: "public", table: "shifts" },
        (p) => setShifts((rows) => upsert(rows, p.new as Shift)))
      .on("postgres_changes", { event: "*", schema: "public", table: "offers" },
        (p) => setOffers((rows) => upsert(rows, p.new as Offer)))
      .on("postgres_changes", { event: "*", schema: "public", table: "nurses" },
        (p) => setNurses((rows) => upsert(rows, p.new as Nurse)))
      .on("postgres_changes", { event: "*", schema: "public", table: "workflows" },
        (p) => setWorkflows((rows) => upsert(rows, p.new as Workflow)))
      .subscribe();
    return () => {
      void supabase.removeChannel(channel);
    };
  }, []);

  return { nurses, workflows, shifts, offers, events, agencyId,
           refresh: () => setTick((t) => t + 1) };
}
