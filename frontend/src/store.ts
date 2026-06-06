// Small zustand store holding live operational state, updated from WS events.
// Single source of truth for the UI; also retains a short metric history for sparklines.

import { create } from "zustand";
import type {
  AgentLog,
  CongestionField,
  Courier,
  DeliveryJob,
  DisruptionEvent,
  Driver,
  MetricSample,
  Notification,
  Plan,
  SignalRec,
  StateSnapshot,
  WsEvent,
} from "./types";
import { sampleMetrics } from "./lib/format";

export interface LogLine {
  ts: string;
  level: string;
  message: string;
  source: "agent_log" | "notification" | "system";
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

  setConnected: (v: boolean) => void;
  hydrate: (snap: StateSnapshot) => void;
  applyEvent: (e: WsEvent) => void;
  pushLog: (line: Omit<LogLine, "ts"> & { ts?: string }) => void;
  selectCourier: (id: string | null) => void;
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

  setConnected: (v) => set({ connected: v }),

  selectCourier: (id) => set({ selectedCourierId: id }),

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
      case "courier_moved": {
        const { courier_id, location } = e.payload;
        set((s) => {
          const c = s.couriers[courier_id];
          if (!c) return {};
          return {
            couriers: {
              ...s.couriers,
              [courier_id]: { ...c, location: { ...c.location, ...location } },
            },
          };
        });
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
    }
  },
}));

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
