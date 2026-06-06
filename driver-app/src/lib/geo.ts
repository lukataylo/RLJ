// Geometry helpers for turn-by-turn: distances, bearings, point-to-route
// distance, and on-device maneuver derivation from a polyline (used when no
// Mapbox token is configured). Shared with the native app's lib/geo.ts.

import type { LatLng, Maneuver } from "../types";

const R = 6371000;
const toRad = (d: number) => (d * Math.PI) / 180;
const toDeg = (r: number) => (r * 180) / Math.PI;

export function haversine(a: LatLng, b: LatLng): number {
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function bearing(a: LatLng, b: LatLng): number {
  const dLng = toRad(b.lng - a.lng);
  const y = Math.sin(dLng) * Math.cos(toRad(b.lat));
  const x =
    Math.cos(toRad(a.lat)) * Math.sin(toRad(b.lat)) -
    Math.sin(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.cos(dLng);
  return (toDeg(Math.atan2(y, x)) + 360) % 360;
}

function distToSegment(p: LatLng, a: LatLng, b: LatLng): number {
  const x = (pt: LatLng) => toRad(pt.lng) * Math.cos(toRad(p.lat)) * R;
  const y = (pt: LatLng) => toRad(pt.lat) * R;
  const px = x(p), py = y(p);
  const ax = x(a), ay = y(a);
  const bx = x(b), by = y(b);
  const dx = bx - ax, dy = by - ay;
  const len2 = dx * dx + dy * dy;
  let t = len2 === 0 ? 0 : ((px - ax) * dx + (py - ay) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

export function distToPath(p: LatLng, path: LatLng[]): number {
  if (path.length === 0) return Infinity;
  if (path.length === 1) return haversine(p, path[0]);
  let min = Infinity;
  for (let i = 0; i < path.length - 1; i++) {
    min = Math.min(min, distToSegment(p, path[i], path[i + 1]));
  }
  return min;
}

export function distancePhrase(m: number): string {
  if (m < 30) return "now";
  if (m < 1000) return `in ${Math.round(m / 10) * 10} metres`;
  return `in ${(m / 1000).toFixed(1)} kilometres`;
}

function segmentLength(path: LatLng[], from: number, to: number): number {
  let d = 0;
  for (let i = from; i < to; i++) d += haversine(path[i], path[i + 1]);
  return d;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function turnFromAngle(delta: number): { type: string; modifier: string; word: string } {
  const a = ((delta + 540) % 360) - 180;
  const abs = Math.abs(a);
  const side = a >= 0 ? "right" : "left";
  if (abs < 18) return { type: "continue", modifier: "straight", word: "continue straight" };
  if (abs < 50) return { type: "turn", modifier: `slight ${side}`, word: `bear ${side}` };
  if (abs < 125) return { type: "turn", modifier: side, word: `turn ${side}` };
  return { type: "turn", modifier: `sharp ${side}`, word: `make a sharp ${side}` };
}

/** Derive turn-by-turn maneuvers from a polyline (no street names). */
export function maneuversFromPolyline(path: LatLng[]): Maneuver[] {
  if (path.length < 2) return [];
  const out: Maneuver[] = [
    { instruction: "Head out along the route", type: "depart", modifier: "straight", location: path[0], distanceM: 0 },
  ];
  let segStart = 0;
  for (let i = 1; i < path.length - 1; i++) {
    const delta = bearing(path[i], path[i + 1]) - bearing(path[i - 1], path[i]);
    const t = turnFromAngle(delta);
    if (t.type === "continue") continue;
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
  const dist = segmentLength(path, segStart, path.length - 1);
  out.push({
    instruction: `${cap(distancePhrase(dist))}, you arrive at your destination`,
    type: "arrive",
    modifier: "straight",
    location: path[path.length - 1],
    distanceM: dist,
  });
  return out;
}
