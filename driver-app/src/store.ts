// Zustand store: the single source of truth for the driver session.
// Holds the local driver identity, share-location state, the live position /
// ping counter, plus the latest congestion field, green-wave advice and
// guidance (whether from the orchestrator or demo fallback).

import { create } from "zustand";
import type {
  CongestionCell,
  DeliveryJob,
  DirectionsResult,
  Driver,
  DriverGuidance,
  GpsFix,
  LatLng,
  Maneuver,
  Plan,
  Route,
  SignalAdvice,
} from "./types";

const LS_KEY = "rlj-driver"; // localStorage: persisted driver identity

/** Liveness of each optional data source — drives graceful-degradation UI. */
export type Source = "live" | "demo" | "off";

interface DriverState {
  // identity
  driver: Driver | null;
  // session
  sharing: boolean;
  geoMode: "gps" | "sim" | null; // resolved at first ping
  position: LatLng | null;
  lastFix: GpsFix | null;
  pings: number; // pings sent THIS session (local truth)
  // server-derived
  congestion: CongestionCell[];
  congestionSource: Source;
  guidance: DriverGuidance | null;
  advice: SignalAdvice | null;
  guidanceSource: Source;
  guidanceAvailable: boolean; // false => endpoint 404'd, hide the card
  orchestratorOnline: boolean;
  // jobs + active delivery + turn-by-turn
  jobs: DeliveryJob[];
  jobsSource: Source;
  plan: Plan | null;
  navigating: boolean;
  directions: DirectionsResult | null;
  maneuver: Maneuver | null; // next maneuver while navigating
  maneuverDist: number; // metres to the next maneuver

  // actions
  setDriver: (d: Driver | null) => void;
  setSharing: (v: boolean) => void;
  setGeoMode: (m: "gps" | "sim" | null) => void;
  recordFix: (fix: GpsFix) => void; // also bumps ping count
  setCongestion: (cells: CongestionCell[], source: Source) => void;
  setGuidance: (g: DriverGuidance | null, source: Source) => void;
  setAdvice: (a: SignalAdvice | null) => void;
  setGuidanceAvailable: (v: boolean) => void;
  setOrchestratorOnline: (v: boolean) => void;
  setJobs: (jobs: DeliveryJob[], source: Source) => void;
  setPlan: (plan: Plan | null) => void;
  setNavigating: (v: boolean) => void;
  setDirections: (d: DirectionsResult | null) => void;
  setManeuver: (m: Maneuver | null, dist: number) => void;
  signOut: () => void;
}

function loadDriver(): Driver | null {
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw ? (JSON.parse(raw) as Driver) : null;
  } catch {
    return null;
  }
}

function persistDriver(d: Driver | null) {
  try {
    if (d) localStorage.setItem(LS_KEY, JSON.stringify(d));
    else localStorage.removeItem(LS_KEY);
  } catch {
    /* private mode / quota — non-fatal */
  }
}

export const useStore = create<DriverState>((set) => ({
  driver: loadDriver(),
  sharing: false,
  geoMode: null,
  position: null,
  lastFix: null,
  pings: 0,
  congestion: [],
  congestionSource: "off",
  guidance: null,
  advice: null,
  guidanceSource: "off",
  guidanceAvailable: true,
  orchestratorOnline: false,
  jobs: [],
  jobsSource: "off",
  plan: null,
  navigating: false,
  directions: null,
  maneuver: null,
  maneuverDist: 0,

  setDriver: (d) => {
    persistDriver(d);
    set({ driver: d });
  },
  setSharing: (v) => set(v ? { sharing: true } : { sharing: false, geoMode: null }),
  setGeoMode: (m) => set({ geoMode: m }),
  recordFix: (fix) =>
    set((s) => ({
      lastFix: fix,
      position: { lat: fix.lat, lng: fix.lng },
      pings: s.pings + 1,
    })),
  setCongestion: (cells, source) =>
    set({ congestion: cells, congestionSource: source }),
  setGuidance: (g, source) =>
    set({
      guidance: g,
      guidanceSource: source,
      advice: g?.signal_advice ?? null,
    }),
  setAdvice: (a) => set({ advice: a }),
  setGuidanceAvailable: (v) => set({ guidanceAvailable: v }),
  setOrchestratorOnline: (v) => set({ orchestratorOnline: v }),
  setJobs: (jobs, source) => set({ jobs, jobsSource: source }),
  setPlan: (plan) => set({ plan }),
  setNavigating: (v) =>
    set(v ? { navigating: true } : { navigating: false, maneuver: null, maneuverDist: 0 }),
  setDirections: (d) => set({ directions: d }),
  setManeuver: (m, dist) => set({ maneuver: m, maneuverDist: dist }),
  signOut: () => {
    persistDriver(null);
    set({
      driver: null,
      sharing: false,
      geoMode: null,
      position: null,
      lastFix: null,
      pings: 0,
      guidance: null,
      advice: null,
      jobs: [],
      plan: null,
      navigating: false,
      directions: null,
      maneuver: null,
    });
  },
}));

// ---- derived selectors ----------------------------------------------------

const UPCOMING_STATUS = ["new", "assigned", "in_transit"];
const PAST_STATUS = ["delivered", "failed"];

/** The active route (first route in the plan — the PWA driver runs one route). */
export function selectActiveRoute(s: DriverState): Route | null {
  return s.plan?.routes?.[0] ?? null;
}

/** The active delivery: the in-transit job, else the first upcoming job. */
export function selectActiveJob(s: DriverState): DeliveryJob | null {
  const inTransit = s.jobs.find((j) => j.status === "in_transit");
  if (inTransit) return inTransit;
  const route = selectActiveRoute(s);
  if (route) {
    const byId = new Map(s.jobs.map((j) => [j.id, j]));
    for (const stop of [...route.stops].sort((a, b) => a.sequence - b.sequence)) {
      const job = byId.get(stop.job_id);
      if (job && UPCOMING_STATUS.includes(job.status)) return job;
    }
  }
  return s.jobs.find((j) => UPCOMING_STATUS.includes(j.status)) ?? null;
}

export function selectUpcoming(s: DriverState): DeliveryJob[] {
  const route = selectActiveRoute(s);
  const order = new Map(
    (route?.stops ?? []).map((st, i) => [st.job_id, st.sequence ?? i]),
  );
  return s.jobs
    .filter((j) => UPCOMING_STATUS.includes(j.status))
    .sort((a, b) => (order.get(a.id) ?? 999) - (order.get(b.id) ?? 999));
}

export function selectPast(s: DriverState): DeliveryJob[] {
  return s.jobs
    .filter((j) => PAST_STATUS.includes(j.status))
    .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
}
