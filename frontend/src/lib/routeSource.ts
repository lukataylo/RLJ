// Route-geometry source for the command-center map: which geometry the ROUTES
// layer draws.
//
//   - "valhalla" — the backend road-following geometry served in each
//                  `route.polyline` (real London streets via our offline Valhalla
//                  /route). Needs NO Mapbox token. The local/DGX default.
//   - "mapbox"   — the client-side Mapbox Directions geometry (lib/routing.ts),
//                  with the built-in straight fallback when no token is present.
//                  The production default (pulsego.org has no DGX/Valhalla).
//
// The DEFAULT is env-driven (build-time VITE_LOCAL): "valhalla" for local DGX
// builds, "mapbox" for production. Once the user toggles via RouteSourceToggle,
// the stored localStorage choice wins.
//
// Persisted to localStorage (mirrors lib/theme.ts) and broadcast via a
// "pulsego-route-source" CustomEvent so the imperative MapView render loop can
// react without prop drilling.

export type RouteSource = "mapbox" | "valhalla";

const KEY = "pulsego_route_source";
const EVENT = "pulsego-route-source";

/** True for DGX/local builds (VITE_LOCAL="true"); Valhalla is available locally. */
export function isLocalBuild(): boolean {
  return import.meta.env.VITE_LOCAL === "true";
}

/** Env-driven default when nothing is stored yet: Valhalla locally, Mapbox in prod. */
function defaultRouteSource(): RouteSource {
  return isLocalBuild() ? "valhalla" : "mapbox";
}

export function getRouteSource(): RouteSource {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "mapbox" || v === "valhalla") return v;
  } catch {
    /* storage unavailable */
  }
  return defaultRouteSource();
}

export function setRouteSource(source: RouteSource): void {
  try {
    localStorage.setItem(KEY, source);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new CustomEvent<RouteSource>(EVENT, { detail: source }));
}

/** Subscribe to route-source changes; returns an unsubscribe fn. */
export function onRouteSourceChange(cb: (source: RouteSource) => void): () => void {
  const handler = (e: Event) => cb((e as CustomEvent<RouteSource>).detail);
  window.addEventListener(EVENT, handler);
  return () => window.removeEventListener(EVENT, handler);
}
