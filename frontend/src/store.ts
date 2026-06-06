// Small zustand store holding live operational state, updated from WS events.
// Single source of truth for the UI; also retains a short metric history for sparklines.

import { create } from "zustand";
import type {
  AgentAnswer,
  AgentLog,
  CctvCamera,
  CongestionField,
  Courier,
  DeliveryJob,
  DisruptionEvent,
  Driver,
  FleetAssessment,
  MetricSample,
  Notification,
  Plan,
  SignalRec,
  StateSnapshot,
  WsEvent,
} from "./types";
import { sampleMetrics } from "./lib/format";
import { getToken, setToken, type AuthUser } from "./api";

const ROLE_KEY = "pulsego_role";

function readRole(): string | null {
  try {
    return localStorage.getItem(ROLE_KEY);
  } catch {
    return null;
  }
}

function persistRole(role: string | null): void {
  try {
    if (role) localStorage.setItem(ROLE_KEY, role);
    else localStorage.removeItem(ROLE_KEY);
  } catch {
    // storage unavailable — degrade silently
  }
}

export interface LogLine {
  ts: string;
  level: string;
  message: string;
  source: "agent_log" | "notification" | "system";
  // True for lines narrated by the GB10 Nemotron agent (tinted in the feed).
  nemotron?: boolean;
}

interface OpsState {
  connected: boolean;
  jobs: Record<string, DeliveryJob>;
  couriers: Record<string, Courier>;
  plan: Plan | null;
  disruptions: DisruptionEvent[];
  drivers: Record<string, Driver>;
  congestion: CongestionField;
  signalRecs: SignalRec[];
  logs: LogLine[];
  lastNotification: Notification | null;
  history: MetricSample[];
  selectedCourierId: string | null;
  focusJobId: string | null;
  // The just-created delivery's own road geometry (from /intake), drawn as a
  // dedicated clean blue route on the map. null = no focus route.
  focusRoute: { lat: number; lng: number }[] | null;
  // The optimized stops for the focus route (origin + destinations, in visit
  // order), drawn as numbered waypoint markers on top of the blue route so a
  // multi-hop delivery is legible. null = no focus stops.
  focusStops: { name: string; lat: number; lng: number }[] | null;
  fleetAssessments: Record<string, FleetAssessment>;
  cctv: CctvCamera[];
  lastAgentAnswer: AgentAnswer | null;

  // --- auth ---
  token: string | null;
  role: string | null;
  authUser: AuthUser | null;
  setAuth: (token: string, role: string | null) => void;
  setAuthUser: (user: AuthUser | null) => void;
  clearAuth: () => void;

  setConnected: (v: boolean) => void;
  hydrate: (snap: StateSnapshot) => void;
  applyEvent: (e: WsEvent) => void;
  pushLog: (line: Omit<LogLine, "ts"> & { ts?: string }) => void;
  selectCourier: (id: string | null) => void;
  setFocusJob: (id: string | null) => void;
  setFocusRoute: (pts: { lat: number; lng: number }[] | null) => void;
  setFocusStops: (
    stops: { name: string; lat: number; lng: number }[] | null,
  ) => void;
  setFleetAssessments: (list: FleetAssessment[]) => void;
  setCctv: (list: CctvCamera[]) => void;
}

const MAX_LOGS = 200;
const MAX_HISTORY = 60;

function byId<T extends { id: string }>(arr: T[]): Record<string, T> {
  const out: Record<string, T> = {};
  for (const item of arr) out[item.id] = item;
  return out;
}

export const useStore = create<OpsState>((set, get) => ({
  connected: false,
  jobs: {},
  couriers: {},
  plan: null,
  disruptions: [],
  drivers: {},
  congestion: { cells: [] },
  signalRecs: [],
  logs: [],
  lastNotification: null,
  history: [],
  selectedCourierId: null,
  focusJobId: null,
  focusRoute: null,
  focusStops: null,
  fleetAssessments: {},
  cctv: [],
  lastAgentAnswer: null,

  // Hydrate auth from localStorage so a logged-in session survives reloads.
  token: getToken(),
  role: readRole(),
  authUser: null,

  setAuth: (token, role) => {
    setToken(token);
    persistRole(role);
    set({ token, role });
  },

  setAuthUser: (user) => set({ authUser: user }),

  clearAuth: () => {
    setToken(null);
    persistRole(null);
    set({ token: null, role: null, authUser: null });
  },

  setConnected: (v) => set({ connected: v }),

  // Selecting (clicking) a courier returns to the normal fleet view: clear any
  // delivery focus route + stops + focused job so only the courier highlight applies.
  selectCourier: (id) =>
    set({ selectedCourierId: id, focusRoute: null, focusStops: null, focusJobId: null }),

  setFocusJob: (id) => set({ focusJobId: id }),

  setFocusRoute: (pts) => set({ focusRoute: pts }),

  setFocusStops: (stops) => set({ focusStops: stops }),

  setFleetAssessments: (list) =>
    set({ fleetAssessments: keyByCourier(Array.isArray(list) ? list : []) }),

  setCctv: (list) => set({ cctv: Array.isArray(list) ? list : [] }),

  hydrate: (snap) => {
    set({
      jobs: byId(snap.jobs ?? []),
      couriers: byId(snap.couriers ?? []),
      plan: snap.plan ?? null,
      disruptions: snap.disruptions ?? [],
      drivers: byId(snap.drivers ?? []),
      congestion: snap.congestion ?? { cells: [] },
      signalRecs: snap.signal_recs ?? [],
    });
    recordSample(get, set);
  },

  pushLog: (line) =>
    set((s) => ({
      logs: [
        ...s.logs,
        { ts: line.ts ?? new Date().toISOString(), ...line },
      ].slice(-MAX_LOGS),
    })),

  applyEvent: (e) => {
    switch (e.type) {
      case "state": {
        get().hydrate(e.payload);
        get().pushLog({
          level: "info",
          message: "State synced from orchestrator.",
          source: "system",
        });
        break;
      }
      case "job_created": {
        const job = e.payload as DeliveryJob;
        set((s) => ({ jobs: { ...s.jobs, [job.id]: job } }));
        recordSample(get, set);
        break;
      }
      case "plan_updated": {
        set({ plan: e.payload as Plan });
        recordSample(get, set);
        break;
      }
      case "disruption": {
        const d = e.payload as DisruptionEvent;
        set((s) => ({ disruptions: [...s.disruptions, d] }));
        break;
      }
      case "agent_log": {
        const log = e.payload as AgentLog;
        get().pushLog({
          ts: e.ts,
          level: log.level ?? "info",
          message: log.message,
          source: "agent_log",
          nemotron: log.source === "nemotron",
        });
        break;
      }
      case "notification": {
        const n = e.payload as Notification;
        set({ lastNotification: n });
        get().pushLog({
          ts: e.ts,
          level: "info",
          message: `[${n.channel}] ${n.message}`,
          source: "notification",
        });
        break;
      }
      case "congestion_updated": {
        const field = e.payload as CongestionField;
        set({ congestion: field ?? { cells: [] } });
        break;
      }
      case "signal_recs": {
        const recs = e.payload as SignalRec[];
        set({ signalRecs: Array.isArray(recs) ? recs : [] });
        break;
      }
      case "driver_joined": {
        const d = e.payload as Driver;
        set((s) => ({ drivers: { ...s.drivers, [d.id]: d } }));
        get().pushLog({
          ts: e.ts,
          level: "info",
          message: `Driver ${d.name ?? d.id} (${d.vehicle_type}) joined the flywheel.`,
          source: "system",
        });
        break;
      }
      case "fleet_assessments": {
        const list = e.payload as FleetAssessment[];
        set({ fleetAssessments: keyByCourier(Array.isArray(list) ? list : []) });
        break;
      }
      case "agent_answer": {
        const ans = e.payload as AgentAnswer;
        set({ lastAgentAnswer: ans });
        get().pushLog({
          ts: e.ts,
          level: "info",
          message: `NemoClaw: ${ans.answer}`,
          source: "agent_log",
          nemotron: true,
        });
        break;
      }
    }
  },
}));

function keyByCourier(list: FleetAssessment[]): Record<string, FleetAssessment> {
  const out: Record<string, FleetAssessment> = {};
  for (const a of list) out[a.courier_id] = a;
  return out;
}

function recordSample(
  get: () => OpsState,
  set: (partial: Partial<OpsState>) => void,
) {
  const s = get();
  const sample = sampleMetrics(
    s.plan,
    Object.values(s.jobs),
    Object.values(s.couriers),
  );
  set({ history: [...s.history, sample].slice(-MAX_HISTORY) });
}
