// Live, driver-centred map. Token-less MapLibre CARTO dark basemap by default;
// premium Mapbox dark style when VITE_MAPBOX_TOKEN is present (mirrors the
// frontend ops console). Renders:
//   - congestion heat (GET /congestion -> coloured, blurred circle field)
//   - the driver's route polyline (from guidance) with a neon glow underlay
//   - the next junction marker (from green-wave advice)
//   - the driver's own position (pulsing dot + heading arrow), map follows it
// All layers are native GeoJSON sources, updated imperatively from the store.

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import mapboxgl from "mapbox-gl";
import type { FeatureCollection } from "geojson";
import { useStore } from "../store";
import type { CongestionCell, LatLng } from "../types";

const MAPBOX_TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN ?? "").trim();
const USE_MAPBOX = MAPBOX_TOKEN.length > 0;
const MAPBOX_STYLE = "mapbox://styles/mapbox/dark-v11";

const INITIAL_CENTER: [number, number] = [-0.1195, 51.5033];

// Free, token-less dark raster basemap (CARTO dark_matter).
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

const EMPTY_FC: FeatureCollection = { type: "FeatureCollection", features: [] };

function congestionFC(cells: CongestionCell[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: cells.map((c) => ({
      type: "Feature",
      properties: { congestion: c.congestion },
      geometry: { type: "Point", coordinates: [c.lng, c.lat] },
    })),
  };
}

function routeFC(poly: LatLng[] | undefined): FeatureCollection {
  if (!poly || poly.length < 2) return EMPTY_FC;
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry: {
          type: "LineString",
          coordinates: poly.map((p) => [p.lng, p.lat]),
        },
      },
    ],
  };
}

function junctionFC(j: LatLng | undefined): FeatureCollection {
  if (!j) return EMPTY_FC;
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry: { type: "Point", coordinates: [j.lng, j.lat] },
      },
    ],
  };
}

export default function DriverMap() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const arrowRef = useRef<HTMLDivElement | null>(null);
  const readyRef = useRef(false);
  const firstFollowRef = useRef(true);

  useEffect(() => {
    if (!containerRef.current) return;

    // Driver marker DOM (pulsing dot + heading arrow).
    const el = document.createElement("div");
    el.className = "driver-marker";
    const arrow = document.createElement("div");
    arrow.className = "driver-arrow";
    el.appendChild(arrow);
    arrowRef.current = arrow;

    // Construct the control + marker INSIDE each branch so the map type is
    // narrowed to the matching library (mapbox/maplibre types don't unify).
    let map: maplibregl.Map | mapboxgl.Map;
    if (USE_MAPBOX) {
      mapboxgl.accessToken = MAPBOX_TOKEN;
      map = new mapboxgl.Map({
        container: containerRef.current,
        style: MAPBOX_STYLE,
        center: INITIAL_CENTER,
        zoom: 14,
        pitch: 45,
        attributionControl: true,
      });
      map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "bottom-right");
      markerRef.current = new mapboxgl.Marker({ element: el })
        .setLngLat(INITIAL_CENTER)
        .addTo(map) as unknown as maplibregl.Marker;
    } else {
      map = new maplibregl.Map({
        container: containerRef.current,
        style: MAP_STYLE,
        center: INITIAL_CENTER,
        zoom: 14,
        pitch: 45,
        attributionControl: { compact: true },
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
      markerRef.current = new maplibregl.Marker({ element: el })
        .setLngLat(INITIAL_CENTER)
        .addTo(map);
    }

    // Both libs expose the same imperative surface at runtime.
    const m = map as maplibregl.Map;
    mapRef.current = m;

    m.on("load", () => {
      m.addSource("congestion", { type: "geojson", data: EMPTY_FC });
      m.addLayer({
        id: "congestion-heat",
        type: "circle",
        source: "congestion",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 16, 15, 42],
          "circle-color": [
            "interpolate",
            ["linear"],
            ["get", "congestion"],
            0, "#18f0ff",
            0.5, "#ffc24b",
            1, "#ff3b5c",
          ],
          "circle-blur": 0.9,
          "circle-opacity": 0.32,
        },
      });

      m.addSource("route", { type: "geojson", data: EMPTY_FC });
      m.addLayer({
        id: "route-glow",
        type: "line",
        source: "route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#18f0ff", "line-width": 14, "line-opacity": 0.18 },
      });
      m.addLayer({
        id: "route-line",
        type: "line",
        source: "route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#18f0ff", "line-width": 4, "line-opacity": 0.9 },
      });

      m.addSource("junction", { type: "geojson", data: EMPTY_FC });
      m.addLayer({
        id: "junction-glow",
        type: "circle",
        source: "junction",
        paint: {
          "circle-radius": 18,
          "circle-color": "#ff9d2f",
          "circle-blur": 0.8,
          "circle-opacity": 0.5,
        },
      });
      m.addLayer({
        id: "junction-dot",
        type: "circle",
        source: "junction",
        paint: {
          "circle-radius": 6,
          "circle-color": "#ff9d2f",
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });

      readyRef.current = true;
      // Paint whatever is already in the store.
      pushToMap(useStore.getState());
    });

    const setData = (id: string, data: FeatureCollection) => {
      const src = m.getSource(id) as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(data);
    };

    const pushToMap = (s: ReturnType<typeof useStore.getState>) => {
      if (!readyRef.current) return;
      setData("congestion", congestionFC(s.congestion));
      setData("route", routeFC(s.guidance?.route_polyline));
      setData("junction", junctionFC(s.advice?.junction));

      if (s.position) {
        markerRef.current?.setLngLat([s.position.lng, s.position.lat]);
        if (arrowRef.current && s.lastFix) {
          arrowRef.current.style.transform = `rotate(${s.lastFix.heading_deg}deg)`;
        }
        // Follow the driver while sharing.
        if (s.sharing) {
          if (firstFollowRef.current) {
            m.easeTo({ center: [s.position.lng, s.position.lat], zoom: 15, duration: 1200 });
            firstFollowRef.current = false;
          } else {
            m.easeTo({ center: [s.position.lng, s.position.lat], duration: 900 });
          }
        }
      }
    };

    const unsub = useStore.subscribe(pushToMap);

    return () => {
      unsub();
      markerRef.current?.remove();
      m.remove();
      mapRef.current = null;
      readyRef.current = false;
      firstFollowRef.current = true;
    };
  }, []);

  return (
    <div className="map-wrap">
      <div ref={containerRef} className="map-root" />
      <div className="map-legend">
        <span><i className="ldot" style={{ background: "#18f0ff" }} /> Free-flow</span>
        <span><i className="ldot" style={{ background: "#ffc24b" }} /> Busy</span>
        <span><i className="ldot" style={{ background: "#ff3b5c" }} /> Jammed</span>
      </div>
    </div>
  );
}
