// Route-geometry source switch for the map (Calm Command). Two small segmented
// buttons — "Valhalla" (offline backend road geometry, default) ⇄ "Mapbox"
// (client-side Directions API). Reuses the .theme-toggle pill styling; the active
// source is the Pulse-Red pill.

import { useEffect, useState } from "react";
import {
  getRouteSource,
  setRouteSource,
  type RouteSource,
} from "../lib/routeSource";

export default function RouteSourceToggle() {
  const [source, setSource] = useState<RouteSource>(() => getRouteSource());

  // Keep in sync if the source is changed elsewhere.
  useEffect(() => {
    setSource(getRouteSource());
  }, []);

  const set = (s: RouteSource) => {
    setRouteSource(s);
    setSource(s);
  };

  return (
    <div className="theme-toggle route-source-toggle" role="group" aria-label="Route source">
      <button
        type="button"
        className={source === "valhalla" ? "on" : ""}
        data-testid="route-source-valhalla"
        aria-pressed={source === "valhalla"}
        aria-label="Valhalla offline routes"
        title="Valhalla — offline road geometry (no token)"
        onClick={() => set("valhalla")}
      >
        Valhalla
      </button>
      <button
        type="button"
        className={source === "mapbox" ? "on" : ""}
        data-testid="route-source-mapbox"
        aria-pressed={source === "mapbox"}
        aria-label="Mapbox Directions routes"
        title="Mapbox — client-side Directions API"
        onClick={() => set("mapbox")}
      >
        Mapbox
      </button>
    </div>
  );
}
