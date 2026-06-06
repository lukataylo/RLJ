// Global app state (zustand). Holds auth/identity, the live snapshot (jobs +
// plan + couriers) hydrated from REST and kept fresh by the WebSocket, and
// derived selectors for "my route" / "my jobs" given the chosen courier.

import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";
import type { Courier, DeliveryJob, Plan, Route } from "./types";

const COURIER_KEY = "pulsego.courierId";
const DRIVER_KEY = "pulsego.driverId";
const CONSENT_KEY = "pulsego.consent";

interface AppState {
  // identity
  authed: boolean;
  email: string | null;
  courierId: string | null;
  driverId: string | null;
  consent: boolean;
  // live snapshot
  jobs: DeliveryJob[];
  plan: Plan | null;
  couriers: Courier[];
  connected: boolean;
  lastEventAt: number | null;

  // actions
  setAuthed: (authed: boolean, email?: string | null) => void;
  setCourierId: (id: string | null) => void;
  setDriverId: (id: string | null) => void;
  setConsent: (v: boolean) => void;
  setConnected: (v: boolean) => void;
  setJobs: (jobs: DeliveryJob[]) => void;
  setCouriers: (couriers: Courier[]) => void;
  setPlan: (plan: Plan | null) => void;
  hydrateSnapshot: (payload: any) => void;
  upsertJob: (job: DeliveryJob) => void;
  bootIdentity: () => Promise<void>;
  signOut: () => void;
}

export const useStore = create<AppState>((set, get) => ({
  authed: false,
  email: null,
  courierId: null,
  driverId: null,
  consent: true,
  jobs: [],
  plan: null,
  couriers: [],
  connected: false,
  lastEventAt: null,

  setAuthed: (authed, email = null) => set({ authed, email }),
  setCourierId: (id) => {
    set({ courierId: id });
    if (id) AsyncStorage.setItem(COURIER_KEY, id).catch(() => {});
    else AsyncStorage.removeItem(COURIER_KEY).catch(() => {});
  },
  setDriverId: (id) => {
    set({ driverId: id });
    if (id) AsyncStorage.setItem(DRIVER_KEY, id).catch(() => {});
  },
  setConsent: (v) => {
    set({ consent: v });
    AsyncStorage.setItem(CONSENT_KEY, v ? "1" : "0").catch(() => {});
  },
  setConnected: (v) => set({ connected: v }),
  setJobs: (jobs) => set({ jobs }),
  setCouriers: (couriers) => set({ couriers }),
  setPlan: (plan) => set({ plan }),

  hydrateSnapshot: (payload) =>
    set({
      jobs: payload?.jobs ?? get().jobs,
      plan: payload?.plan ?? get().plan,
      couriers: payload?.couriers ?? get().couriers,
      lastEventAt: Date.now(),
    }),

  upsertJob: (job) => {
    const jobs = get().jobs.slice();
    const i = jobs.findIndex((j) => j.id === job.id);
    if (i >= 0) jobs[i] = job;
    else jobs.unshift(job);
    set({ jobs, lastEventAt: Date.now() });
  },

  bootIdentity: async () => {
    const [courierId, driverId, consent] = await Promise.all([
      AsyncStorage.getItem(COURIER_KEY),
      AsyncStorage.getItem(DRIVER_KEY),
      AsyncStorage.getItem(CONSENT_KEY),
    ]);
    set({
      courierId: courierId ?? null,
      driverId: driverId ?? null,
      consent: consent === null ? true : consent === "1",
    });
  },

  signOut: () => {
    AsyncStorage.multiRemove([COURIER_KEY, DRIVER_KEY]).catch(() => {});
    set({
      authed: false,
      email: null,
      courierId: null,
      driverId: null,
      jobs: [],
      plan: null,
      couriers: [],
    });
  },
}));

// ---- derived selectors ----------------------------------------------------

/** The route assigned to the chosen courier (or null). */
export function selectMyRoute(s: AppState): Route | null {
  if (!s.courierId || !s.plan) return null;
  return s.plan.routes.find((r) => r.courier_id === s.courierId) ?? null;
}

/** The chosen courier record. */
export function selectMyCourier(s: AppState): Courier | null {
  if (!s.courierId) return null;
  return s.couriers.find((c) => c.id === s.courierId) ?? null;
}

/** Jobs referenced by my route's stops, in stop order. Falls back to []. */
export function selectMyJobs(s: AppState): DeliveryJob[] {
  const route = selectMyRoute(s);
  if (!route) return [];
  const byId = new Map(s.jobs.map((j) => [j.id, j]));
  const seen = new Set<string>();
  const out: DeliveryJob[] = [];
  for (const stop of [...route.stops].sort((a, b) => a.sequence - b.sequence)) {
    if (seen.has(stop.job_id)) continue;
    seen.add(stop.job_id);
    const job = byId.get(stop.job_id);
    if (job) out.push(job);
  }
  return out;
}
