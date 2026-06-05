// Zustand store: the single source of truth for the driver session.
// Holds the local driver identity, share-location state, the live position /
// ping counter, plus the latest congestion field, green-wave advice and
// guidance (whether from the orchestrator or demo fallback).

import { create } from "zustand";
import type {
  CongestionCell,
  Driver,
  DriverGuidance,
  GpsFix,
  LatLng,
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
    });
  },
}));
