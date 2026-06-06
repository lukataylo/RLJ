// REST client for the PulseGo orchestrator. Every call DEGRADES GRACEFULLY:
// network errors / non-2xx resolve to { ok:false, data:null } rather than throw,
// so the UI can show an empty state instead of crashing (pattern lifted from
// driver-app/src/api.ts). Writes attach the JWT Bearer token from auth.ts.

import { getToken } from "./auth";
import { getApiUrl } from "./config";
import type {
  CongestionField,
  Courier,
  DeliveryJob,
  DisruptionEvent,
  Driver,
  DriverGuidance,
  LoginResponse,
  Me,
  Plan,
  SignalAdvice,
  TelemetryAck,
  TelemetryBatch,
} from "./types";

export interface ApiResult<T> {
  ok: boolean;
  status: number; // HTTP status, or 0 for network error
  data: T | null;
}

async function call<T>(
  path: string,
  init?: RequestInit,
  auth = false,
): Promise<ApiResult<T>> {
  try {
    const headers: Record<string, string> = {
      ...(init?.headers as Record<string, string>),
    };
    if (init?.body) headers["content-type"] = "application/json";
    if (auth) {
      const t = getToken();
      if (t) headers["authorization"] = `Bearer ${t}`;
    }
    const res = await fetch(`${getApiUrl()}${path}`, { ...init, headers });
    if (!res.ok) return { ok: false, status: res.status, data: null };
    // some endpoints (logout) may return empty bodies
    const text = await res.text();
    const data = text ? (JSON.parse(text) as T) : (null as T);
    return { ok: true, status: res.status, data };
  } catch {
    return { ok: false, status: 0, data: null };
  }
}

// ---- health & auth --------------------------------------------------------

export async function health(): Promise<boolean> {
  try {
    const res = await fetch(`${getApiUrl()}/healthz`);
    return res.ok;
  } catch {
    return false;
  }
}

export function login(
  email: string,
  password: string,
): Promise<ApiResult<LoginResponse>> {
  return call<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function me(): Promise<ApiResult<Me>> {
  return call<Me>("/auth/me", undefined, true);
}

// ---- read endpoints -------------------------------------------------------

export function getJobs(): Promise<ApiResult<DeliveryJob[]>> {
  return call<DeliveryJob[]>("/jobs");
}

export function getCouriers(): Promise<ApiResult<Courier[]>> {
  return call<Courier[]>("/couriers");
}

export function getPlan(): Promise<ApiResult<Plan | null>> {
  return call<Plan | null>("/plan");
}

// ---- re-routing commands (Bearer) -----------------------------------------

/** Ask the server to redirect a courier — triggers a re-optimize + WS broadcast. */
export function redirectCourier(courierId: string): Promise<ApiResult<unknown>> {
  return call(
    `/couriers/${encodeURIComponent(courierId)}/redirect`,
    { method: "POST", body: JSON.stringify({}) },
    true,
  );
}

/** Report a road closure at a point — server re-optimizes around it. */
export function postDisruption(
  d: DisruptionEvent,
): Promise<ApiResult<DisruptionEvent>> {
  return call<DisruptionEvent>(
    "/disruptions",
    { method: "POST", body: JSON.stringify(d) },
    true,
  );
}

// ---- driver flywheel ------------------------------------------------------

export function postDriver(
  driver: Partial<Driver>,
): Promise<ApiResult<Driver>> {
  return call<Driver>(
    "/drivers",
    { method: "POST", body: JSON.stringify(driver) },
    true,
  );
}

export function postTelemetry(
  batch: TelemetryBatch,
): Promise<ApiResult<TelemetryAck>> {
  return call<TelemetryAck>(
    "/telemetry",
    { method: "POST", body: JSON.stringify(batch) },
    true,
  );
}

/** GET /congestion — current congestion field for the heat layer. */
export function getCongestion(): Promise<ApiResult<CongestionField>> {
  return call<CongestionField>("/congestion");
}

/** GET /driver/{id}/guidance — route + green-wave + contribution. */
export function getGuidance(id: string): Promise<ApiResult<DriverGuidance>> {
  return call<DriverGuidance>(`/driver/${encodeURIComponent(id)}/guidance`);
}

/** GET /signals/advice — green-wave speed-to-next-green hint. */
export function getSignalAdvice(q: {
  driver_id: string;
  lat: number;
  lng: number;
  heading: number;
}): Promise<ApiResult<SignalAdvice>> {
  const p = new URLSearchParams({
    driver_id: q.driver_id,
    lat: String(q.lat),
    lng: String(q.lng),
    heading: String(q.heading),
  });
  return call<SignalAdvice>(`/signals/advice?${p.toString()}`);
}
