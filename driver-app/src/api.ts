// REST helpers for the driver flywheel + green-wave endpoints
// (contracts/driver-api.md). Base URL from VITE_ORCHESTRATOR_URL, default
// http://localhost:8000.
//
// Every call is written to DEGRADE GRACEFULLY: network errors and 404s resolve
// to `null` (not throw), so the UI can fall back to demo data / hide a card.

import type {
  CongestionField,
  Driver,
  DriverGuidance,
  GpsFix,
  LatLng,
  SignalAdvice,
  TelemetryAck,
  TelemetryBatch,
} from "./types";

export const BASE = (
  import.meta.env.VITE_ORCHESTRATOR_URL || "http://localhost:8000"
).replace(/\/$/, "");

/** Result of an optional fetch: ok+data, or a reason it failed. */
export interface ApiResult<T> {
  ok: boolean;
  status: number; // HTTP status, or 0 for network error
  data: T | null;
}

async function call<T>(
  path: string,
  init?: RequestInit,
): Promise<ApiResult<T>> {
  try {
    const res = await fetch(`${BASE}${path}`, init);
    if (!res.ok) return { ok: false, status: res.status, data: null };
    const data = (await res.json()) as T;
    return { ok: true, status: res.status, data };
  } catch {
    // network error / orchestrator down / CORS
    return { ok: false, status: 0, data: null };
  }
}

// ----------------------------------------------------------------- endpoints

/**
 * Is the orchestrator reachable at all? Used to choose between "demo mode"
 * (orchestrator down → fabricate data) and "endpoint missing" (orchestrator up
 * but a specific driver endpoint 404s → hide that card). Probes /healthz, which
 * the core orchestrator exposes.
 */
export async function health(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/healthz`);
    return res.ok;
  } catch {
    return false;
  }
}

/** POST /drivers — server fills id/joined_at when omitted. */
export function postDriver(driver: Partial<Driver>): Promise<ApiResult<Driver>> {
  return call<Driver>("/drivers", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(driver),
  });
}

/** GET /drivers — roster (used to confirm the orchestrator is reachable). */
export function getDrivers(): Promise<ApiResult<Driver[]>> {
  return call<Driver[]>("/drivers");
}

/** POST /telemetry — push a batch of GPS probes. */
export function postTelemetry(
  batch: TelemetryBatch,
): Promise<ApiResult<TelemetryAck>> {
  return call<TelemetryAck>("/telemetry", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(batch),
  });
}

/** GET /congestion — current congestion field for the heat layer. */
export function getCongestion(): Promise<ApiResult<CongestionField>> {
  return call<CongestionField>("/congestion");
}

/** GET /driver/{id}/guidance — route + green-wave + contribution. */
export function getGuidance(id: string): Promise<ApiResult<DriverGuidance>> {
  return call<DriverGuidance>(`/driver/${encodeURIComponent(id)}/guidance`);
}

/** GET /signals/advice?driver_id&lat&lng&heading — green-wave advice. */
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

// --------------------------------------------------------------- GPS sources

/**
 * Try one real geolocation fix. Resolves to null if the API is unavailable,
 * permission is denied, or it times out — caller then falls back to simulate.
 */
export function getGeoFix(timeoutMs = 8000): Promise<GpsFix | null> {
  return new Promise((resolve) => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) =>
        resolve({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          speed_mps: pos.coords.speed ?? 0,
          heading_deg: pos.coords.heading ?? 0,
        }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 2000 },
    );
  });
}

// A plausible central-London loop (Southbank ↔ Westminster ↔ Trafalgar ↔ Strand)
// so the demo "moves" on a laptop with no GPS. Within the London bbox the
// contract validates against (lat 51.28–51.69, lng −0.51–0.33).
export const LONDON_LOOP: LatLng[] = [
  { lat: 51.5033, lng: -0.1195 }, // London Eye
  { lat: 51.5007, lng: -0.1246 }, // Westminster Bridge
  { lat: 51.4995, lng: -0.1248 }, // Houses of Parliament
  { lat: 51.4975, lng: -0.1357 }, // toward Victoria
  { lat: 51.5012, lng: -0.1419 }, // Buckingham Gate
  { lat: 51.5074, lng: -0.1278 }, // Trafalgar Square
  { lat: 51.5108, lng: -0.122 }, // Covent Garden
  { lat: 51.5081, lng: -0.117 }, // Aldwych
  { lat: 51.5052, lng: -0.1153 }, // Waterloo Bridge (north)
];

function headingDeg(a: LatLng, b: LatLng): number {
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const y = Math.sin(dLng) * Math.cos((b.lat * Math.PI) / 180);
  const x =
    Math.cos((a.lat * Math.PI) / 180) * Math.sin((b.lat * Math.PI) / 180) -
    Math.sin((a.lat * Math.PI) / 180) *
      Math.cos((b.lat * Math.PI) / 180) *
      Math.cos(dLng);
  return (((Math.atan2(y, x) * 180) / Math.PI) + 360) % 360;
}

/**
 * Build a stateful GPS simulator that walks along LONDON_LOOP. Each call returns
 * the next fix (position advances ~`stepMeters` per call, default tuned for a
 * 5s ping interval at urban cycling speed). Used when real geolocation is
 * unavailable so the laptop demo still contributes pings + sees the map move.
 */
export function simulateGps(stepMeters = 35): () => GpsFix {
  const loop = LONDON_LOOP;
  let seg = 0;
  let frac = 0;

  const segMeters = (i: number): number => {
    const a = loop[i];
    const b = loop[(i + 1) % loop.length];
    const dLat = (b.lat - a.lat) * 111_320;
    const dLng = (b.lng - a.lng) * 111_320 * Math.cos((a.lat * Math.PI) / 180);
    return Math.hypot(dLat, dLng);
  };

  return () => {
    const a = loop[seg];
    const b = loop[(seg + 1) % loop.length];
    const lat = a.lat + (b.lat - a.lat) * frac;
    const lng = a.lng + (b.lng - a.lng) * frac;
    const heading = headingDeg(a, b);
    // a touch of speed variance so the gauge looks alive (~18–32 km/h)
    const speed_mps = 5 + Math.random() * 4;

    // advance for next call
    const len = segMeters(seg) || 1;
    frac += stepMeters / len;
    while (frac >= 1) {
      frac -= 1;
      seg = (seg + 1) % loop.length;
    }
    return { lat, lng, speed_mps, heading_deg: heading };
  };
}
