// The live operations map: token-less MapLibre dark basemap + deck.gl overlay.
//
// Layers (overlaid via MapboxOverlay):
//   - TRAFFIC FLOW: roads coloured by congestion (green/amber/red) + animated flow
//     dots, loaded from /data/roads.geojson IF PRESENT (skipped gracefully on 404).
//   - 3D BUILDINGS: extruded polygons from /data/buildings.geojson (toggle + presence).
//   - job origin->destination arcs, colour by priority
//   - plan routes (PathLayer from polyline) coloured by route priority
//   - animated head markers easing along each route polyline
//   - couriers (status colour), pulsing disruption markers

import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import mapboxgl from "mapbox-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import type { Layer, PickingInfo } from "@deck.gl/core";
import { ScatterplotLayer, PathLayer, ArcLayer, PolygonLayer } from "@deck.gl/layers";
import { useStore } from "../store";
import type { Courier, DeliveryJob, LatLng, Plan, Priority } from "../types";
import { COURIER_RGB, DISRUPTION_RGB, PRIORITY_RGB, congestionRGB } from "../lib/palette";
import { pointAlong, pointAlongPath } from "../lib/geo";
import { fetchOptionalJson, parseBuildings, parseRoads, type BuildingPoly, type RoadPath } from "../lib/geojson";

const INITIAL_VIEW = {
  center: [-0.118, 51.503] as [number, number],
  zoom: 11.4,
  pitch: 50,
  bearing: -14,
};

// Premium basemap path: a Mapbox PUBLIC token enables the Mapbox dark style for the
// high-end command-center look. Empty/absent => token-less MapLibre fallback below.
const MAPBOX_TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN ?? "").trim();
const USE_MAPBOX = MAPBOX_TOKEN.length > 0;
// dark-v11 is the safer choice to keep the dark UI readable (vs satellite-streets).
const MAPBOX_STYLE = "mapbox://styles/mapbox/dark-v11";

// Free, token-less dark raster basemap (CARTO dark_matter). Works without an account.
const MAP_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    carto: {
      type: "raster",
      tiles: [
        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors © CARTO",
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#0a0e16" } },
    { id: "carto", type: "raster", source: "carto" },
  ],
};

interface Snapshot {
  jobs: DeliveryJob[];
  couriers: Courier[];
  plan: Plan | null;
  disruptions: { id: string; kind: string; geometry?: LatLng[] }[];
  selectedCourierId: string | null;
}

interface OptionalData {
  roads: RoadPath[];
  buildings: BuildingPoly[];
}

// Highest-priority job served by a route -> route colour.
function routePriority(plan: Plan | null, courierId: string, jobs: DeliveryJob[]): Priority {
  const route = plan?.routes?.find((r) => r.courier_id === courierId);
  if (!route) return "routine";
  const jobById = new Map(jobs.map((j) => [j.id, j]));
  const order: Priority[] = ["stat", "urgent", "routine"];
  let best: Priority = "routine";
  for (const s of route.stops ?? []) {
    const p = jobById.get(s.job_id)?.priority;
    if (p && order.indexOf(p) < order.indexOf(best)) best = p;
  }
  return best;
}

function buildLayers(
  snap: Snapshot,
  data: OptionalData,
  buildingsOn: boolean,
  phase: number,
): Layer[] {
  const { jobs, couriers, plan, disruptions, selectedCourierId } = snap;
  const layers: Layer[] = [];

  // 0a. 3D buildings (drawn first, under everything).
  if (buildingsOn && data.buildings.length) {
    layers.push(
      new PolygonLayer<BuildingPoly>({
        id: "buildings",
        data: data.buildings,
        extruded: true,
        getPolygon: (d) => d.polygon,
        getElevation: (d) => d.height,
        getFillColor: [38, 47, 64, 220],
        getLineColor: [70, 84, 110, 120],
        lineWidthMinPixels: 1,
        material: { ambient: 0.6, diffuse: 0.6, shininess: 32, specularColor: [60, 70, 90] },
      }),
    );
  }

  // 0b. Traffic flow — roads coloured by congestion.
  if (data.roads.length) {
    layers.push(
      new PathLayer<RoadPath>({
        id: "traffic-roads",
        data: data.roads,
        getPath: (d) => d.path,
        getColor: (d) => [...congestionRGB(d.congestion), 150] as [number, number, number, number],
        getWidth: (d) => 2 + d.congestion * 3,
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
      }),
    );
    // Animated flow "dashes" — dots easing along each road segment.
    const flow: { pos: [number, number]; congestion: number }[] = [];
    for (const r of data.roads) {
      const pos = pointAlongPath(r.path, (phase * 1.7) % 1);
      if (pos) flow.push({ pos, congestion: r.congestion });
    }
    layers.push(
      new ScatterplotLayer<{ pos: [number, number]; congestion: number }>({
        id: "traffic-flow",
        data: flow,
        getPosition: (d) => d.pos,
        getRadius: 2,
        radiusUnits: "pixels",
        radiusMinPixels: 1.5,
        radiusMaxPixels: 4,
        getFillColor: (d) => [...congestionRGB(d.congestion), 230] as [number, number, number, number],
        updateTriggers: { getPosition: phase },
      }),
    );
  }

  // 1. Job origin -> destination arcs, colour by priority.
  layers.push(
    new ArcLayer<DeliveryJob>({
      id: "job-arcs",
      data: jobs,
      getSourcePosition: (j) => [j.origin.lng, j.origin.lat],
      getTargetPosition: (j) => [j.destination.lng, j.destination.lat],
      getSourceColor: (j) => [...PRIORITY_RGB[j.priority], 90] as [number, number, number, number],
      getTargetColor: (j) => [...PRIORITY_RGB[j.priority], 220] as [number, number, number, number],
      getWidth: (j) => (j.priority === "stat" ? 3 : j.priority === "urgent" ? 2 : 1.4),
      getHeight: 0.3,
      widthUnits: "pixels",
      pickable: true,
    }),
  );

  // 2. Job endpoints.
  const endpoints = jobs.flatMap((j) => [
    { job: j, loc: j.origin, kind: "origin" as const },
    { job: j, loc: j.destination, kind: "dest" as const },
  ]);
  layers.push(
    new ScatterplotLayer<(typeof endpoints)[number]>({
      id: "job-endpoints",
      data: endpoints,
      getPosition: (d) => [d.loc.lng, d.loc.lat],
      getRadius: (d) => (d.kind === "dest" ? 90 : 70),
      radiusUnits: "meters",
      radiusMinPixels: 4,
      radiusMaxPixels: 15,
      stroked: true,
      lineWidthMinPixels: 1.5,
      getLineColor: [255, 255, 255, 210],
      getFillColor: (d) =>
        [...PRIORITY_RGB[d.job.priority], d.kind === "dest" ? 230 : 110] as [number, number, number, number],
      pickable: true,
    }),
  );

  // 3. Plan routes — PathLayer per route polyline, coloured by route priority.
  const routePaths = (plan?.routes ?? [])
    .filter((r) => r.polyline && r.polyline.length >= 2)
    .map((r) => ({
      courier_id: r.courier_id,
      priority: routePriority(plan, r.courier_id, jobs),
      path: r.polyline!.map((p) => [p.lng, p.lat] as [number, number]),
    }));
  layers.push(
    new PathLayer<(typeof routePaths)[number]>({
      id: "routes",
      data: routePaths,
      getPath: (d) => d.path,
      getColor: (d) =>
        [...PRIORITY_RGB[d.priority], d.courier_id === selectedCourierId ? 255 : 190] as [number, number, number, number],
      getWidth: (d) => (d.courier_id === selectedCourierId ? 7 : 5),
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      pickable: true,
      updateTriggers: { getColor: selectedCourierId, getWidth: selectedCourierId },
    }),
  );

  // 4. Animated head markers easing along each route polyline.
  const heads = (plan?.routes ?? [])
    .filter((r) => r.polyline && r.polyline.length >= 2)
    .map((r) => ({
      courier_id: r.courier_id,
      priority: routePriority(plan, r.courier_id, jobs),
      pos: pointAlong(r.polyline!, phase),
    }))
    .filter((h) => h.pos) as { courier_id: string; priority: Priority; pos: [number, number] }[];
  layers.push(
    new ScatterplotLayer<(typeof heads)[number]>({
      id: "trip-heads",
      data: heads,
      getPosition: (d) => d.pos,
      getRadius: 9,
      radiusUnits: "pixels",
      stroked: true,
      lineWidthMinPixels: 2,
      getLineColor: [255, 255, 255, 255],
      getFillColor: (d) => [...PRIORITY_RGB[d.priority], 255] as [number, number, number, number],
      updateTriggers: { getPosition: phase },
    }),
  );

  // 5. Couriers, colour by status; selected gets a halo ring.
  layers.push(
    new ScatterplotLayer<Courier>({
      id: "couriers",
      data: couriers,
      getPosition: (c) => [c.location.lng, c.location.lat],
      getRadius: 130,
      radiusUnits: "meters",
      radiusMinPixels: 7,
      radiusMaxPixels: 20,
      stroked: true,
      lineWidthMinPixels: 2,
      getLineColor: (c) => (c.id === selectedCourierId ? [255, 255, 255, 255] : [10, 14, 22, 255]),
      getFillColor: (c) =>
        [...(COURIER_RGB[c.status] ?? [200, 200, 200]), 255] as [number, number, number, number],
      pickable: true,
      updateTriggers: { getLineColor: selectedCourierId },
    }),
  );

  // 6. Disruptions — pulsing markers.
  const disrPts = disruptions
    .filter((d) => d.geometry && d.geometry.length)
    .map((d) => ({ id: d.id, kind: d.kind, loc: d.geometry![0] }));
  if (disrPts.length) {
    const pulse = 0.5 + 0.5 * Math.sin(phase * Math.PI * 2);
    layers.push(
      new ScatterplotLayer<(typeof disrPts)[number]>({
        id: "disruptions-pulse",
        data: disrPts,
        getPosition: (d) => [d.loc.lng, d.loc.lat],
        getRadius: 180 + pulse * 220,
        radiusUnits: "meters",
        radiusMinPixels: 10,
        radiusMaxPixels: 48,
        getFillColor: [...DISRUPTION_RGB, Math.round(40 + pulse * 60)] as [number, number, number, number],
        updateTriggers: { getRadius: phase, getFillColor: phase },
      }),
    );
    layers.push(
      new ScatterplotLayer<(typeof disrPts)[number]>({
        id: "disruptions",
        data: disrPts,
        getPosition: (d) => [d.loc.lng, d.loc.lat],
        getRadius: 140,
        radiusUnits: "meters",
        radiusMinPixels: 7,
        radiusMaxPixels: 22,
        stroked: true,
        lineWidthMinPixels: 2,
        getLineColor: [255, 255, 255, 230],
        getFillColor: [...DISRUPTION_RGB, 180] as [number, number, number, number],
        pickable: true,
      }),
    );
  }

  return layers;
}

export default function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const phaseRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const snapRef = useRef<Snapshot>({ jobs: [], couriers: [], plan: null, disruptions: [], selectedCourierId: null });
  const dataRef = useRef<OptionalData>({ roads: [], buildings: [] });
  const buildingsOnRef = useRef(false);

  const [optional, setOptional] = useState<OptionalData>({ roads: [], buildings: [] });
  const [buildingsOn, setBuildingsOn] = useState(false);
  const [routeCount, setRouteCount] = useState(0);

  const selectCourier = useStore((s) => s.selectCourier);

  // Keep refs in sync with store + local state for the imperative render loop.
  useEffect(() => {
    const update = () => {
      const s = useStore.getState();
      snapRef.current = {
        jobs: Object.values(s.jobs),
        couriers: Object.values(s.couriers),
        plan: s.plan,
        disruptions: s.disruptions,
        selectedCourierId: s.selectedCourierId,
      };
      setRouteCount(s.plan?.routes?.filter((r) => (r.polyline?.length ?? 0) >= 2).length ?? 0);
    };
    update();
    return useStore.subscribe(update);
  }, []);

  useEffect(() => {
    dataRef.current = optional;
  }, [optional]);
  useEffect(() => {
    buildingsOnRef.current = buildingsOn;
  }, [buildingsOn]);

  // Load optional traffic / building data once (graceful on absence).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [roadsGj, buildingsGj] = await Promise.all([
        fetchOptionalJson("/data/roads.geojson"),
        fetchOptionalJson("/data/buildings.geojson"),
      ]);
      if (cancelled) return;
      const roads = parseRoads(roadsGj);
      const buildings = parseBuildings(buildingsGj);
      setOptional({ roads, buildings });
      if (buildings.length) setBuildingsOn(true);
      if (roads.length || buildings.length) {
        useStore.getState().pushLog({
          level: "info",
          source: "system",
          message: `Map data loaded: ${roads.length} road segments, ${buildings.length} buildings.`,
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Init map + overlay once.
  useEffect(() => {
    if (!containerRef.current) return;

    // Premium Mapbox basemap when a token is present; otherwise the token-less
    // MapLibre CARTO dark fallback (kept exactly as-is). Both expose the same
    // imperative surface (addControl / on / easeTo / remove) and both work with
    // deck.gl's MapboxOverlay.
    let map: maplibregl.Map | mapboxgl.Map;
    if (USE_MAPBOX) {
      mapboxgl.accessToken = MAPBOX_TOKEN;
      map = new mapboxgl.Map({
        container: containerRef.current,
        style: MAPBOX_STYLE,
        center: INITIAL_VIEW.center,
        zoom: INITIAL_VIEW.zoom,
        pitch: INITIAL_VIEW.pitch,
        bearing: INITIAL_VIEW.bearing,
        attributionControl: true,
        antialias: true,
      });
      map.addControl(new mapboxgl.NavigationControl({ showCompass: true }), "bottom-left");
    } else {
      map = new maplibregl.Map({
        container: containerRef.current,
        style: MAP_STYLE,
        center: INITIAL_VIEW.center,
        zoom: INITIAL_VIEW.zoom,
        pitch: INITIAL_VIEW.pitch,
        bearing: INITIAL_VIEW.bearing,
        attributionControl: { compact: true },
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "bottom-left");
    }

    // Shared imperative handle: both libraries expose the same surface at runtime,
    // so we narrow the union to one type for the calls below (incl. the deck.gl overlay).
    const m = map as maplibregl.Map;

    m.on("load", () => {
      // Gentle settle for a "command-center" entrance.
      m.easeTo({ zoom: INITIAL_VIEW.zoom + 0.3, duration: 2200, pitch: INITIAL_VIEW.pitch });
    });

    const overlay = new MapboxOverlay({
      interleaved: false,
      layers: [],
      onClick: (info: PickingInfo) => {
        const o = info.object as Record<string, unknown> | null;
        if (o && "status" in o && "location" in o) {
          selectCourier((o as unknown as Courier).id);
        }
      },
      getTooltip: ({ object }: PickingInfo) => {
        if (!object) return null;
        const o = object as Record<string, unknown>;
        if ("status" in o && "location" in o) {
          const c = object as Courier;
          return { text: `${c.name ?? c.id} — ${c.status}` };
        }
        if ("priority" in o && "origin" in o) {
          const j = object as DeliveryJob;
          return { text: `${j.id} [${j.priority}] ${j.origin.name ?? "?"} → ${j.destination.name ?? "?"}` };
        }
        if ("job" in o) {
          const e = object as { job: DeliveryJob; kind: string };
          return { text: `${e.kind}: ${e.job.id} (${e.job.priority})` };
        }
        if ("courier_id" in o && "path" in o) {
          return { text: `route: ${(object as { courier_id: string }).courier_id}` };
        }
        if ("kind" in o && "loc" in o) {
          return { text: `disruption: ${(object as { kind: string }).kind}` };
        }
        return null;
      },
    });
    m.addControl(overlay);
    overlayRef.current = overlay;

    let last = performance.now();
    const LOOP_SECONDS = 12;
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      phaseRef.current = (phaseRef.current + dt / LOOP_SECONDS) % 1;
      overlay.setProps({
        layers: buildLayers(snapRef.current, dataRef.current, buildingsOnRef.current, phaseRef.current),
      });
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      m.remove();
      overlayRef.current = null;
    };
  }, [selectCourier]);

  const trafficOn = optional.roads.length > 0;
  const hasBuildings = optional.buildings.length > 0;
  const layerStatus = useMemo(
    () =>
      [
        `routes:${routeCount}`,
        `traffic:${trafficOn ? optional.roads.length : "off"}`,
        `buildings:${hasBuildings ? (buildingsOn ? "on" : "off") : "absent"}`,
      ].join(" · "),
    [routeCount, trafficOn, optional.roads.length, hasBuildings, buildingsOn],
  );

  return (
    <div className="map-wrap">
      <div ref={containerRef} className="map-root" />

      <div className="map-overlays">
        <div
          className="map-chip route-status"
          data-testid="route-layer-status"
          data-route-count={routeCount}
          data-traffic={trafficOn ? "on" : "off"}
          data-buildings={hasBuildings ? (buildingsOn ? "on" : "off") : "absent"}
        >
          <span className="chip-led" /> {layerStatus}
        </div>

        {hasBuildings && (
          <button
            className={`map-toggle ${buildingsOn ? "on" : ""}`}
            onClick={() => setBuildingsOn((v) => !v)}
          >
            3D Buildings {buildingsOn ? "ON" : "OFF"}
          </button>
        )}
      </div>

      <div className="map-legend">
        <span><i className="ldot" style={{ background: "#ff4d4f" }} /> STAT</span>
        <span><i className="ldot" style={{ background: "#ffb020" }} /> Urgent</span>
        <span><i className="ldot" style={{ background: "#4da6ff" }} /> Routine</span>
        <span className="lsep" />
        <span><i className="ldot" style={{ background: "#3ddc84" }} /> Idle</span>
        <span><i className="ldot" style={{ background: "#22d3ee" }} /> En route</span>
        <span><i className="ldot" style={{ background: "#6b7689" }} /> Offline</span>
      </div>
    </div>
  );
}
