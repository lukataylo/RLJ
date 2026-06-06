// Turn-by-turn directions for a route's stops. The orchestrator returns route
// polylines + stop ETAs but NO maneuver text, so we generate it here:
//   • with EXPO_PUBLIC_MAPBOX_TOKEN → Mapbox Directions API (real street names)
//   • without a token → on-device maneuvers derived from the polyline geometry
// Mapbox is reached over plain fetch (no native SDK) so it works in Expo Go.

import { MAPBOX_TOKEN } from "./config";
import { maneuversFromPolyline } from "./geo";
import type { DirectionsResult, LatLng, Maneuver, Route } from "./types";

const MAPBOX_MAX_WAYPOINTS = 25;

/** Ordered waypoints for a route: each stop's location, in sequence order. */
export function routeWaypoints(route: Route): LatLng[] {
  return [...route.stops]
    .sort((a, b) => a.sequence - b.sequence)
    .map((s) => ({ lat: s.location.lat, lng: s.location.lng }));
}

async function fetchMapbox(waypoints: LatLng[]): Promise<DirectionsResult | null> {
  if (!MAPBOX_TOKEN || waypoints.length < 2) return null;
  const pts = waypoints.slice(0, MAPBOX_MAX_WAYPOINTS);
  const coords = pts.map((p) => `${p.lng},${p.lat}`).join(";");
  const url =
    `https://api.mapbox.com/directions/v5/mapbox/driving/${coords}` +
    `?steps=true&geometries=geojson&overview=full&access_token=${MAPBOX_TOKEN}`;
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const json: any = await res.json();
    const route = json?.routes?.[0];
    if (!route) return null;
    const geometry: LatLng[] = (route.geometry?.coordinates || []).map(
      ([lng, lat]: [number, number]) => ({ lat, lng }),
    );
    const maneuvers: Maneuver[] = [];
    for (const leg of route.legs || []) {
      for (const step of leg.steps || []) {
        const m = step.maneuver || {};
        const [lng, lat] = m.location || [];
        maneuvers.push({
          instruction: m.instruction || "Continue",
          type: m.type || "continue",
          modifier: m.modifier,
          location: { lat, lng },
          distanceM: step.distance || 0,
        });
      }
    }
    if (geometry.length < 2) return null;
    return { geometry, maneuvers, source: "mapbox" };
  } catch {
    return null;
  }
}

/**
 * Resolve directions for a route. Prefers Mapbox street-name maneuvers; falls
 * back to the server polyline + locally-derived turns. `fallbackPolyline` is the
 * route.polyline from the Plan (used for geometry + fallback maneuvers).
 */
export async function getDirections(
  route: Route,
  fallbackPolyline: LatLng[],
): Promise<DirectionsResult> {
  const waypoints = routeWaypoints(route);
  const mb = await fetchMapbox(waypoints);
  if (mb) return mb;

  // Fallback: use the richest geometry we have. Prefer the server polyline; if
  // it's empty, connect the stops directly so the map + turns still work.
  const geometry =
    fallbackPolyline && fallbackPolyline.length >= 2
      ? fallbackPolyline
      : waypoints;
  return {
    geometry,
    maneuvers: maneuversFromPolyline(geometry),
    source: "polyline",
  };
}
