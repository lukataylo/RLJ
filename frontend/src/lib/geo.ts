// Geometry helpers shared by the map layers.

import type { LatLng } from "../types";

/** Interpolate a position a fraction `f` (0..1) along a lat/lng polyline. */
export function pointAlong(poly: LatLng[], f: number): [number, number] | null {
  if (!poly || poly.length === 0) return null;
  if (poly.length === 1) return [poly[0].lng, poly[0].lat];
  const segLens: number[] = [];
  let total = 0;
  for (let i = 0; i < poly.length - 1; i++) {
    const dx = poly[i + 1].lng - poly[i].lng;
    const dy = poly[i + 1].lat - poly[i].lat;
    const len = Math.hypot(dx, dy);
    segLens.push(len);
    total += len;
  }
  if (total === 0) return [poly[0].lng, poly[0].lat];
  let target = f * total;
  for (let i = 0; i < segLens.length; i++) {
    if (target <= segLens[i] || i === segLens.length - 1) {
      const t = segLens[i] === 0 ? 0 : target / segLens[i];
      return [
        poly[i].lng + (poly[i + 1].lng - poly[i].lng) * t,
        poly[i].lat + (poly[i + 1].lat - poly[i].lat) * t,
      ];
    }
    target -= segLens[i];
  }
  const last = poly[poly.length - 1];
  return [last.lng, last.lat];
}

/** Interpolate along a path of [lng,lat] tuples (deck.gl ordering). */
export function pointAlongPath(
  path: [number, number][],
  f: number,
): [number, number] | null {
  if (!path || path.length === 0) return null;
  return pointAlong(
    path.map(([lng, lat]) => ({ lat, lng })),
    f,
  );
}
