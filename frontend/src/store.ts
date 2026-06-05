// Small zustand store holding live operational state, updated from WS events.

import { create } from "zustand";
import type {
  AgentLog,
  Courier,
  DeliveryJob,
  DisruptionEvent,
  Notification,
  Plan,
  StateSnapshot,
  WsEvent,
} from "./types";

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
  logs: LogLine[];
  lastNotification: Notification | null;

  // derived selectors are computed in components; these are the mutators:
  setConnected: (v: boolean) => void;
  hydrate: (snap: StateSnapshot) => void;
  applyEvent: (e: WsEvent) => void;
  pushLog: (line: Omit<LogLine, "ts"> & { ts?: string }) => void;
}

const MAX_LOGS = 200;

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
  logs: [],
  lastNotification: null,

  setConnected: (v) => set({ connected: v }),

  hydrate: (snap) =>
    set({
      jobs: byId(snap.jobs ?? []),
      couriers: byId(snap.couriers ?? []),
      plan: snap.plan ?? null,
      disruptions: snap.disruptions ?? [],
    }),

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
        break;
      }
      case "plan_updated": {
        set({ plan: e.payload as Plan });
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
    }
  },
}));
