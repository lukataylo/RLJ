// Client-side road routing via the Mapbox Directions API so courier routes
// follow the street network (Waze / Google-Maps style) instead of straight spokes
// — AND carry LIVE per-segment traffic congestion so we can colour the route
// green→yellow→orange→red exactly like Waze.
//
//   GET https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{lng,lat;...}
//        ?geometries=geojson&overview=full&annotations=congestion_numeric&access_token=TOKEN
//
// - `driving-traffic` + `annotations=congestion_numeric` returns a 0–100 congestion
//   value per geometry segment (N coords → N-1 values; null where unknown → -1).
// - Max 25 coords/request: longer routes are chunked and stitched (coords + congestion).
// - Cached by a route signature so we only refetch when a route actually changes.
// - On no-token / failure / empty geometry we return null, and the caller FALLS BACK
//   to the straight stop polyline so a route always renders.

export type LngLat = [number, number];

/** A road-following geometry plus live per-segment congestion (0–100, -1 = unknown). */
export interface RoadGeom {
  coords: LngLat[];
  /** length == coords.length - 1 */
  congestion: number[];
}

const TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN ?? "").trim();
const MAX_COORDS = 25;

export function hasMapboxToken(): boolean {
  return TOKEN.length > 0;
}

/** Stable signature for a courier's ordered stop coords (5-dp ≈ 1 m). */
export function routeSignature(courierId: string, coords: LngLat[]): string {
  return (
    courierId +
    "|" +
    coords.map(([lng, lat]) => `${lng.toFixed(5)},${lat.toFixed(5)}`).join(";")
  );
}

// Resolved road geometries, keyed by signature. `null` = fetched-but-failed.
const cache = new Map<string, RoadGeom | null>();
const inflight = new Map<string, Promise<RoadGeom | null>>();

export function cachedRoute(sig: string): RoadGeom | null | undefined {
  return cache.get(sig);
}

/** Drop cached geometries so the next resolve re-fetches LIVE traffic (Waze-style
 * realtime). In-flight requests are left to settle. */
export function clearRouteCache(): void {
  cache.clear();
}

async function fetchChunk(coords: LngLat[]): Promise<RoadGeom | null> {
  const path = coords.map(([lng, lat]) => `${lng},${lat}`).join(";");
  const url =
    `https://api.mapbox.com/directions/v5/mapbox/driving-traffic/${path}` +
    `?geometries=geojson&overview=full&annotations=congestion_numeric&access_token=${TOKEN}`;
  const res = await fetch(url);
  if (!res.ok) return null;
  const data = (await res.json()) as {
    routes?: {
      geometry?: { coordinates?: LngLat[] };
      legs?: { annotation?: { congestion_numeric?: (number | null)[] } }[];
    }[];
  };
  const route = data?.routes?.[0];
  const geom = route?.geometry?.coordinates;
  if (!Array.isArray(geom) || geom.length < 2) return null;
  // Congestion spans all legs concatenated; -1 where Mapbox reports null/unknown.
  const cong: number[] = [];
  for (const leg of route?.legs ?? []) {
    for (const c of leg.annotation?.congestion_numeric ?? []) {
      cong.push(typeof c === "number" ? c : -1);
    }
  }
  const want = geom.length - 1;
  while (cong.length < want) cong.push(-1);
  return { coords: geom as LngLat[], congestion: cong.slice(0, want) };
}

/** Fetch a road-following geometry + congestion (chunked + stitched). */
async function fetchRoadGeometry(coords: LngLat[]): Promise<RoadGeom | null> {
  if (!hasMapboxToken() || coords.length < 2) return null;
  try {
    if (coords.length <= MAX_COORDS) return await fetchChunk(coords);
    const stitchedCoords: LngLat[] = [];
    const stitchedCong: number[] = [];
    for (let i = 0; i < coords.length - 1; i += MAX_COORDS - 1) {
      const sub = coords.slice(i, i + MAX_COORDS);
      if (sub.length < 2) break;
      const part = await fetchChunk(sub);
      if (!part) return null;
      if (stitchedCoords.length) stitchedCoords.push(...part.coords.slice(1));
      else stitchedCoords.push(...part.coords);
      stitchedCong.push(...part.congestion);
    }
    return stitchedCoords.length >= 2
      ? { coords: stitchedCoords, congestion: stitchedCong }
      : null;
  } catch {
    return null;
  }
}

/**
 * Return a road geometry for `sig`/`coords`, fetching once and caching the result.
 * Returns the cached geometry synchronously when available; otherwise kicks off a
 * single in-flight request and returns null until it resolves (caller re-renders
 * from the live loop / store, so the new geometry is picked up next frame).
 */
export function getRoadRoute(
  sig: string,
  coords: LngLat[],
  onResolved?: () => void,
): RoadGeom | null {
  if (cache.has(sig)) return cache.get(sig) ?? null;
  if (!inflight.has(sig)) {
    const p = fetchRoadGeometry(coords)
      .then((geom) => {
        cache.set(sig, geom);
        inflight.delete(sig);
        onResolved?.();
        return geom;
      })
      .catch(() => {
        cache.set(sig, null);
        inflight.delete(sig);
        onResolved?.();
        return null;
      });
    inflight.set(sig, p);
  }
  return null;
}
