// Turn-by-turn directions for a route. With VITE_MAPBOX_TOKEN set, fetches real
// street-name maneuvers from the Mapbox Directions API; otherwise derives turns
// on-device from the route polyline. Mirrors the native app's lib/directions.ts.

import type { DirectionsResult, LatLng, Maneuver, Route } from "../types";
import { maneuversFromPolyline } from "./geo";

const MAPBOX_TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN ?? "").trim();
const MAX_WAYPOINTS = 25;

export function routeWaypoints(route: Route): LatLng[] {
  return [...route.stops]
    .sort((a, b) => a.sequence - b.sequence)
    .map((s) => ({ lat: s.location.lat, lng: s.location.lng }));
}

async function fetchMapbox(waypoints: LatLng[]): Promise<DirectionsResult | null> {
  if (!MAPBOX_TOKEN || waypoints.length < 2) return null;
  const pts = waypoints.slice(0, MAX_WAYPOINTS);
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

/** Resolve directions for a route — Mapbox if available, else polyline turns. */
export async function getDirections(
  route: Route,
  fallbackPolyline: LatLng[],
): Promise<DirectionsResult> {
  const waypoints = routeWaypoints(route);
  const mb = await fetchMapbox(waypoints);
  if (mb) return mb;
  const geometry =
    fallbackPolyline && fallbackPolyline.length >= 2 ? fallbackPolyline : waypoints;
  return { geometry, maneuvers: maneuversFromPolyline(geometry), source: "polyline" };
}
