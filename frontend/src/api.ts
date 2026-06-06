// REST + WebSocket helpers for the orchestrator (contracts/api.md).
// Base URL comes from VITE_ORCHESTRATOR_URL, default http://localhost:8000.

import type {
  CctvCamera,
  CongestionField,
  DeliveryJob,
  DisruptionEvent,
  Driver,
  FleetAssessment,
  Plan,
  SignalRec,
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

// ----------------------------------------------------------------- auth/token
// JWT lives in localStorage so it survives reloads. It is the single source of
// truth read by every write request below; the store mirrors it for the UI.
const TOKEN_KEY = "pulsego_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage unavailable (private mode / SSR) — degrade silently
  }
}

/** Merge an `Authorization: Bearer <token>` header onto write requests when a
 * token is present. Dev runs AUTH_REQUIRED=false so a missing token still works. */
function authHeaders(base: Record<string, string> = {}): Record<string, string> {
  const t = getToken();
  return t ? { ...base, authorization: `Bearer ${t}` } : base;
}

export interface AuthUser {
  id?: string;
  email?: string;
  role?: string;
  [k: string]: unknown;
}

export interface LoginResult {
  access_token: string;
  token_type: string;
  role: string;
}

/** POST /auth/login — exchange credentials for a JWT. Throws on 401. */
export async function login(email: string, password: string): Promise<LoginResult> {
  return json<LoginResult>(
    await fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
  );
}

/** GET /auth/me — validate the current token and return the logged-in user. */
export async function me(): Promise<AuthUser> {
  return json<AuthUser>(await fetch(`${BASE}/auth/me`, { headers: authHeaders() }));
}

/** Clear the persisted token (client-side logout). */
export function logout(): void {
  setToken(null);
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
      headers: authHeaders({ "content-type": "application/json" }),
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
      headers: authHeaders({ "content-type": "application/json" }),
      body: JSON.stringify(d),
    }),
  );
}

/** POST /optimize — force a re-plan. Returns the new Plan. */
export async function optimize(): Promise<Plan> {
  return json<Plan>(
    await fetch(`${BASE}/optimize`, { method: "POST", headers: authHeaders() }),
  );
}

/** POST /demo/seed — populate the orchestrator with the demo scenario (couriers +
 * jobs) and optimise, so a fresh instance shows active routes + deliveries. */
export async function seedDemo(): Promise<{ couriers: number; jobs: number; routes: number }> {
  return json(
    await fetch(`${BASE}/demo/seed`, { method: "POST", headers: authHeaders() }),
  );
}

/** POST /demo/clear — empty the demo scenario so the toggle can turn off. */
export async function clearDemo(): Promise<{ couriers: number; jobs: number; routes: number }> {
  return json(
    await fetch(`${BASE}/demo/clear`, { method: "POST", headers: authHeaders() }),
  );
}

/** POST /notifications — dispatch a courier/clinic notification (voice_call etc.).
 * The orchestrator broadcasts it on the WS (voice agent + agent log pick it up). */
export async function postNotification(n: {
  channel: string; to?: string; job_id?: string; message: string;
}): Promise<unknown> {
  return json(
    await fetch(`${BASE}/notifications`, {
      method: "POST",
      headers: authHeaders({ "content-type": "application/json" }),
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

/** GET /signals/recommendations — GB10 Nemotron traffic-signal recs.
 * Empty list on 404/error so the UI degrades gracefully. */
export async function getSignalRecs(): Promise<SignalRec[]> {
  try {
    const res = await fetch(`${BASE}/signals/recommendations`);
    if (!res.ok) return [];
    return (await res.json()) as SignalRec[];
  } catch {
    return [];
  }
}

/** POST /agent/ask — queue a question for the GB10 Nemotron agent. The answer
 * arrives asynchronously as a WS "agent_log" (source "nemotron") + "agent_answer". */
export async function askAgent(question: string): Promise<unknown> {
  return json(
    await fetch(`${BASE}/agent/ask`, {
      method: "POST",
      headers: authHeaders({ "content-type": "application/json" }),
      body: JSON.stringify({ question }),
    }),
  );
}

/** GET /fleet/assessments — per-courier on-time/reroute/at-risk verdicts.
 * Empty list on 404/error so the cards degrade gracefully. */
export async function getFleetAssessments(): Promise<FleetAssessment[]> {
  try {
    const res = await fetch(`${BASE}/fleet/assessments`);
    if (!res.ok) return [];
    return (await res.json()) as FleetAssessment[];
  } catch {
    return [];
  }
}

/** POST /couriers/{id}/redirect — ask the orchestrator to re-route one courier.
 * Throws on 404 (unknown courier) so the caller can surface the failure. */
export async function redirectCourier(id: string): Promise<{ ok: boolean } & Record<string, unknown>> {
  return json(
    await fetch(`${BASE}/couriers/${encodeURIComponent(id)}/redirect`, {
      method: "POST",
      headers: authHeaders({ "content-type": "application/json" }),
    }),
  );
}

/** GET /cctv/cameras — curated live TfL JamCams. Empty list on 404/error. */
export async function getCctv(): Promise<CctvCamera[]> {
  try {
    const res = await fetch(`${BASE}/cctv/cameras`);
    if (!res.ok) return [];
    return (await res.json()) as CctvCamera[];
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
