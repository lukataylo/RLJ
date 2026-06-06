// REST + WebSocket helpers for the orchestrator (contracts/api.md).
// Base URL comes from VITE_ORCHESTRATOR_URL, default http://localhost:8000.

import type {
  CongestionField,
  DeliveryJob,
  DisruptionEvent,
  Driver,
  Plan,
  StateSnapshot,
  WsEvent,
} from "./types";

const BASE = (
  import.meta.env.VITE_ORCHESTRATOR_URL || "http://localhost:8000"
).replace(/\/$/, "");

// http://host -> ws://host , https://host -> wss://host
export const WS_URL = BASE.replace(/^http/, "ws") + "/ws";
export const REST_URL = BASE;

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} — ${body}`);
  }
  return (await res.json()) as T;
}

// ----------------------------------------------------------------- REST helpers

/** GET /state — full snapshot used to hydrate on load / after a WS drop. */
export async function getState(): Promise<StateSnapshot> {
  return json<StateSnapshot>(await fetch(`${BASE}/state`));
}

/** POST /jobs — server fills id/status/created_at when omitted. */
export async function postJob(job: Partial<DeliveryJob>): Promise<DeliveryJob> {
  return json<DeliveryJob>(
    await fetch(`${BASE}/jobs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(job),
    }),
  );
}

/** POST /disruptions — triggers a re-optimize server-side. */
export async function postDisruption(
  d: Partial<DisruptionEvent>,
): Promise<DisruptionEvent> {
  return json<DisruptionEvent>(
    await fetch(`${BASE}/disruptions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(d),
    }),
  );
}

/** POST /optimize — force a re-plan. Returns the new Plan. */
export async function optimize(): Promise<Plan> {
  return json<Plan>(await fetch(`${BASE}/optimize`, { method: "POST" }));
}

/** POST /notifications — dispatch a courier/clinic notification (voice_call etc.).
 * The orchestrator broadcasts it on the WS (voice agent + agent log pick it up). */
export async function postNotification(n: {
  channel: string; to?: string; job_id?: string; message: string;
}): Promise<unknown> {
  return json(
    await fetch(`${BASE}/notifications`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(n),
    }),
  );
}

/** GET /congestion — live crowdsourced congestion field. Empty field on 404/error. */
export async function getCongestion(): Promise<CongestionField> {
  try {
    const res = await fetch(`${BASE}/congestion`);
    if (!res.ok) return { cells: [] };
    return (await res.json()) as CongestionField;
  } catch {
    return { cells: [] };
  }
}

/** GET /drivers — crowdsourced fleet roster. Empty list on 404/error. */
export async function getDrivers(): Promise<Driver[]> {
  try {
    const res = await fetch(`${BASE}/drivers`);
    if (!res.ok) return [];
    return (await res.json()) as Driver[];
  } catch {
    return [];
  }
}

// ----------------------------------------------------------------- WebSocket

export interface WsHandlers {
  onEvent: (e: WsEvent) => void;
  /** Called on every (re)connection — use it to re-hydrate via GET /state. */
  onOpen?: () => void;
  /** Called whenever the socket drops / errors. */
  onClose?: () => void;
}

/**
 * Connect to ws://.../ws with automatic reconnect (exponential-ish backoff).
 * Returns a disposer that permanently closes the connection.
 */
export function connectWs(handlers: WsHandlers): () => void {
  let ws: WebSocket | null = null;
  let closedByUser = false;
  let retry = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  const open = () => {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      retry = 0;
      handlers.onOpen?.();
    };

    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data) as WsEvent;
        handlers.onEvent(data);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = () => {
      handlers.onClose?.();
      if (!closedByUser) scheduleReconnect();
    };

    ws.onerror = () => {
      // onclose will follow and trigger reconnect.
      ws?.close();
    };
  };

  const scheduleReconnect = () => {
    if (closedByUser || reconnectTimer) return;
    const delay = Math.min(1000 * 2 ** retry, 8000); // 1s,2s,4s,8s cap
    retry += 1;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      open();
    }, delay);
  };

  open();

  return () => {
    closedByUser = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    ws?.close();
  };
}
