// Geometry helpers for navigation: distances, bearings, point-to-route distance,
// on-device maneuver derivation from a polyline, and a London-loop GPS simulator
// (ported from driver-app/src/api.ts) so the app demos without a real GPS fix.

import type { LatLng, Maneuver } from "./types";

const R = 6371000; // earth radius, metres
const toRad = (d: number) => (d * Math.PI) / 180;
const toDeg = (r: number) => (r * 180) / Math.PI;

/** Great-circle distance between two points, metres. */
export function haversine(a: LatLng, b: LatLng): number {
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Initial bearing from a→b in degrees [0,360). */
export function bearing(a: LatLng, b: LatLng): number {
  const dLng = toRad(b.lng - a.lng);
  const y = Math.sin(dLng) * Math.cos(toRad(b.lat));
  const x =
    Math.cos(toRad(a.lat)) * Math.sin(toRad(b.lat)) -
    Math.sin(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.cos(dLng);
  return (toDeg(Math.atan2(y, x)) + 360) % 360;
}

/** Perpendicular distance (metres) from point p to segment a→b. */
export function distToSegment(p: LatLng, a: LatLng, b: LatLng): number {
  // local equirectangular projection (fine over street-scale distances)
  const x = (pt: LatLng) => toRad(pt.lng) * Math.cos(toRad(p.lat)) * R;
  const y = (pt: LatLng) => toRad(pt.lat) * R;
  const px = x(p),
    py = y(p);
  const ax = x(a),
    ay = y(a);
  const bx = x(b),
    by = y(b);
  const dx = bx - ax,
    dy = by - ay;
  const len2 = dx * dx + dy * dy;
  let t = len2 === 0 ? 0 : ((px - ax) * dx + (py - ay) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  const cx = ax + t * dx,
    cy = ay + t * dy;
  return Math.hypot(px - cx, py - cy);
}

/** Minimum distance (metres) from a point to a polyline. */
export function distToPath(p: LatLng, path: LatLng[]): number {
  if (path.length === 0) return Infinity;
  if (path.length === 1) return haversine(p, path[0]);
  let min = Infinity;
  for (let i = 0; i < path.length - 1; i++) {
    min = Math.min(min, distToSegment(p, path[i], path[i + 1]));
  }
  return min;
}

/** Human distance phrase for spoken/displayed directions. */
export function distancePhrase(m: number): string {
  if (m < 30) return "now";
  if (m < 1000) return `in ${Math.round(m / 10) * 10} metres`;
  return `in ${(m / 1000).toFixed(1)} kilometres`;
}

function turnFromAngle(delta: number): { type: string; modifier: string; word: string } {
  // delta in (-180,180]; positive = right
  const a = ((delta + 540) % 360) - 180;
  const abs = Math.abs(a);
  const side = a >= 0 ? "right" : "left";
  if (abs < 18) return { type: "continue", modifier: "straight", word: "continue straight" };
  if (abs < 50)
    return { type: "turn", modifier: `slight ${side}`, word: `bear ${side}` };
  if (abs < 125) return { type: "turn", modifier: side, word: `turn ${side}` };
  return { type: "turn", modifier: `sharp ${side}`, word: `make a sharp ${side}` };
}

/**
 * Derive turn-by-turn maneuvers from a route polyline by detecting bearing
 * changes at vertices. Used when no Mapbox token is configured. No street names
 * (the polyline carries none), but gives correct turn/distance guidance.
 */
export function maneuversFromPolyline(path: LatLng[]): Maneuver[] {
  if (path.length < 2) return [];
  const out: Maneuver[] = [];
  out.push({
    instruction: "Head out along the route",
    type: "depart",
    modifier: "straight",
    location: path[0],
    distanceM: 0,
  });
  let segStart = 0;
  for (let i = 1; i < path.length - 1; i++) {
    const inB = bearing(path[i - 1], path[i]);
    const outB = bearing(path[i], path[i + 1]);
    const delta = outB - inB;
    const t = turnFromAngle(delta);
    if (t.type === "continue") continue; // only emit real turns
    const dist = segmentLength(path, segStart, i);
    out.push({
      instruction: `${cap(distancePhrase(dist))}, ${t.word}`,
      type: t.type,
      modifier: t.modifier,
      location: path[i],
      distanceM: dist,
    });
    segStart = i;
  }
  const last = path[path.length - 1];
  out.push({
    instruction: `${cap(distancePhrase(segmentLength(path, segStart, path.length - 1)))}, you arrive at your destination`,
    type: "arrive",
    modifier: "straight",
    location: last,
    distanceM: segmentLength(path, segStart, path.length - 1),
  });
  return out;
}

function segmentLength(path: LatLng[], from: number, to: number): number {
  let d = 0;
  for (let i = from; i < to; i++) d += haversine(path[i], path[i + 1]);
  return d;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

// ----------------------------------------------------------- GPS simulator

// Central-London loop (Southbank ↔ Westminster ↔ Trafalgar ↔ Strand), within
// the London bbox the contract validates (lat 51.28–51.69, lng −0.51–0.33).
export const LONDON_LOOP: LatLng[] = [
  { lat: 51.5033, lng: -0.1195 },
  { lat: 51.5007, lng: -0.1246 },
  { lat: 51.4995, lng: -0.1248 },
  { lat: 51.4975, lng: -0.1357 },
  { lat: 51.5012, lng: -0.1419 },
  { lat: 51.5074, lng: -0.1278 },
  { lat: 51.5108, lng: -0.122 },
  { lat: 51.5081, lng: -0.117 },
  { lat: 51.5052, lng: -0.1153 },
];

/** Stateful simulator: each call advances ~stepMeters along LONDON_LOOP. */
export function simulateGps(stepMeters = 35): () => {
  lat: number;
  lng: number;
  speed_mps: number;
  heading_deg: number;
} {
  const loop = LONDON_LOOP;
  let seg = 0;
  let frac = 0;
  return () => {
    const a = loop[seg];
    const b = loop[(seg + 1) % loop.length];
    const lat = a.lat + (b.lat - a.lat) * frac;
    const lng = a.lng + (b.lng - a.lng) * frac;
    const heading = bearing(a, b);
    const speed_mps = 5 + Math.random() * 4;
    const len = haversine(a, b) || 1;
    frac += stepMeters / len;
    while (frac >= 1) {
      frac -= 1;
      seg = (seg + 1) % loop.length;
    }
    return { lat, lng, speed_mps, heading_deg: heading };
  };
}
