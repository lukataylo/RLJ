// Client-side road routing via the Mapbox Directions API so courier routes
// follow the street network (Waze / Google-Maps style) instead of straight spokes.
//
//   GET https://api.mapbox.com/directions/v5/mapbox/driving/{lng,lat;...}
//        ?geometries=geojson&overview=full&access_token=TOKEN
//
// - Max 25 coords/request: longer routes are chunked and stitched.
// - Results are cached by a route signature (courier id + rounded stop coords) so
//   we only refetch when a route actually changes.
// - On no-token / fetch failure / empty geometry we return null, and the caller
//   FALLS BACK to the straight stop polyline so a route always renders.

export type LngLat = [number, number];

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
const cache = new Map<string, LngLat[] | null>();
const inflight = new Map<string, Promise<LngLat[] | null>>();

export function cachedRoute(sig: string): LngLat[] | null | undefined {
  return cache.get(sig);
}

async function fetchChunk(coords: LngLat[]): Promise<LngLat[] | null> {
  const path = coords.map(([lng, lat]) => `${lng},${lat}`).join(";");
  const url =
    `https://api.mapbox.com/directions/v5/mapbox/driving/${path}` +
    `?geometries=geojson&overview=full&access_token=${TOKEN}`;
  const res = await fetch(url);
  if (!res.ok) return null;
  const data = (await res.json()) as {
    routes?: { geometry?: { coordinates?: LngLat[] } }[];
  };
  const geom = data?.routes?.[0]?.geometry?.coordinates;
  if (!Array.isArray(geom) || geom.length < 2) return null;
  return geom as LngLat[];
}

/** Fetch a road-following geometry for the ordered coords (chunked + stitched). */
async function fetchRoadGeometry(coords: LngLat[]): Promise<LngLat[] | null> {
  if (!hasMapboxToken() || coords.length < 2) return null;
  try {
    if (coords.length <= MAX_COORDS) return await fetchChunk(coords);
    // Chunk with a 1-coord overlap so consecutive legs join cleanly.
    const stitched: LngLat[] = [];
    for (let i = 0; i < coords.length - 1; i += MAX_COORDS - 1) {
      const sub = coords.slice(i, i + MAX_COORDS);
      if (sub.length < 2) break;
      const part = await fetchChunk(sub);
      if (!part) return null;
      if (stitched.length) stitched.push(...part.slice(1));
      else stitched.push(...part);
    }
    return stitched.length >= 2 ? stitched : null;
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
): LngLat[] | null {
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
