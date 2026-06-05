// Optional reference datasets served from public/data/*.json (NHS facilities,
// signalised junctions, public-event venues, Tower Bridge). Everything here
// degrades gracefully: a missing / malformed file yields [] or null so the map
// simply skips that layer.

import type { DisruptionEvent } from "../types";

export interface Facility {
  id: string;
  name: string;
  type: string; // hospital | lab | gp | clinic | pharmacy | ...
  lat: number;
  lng: number;
}

export interface Junction {
  id: string;
  name: string;
  lat: number;
  lng: number;
  cycle_s: number;
  green_s: number;
  offset_s: number;
}

export interface EventVenue {
  id: string;
  name: string;
  lat: number;
  lng: number;
}

export interface BridgePoint {
  lat: number;
  lng: number;
}

/** Fetch + JSON-parse from public/, returning null on 404 / non-JSON / parse error. */
export async function fetchOptional<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return null;
    const ct = res.headers.get("content-type") ?? "";
    // The Vite dev server returns index.html (not JSON) for missing files.
    if (!ct.includes("json") && !ct.includes("octet-stream")) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

function isFiniteNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

export function parseFacilities(raw: unknown): Facility[] {
  if (!Array.isArray(raw)) return [];
  const out: Facility[] = [];
  for (const r of raw as Record<string, unknown>[]) {
    if (!r || !isFiniteNum(r.lat) || !isFiniteNum(r.lng)) continue;
    out.push({
      id: String(r.id ?? `${r.lat},${r.lng}`),
      name: String(r.name ?? r.id ?? "Facility"),
      type: String(r.type ?? "facility").toLowerCase(),
      lat: r.lat,
      lng: r.lng,
    });
  }
  return out;
}

export function parseJunctions(raw: unknown): Junction[] {
  if (!Array.isArray(raw)) return [];
  const out: Junction[] = [];
  for (const r of raw as Record<string, unknown>[]) {
    if (!r || !isFiniteNum(r.lat) || !isFiniteNum(r.lng)) continue;
    out.push({
      id: String(r.id ?? `${r.lat},${r.lng}`),
      name: String(r.name ?? r.id ?? "Junction"),
      lat: r.lat,
      lng: r.lng,
      cycle_s: isFiniteNum(r.cycle_s) ? r.cycle_s : 90,
      green_s: isFiniteNum(r.green_s) ? r.green_s : 30,
      offset_s: isFiniteNum(r.offset_s) ? r.offset_s : 0,
    });
  }
  return out;
}

export function parseEventVenues(raw: unknown): EventVenue[] {
  const obj = raw as { venues?: unknown } | null;
  const venues = obj?.venues;
  if (!Array.isArray(venues)) return [];
  const out: EventVenue[] = [];
  for (const r of venues as Record<string, unknown>[]) {
    if (!r || !isFiniteNum(r.lat) || !isFiniteNum(r.lng)) continue;
    out.push({
      id: String(r.id ?? r.name ?? ""),
      name: String(r.name ?? r.id ?? "Venue"),
      lat: r.lat,
      lng: r.lng,
    });
  }
  return out;
}

export function parseBridgeCentre(raw: unknown): BridgePoint | null {
  const obj = raw as { centre?: { lat?: unknown; lng?: unknown } } | null;
  const c = obj?.centre;
  if (c && isFiniteNum(c.lat) && isFiniteNum(c.lng)) return { lat: c.lat, lng: c.lng };
  return null;
}

// ---- green-wave signal phase ------------------------------------------------

export interface SignalPhase {
  green: boolean;
  secsToGreen: number; // 0 when currently green
  secsLeft: number; // seconds remaining in the current state
}

/** Where a junction sits in its fixed-time cycle right now (offset-aligned). */
export function signalPhase(j: Junction, nowMs: number): SignalPhase {
  const cycle = Math.max(1, j.cycle_s);
  const green = Math.max(0, Math.min(cycle, j.green_s));
  const t = (((nowMs / 1000 - j.offset_s) % cycle) + cycle) % cycle;
  if (t < green) {
    return { green: true, secsToGreen: 0, secsLeft: Math.ceil(green - t) };
  }
  return { green: false, secsToGreen: Math.ceil(cycle - t), secsLeft: Math.ceil(cycle - t) };
}

// ---- disruption classification (bridge vs event vs congestion vs manual) ----

export type DisruptionClass = "bridge" | "event" | "congestion" | "courier" | "manual";

export interface ClassifiedDisruption {
  id: string;
  cls: DisruptionClass;
  label: string;
  lat: number;
  lng: number;
}

const CLASS_LABEL: Record<DisruptionClass, string> = {
  bridge: "Tower Bridge lift",
  event: "Event zone",
  congestion: "Congestion zone",
  courier: "Courier down",
  manual: "Road closure",
};

/**
 * Classify an orchestrator DisruptionEvent into a display class + human label.
 * Uses the id-prefix convention the data pipeline emits:
 *   twr-…  = Tower Bridge lift · evt-…-<venue>-… = public-event zone ·
 *   cong-… = congestion-derived · courier_down kind = courier · else manual.
 */
export function classifyDisruption(
  d: DisruptionEvent,
  venues: EventVenue[],
): ClassifiedDisruption | null {
  const g = d.geometry?.[0];
  if (!g || !isFiniteNum(g.lat) || !isFiniteNum(g.lng)) return null;
  const id = d.id ?? "";
  let cls: DisruptionClass;
  let label: string;
  if (d.kind === "courier_down") {
    cls = "courier";
    label = d.courier_id ? `Courier down: ${d.courier_id}` : CLASS_LABEL.courier;
  } else if (id.startsWith("twr-")) {
    cls = "bridge";
    label = CLASS_LABEL.bridge;
  } else if (id.startsWith("evt-")) {
    cls = "event";
    const venue = venues.find((v) => v.id && id.includes(`-${v.id}-`));
    label = venue ? `Event: ${venue.name}` : CLASS_LABEL.event;
  } else if (id.startsWith("cong-")) {
    cls = "congestion";
    label = d.kind === "road_closure" ? "Congestion: blocked" : "Congestion zone";
  } else {
    cls = "manual";
    label = d.kind === "road_closure" ? "Road closure (manual)" : `Disruption: ${d.kind}`;
  }
  return { id, cls, label, lat: g.lat, lng: g.lng };
}
