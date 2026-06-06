// CityScene — the Square Mile Pulse Three.js LiDAR digital twin, ported into RLJ
// as the main view (replacing the deck.gl/MapLibre map).
//
// Renders the real EA National LIDAR Programme scan (citycloud.bin, 3M points)
// as a cyberpunk cyan point cloud, with OSM building facades extruded to fill
// the towers (citybuildings.json, ~4.4k City buildings), an infinite grid, a
// radar sweep, bloom + vignette, and orbit/zoom controls. Orange beams rise at
// live disruptions from RLJ's orchestrator (red for road closures).

import { Canvas, useFrame } from "@react-three/fiber";
import { Grid, OrbitControls } from "@react-three/drei";
import { Bloom, EffectComposer, Vignette } from "@react-three/postprocessing";
import { useEffect, useMemo, useState } from "react";
import { useRef } from "react";
import * as THREE from "three";
import { buildFacades, buildPointCloud, type BuildingsResponse } from "../lib/pointcloud";
import { project } from "../lib/scene-geo";
import { useStore } from "../store";

function merge(a: Float32Array, b: Float32Array): Float32Array {
  const out = new Float32Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

interface CloudMeta {
  count: number;
  minY: number;
  maxY: number;
  groundY: number;
  source: string;
}

// Cyberpunk teal gradient, deep base -> bright cyan crown. Kept dark at the base
// so the dense ground doesn't blow out under additive blending.
function colorize(positions: Float32Array, meta: { groundY: number; maxY: number }): Float32Array {
  const colors = new Float32Array(positions.length);
  const lo = meta.groundY;
  const span = Math.max(1, meta.maxY - lo);
  for (let i = 0; i < positions.length; i += 3) {
    const y = positions[i + 1];
    const t = Math.min(1, Math.max(0, (y - lo) / span));
    colors[i] = 0.03 + (0.45 - 0.03) * t;
    colors[i + 1] = 0.17 + (0.82 - 0.17) * t;
    colors[i + 2] = 0.24 + (0.98 - 0.24) * t;
  }
  return colors;
}

/** Loads the real EA LiDAR point cloud; falls back to the OSM building cloud. */
function CityCloud({ fallback, opacityScale = 1 }: { fallback: BuildingsResponse; opacityScale?: number }) {
  const [geom, setGeom] = useState<THREE.BufferGeometry | null>(null);
  const [real, setReal] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [binRes, metaRes] = await Promise.all([fetch("/citycloud.bin"), fetch("/citycloud.json")]);
        if (!binRes.ok || !metaRes.ok) throw new Error("no asset");
        const buf = await binRes.arrayBuffer();
        const m: CloudMeta = await metaRes.json();
        const lidarPos = new Float32Array(buf);
        const lidarCol = colorize(lidarPos, m);
        // Aerial LiDAR lacks walls — add extruded OSM facades so towers read solid.
        const fac = buildFacades(fallback.buildings, fallback.center);
        const positions = merge(lidarPos, fac.positions);
        const colors = merge(lidarCol, fac.colors);
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
        g.setAttribute("color", new THREE.BufferAttribute(colors, 3));
        if (alive) {
          setGeom(g);
          setReal(true);
        }
      } catch {
        // Fallback: synthesize a cloud from OSM building footprints.
        const cloud = buildPointCloud(fallback.buildings, fallback.center);
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.BufferAttribute(cloud.positions, 3));
        g.setAttribute("color", new THREE.BufferAttribute(cloud.colors, 3));
        if (alive) {
          setGeom(g);
          setReal(false);
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [fallback]);

  if (!geom) return null;
  return (
    <points geometry={geom}>
      <pointsMaterial
        size={real ? 1.35 : 2.3}
        sizeAttenuation
        vertexColors
        transparent
        opacity={(real ? 0.55 : 0.85) * opacityScale}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

function Beam({
  position,
  color,
  height,
  pulse,
}: {
  position: [number, number, number];
  color: string;
  height: number;
  pulse?: boolean;
}) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame((state) => {
    if (ref.current && pulse) {
      const mtl = ref.current.material as THREE.MeshBasicMaterial;
      mtl.opacity = 0.45 + 0.35 * (0.5 + 0.5 * Math.sin(state.clock.elapsedTime * 3));
    }
  });
  return (
    <group position={position}>
      <mesh ref={ref} position={[0, height / 2, 0]}>
        <cylinderGeometry args={[pulse ? 5 : 2.5, pulse ? 5 : 2.5, height, 12, 1, true]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={0.6}
          side={THREE.DoubleSide}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 1, 0]}>
        <ringGeometry args={[pulse ? 10 : 5, pulse ? 18 : 9, 32]} />
        <meshBasicMaterial color={color} transparent opacity={0.5} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>
    </group>
  );
}

function Scanner({ radius }: { radius: number }) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame((state) => {
    if (ref.current) {
      const t = (state.clock.elapsedTime * 0.12) % 1;
      const s = t * radius;
      ref.current.scale.set(s, s, s);
      (ref.current.material as THREE.MeshBasicMaterial).opacity = 0.32 * (1 - t);
    }
  });
  return (
    <mesh ref={ref} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.5, 0]}>
      <ringGeometry args={[0.96, 1, 96]} />
      <meshBasicMaterial color="#5ad1ff" transparent opacity={0.3} blending={THREE.AdditiveBlending} depthWrite={false} />
    </mesh>
  );
}

interface BeamSpec {
  key: string;
  position: [number, number, number];
  color: string;
  height: number;
}

function Scene({ data, beams }: { data: BuildingsResponse; beams: BeamSpec[] }) {
  return (
    <Canvas
      gl={{ antialias: true, powerPreference: "high-performance" }}
      camera={{ position: [-120, 430, 760], fov: 58, near: 1, far: 8000 }}
      style={{ background: "#04060b" }}
    >
      <color attach="background" args={["#04060b"]} />
      <fog attach="fog" args={["#04060b", 850, 4000]} />
      <ambientLight intensity={0.4} />

      <CityCloud fallback={data} />

      <Grid
        args={[6000, 6000]}
        cellSize={60}
        cellThickness={0.5}
        cellColor="#0d3a44"
        sectionSize={300}
        sectionThickness={1}
        sectionColor="#13616f"
        fadeDistance={3600}
        fadeStrength={2}
        infiniteGrid
      />

      <Scanner radius={2600} />

      {beams.map((b) => (
        <Beam key={b.key} position={b.position} color={b.color} height={b.height} />
      ))}

      <OrbitControls
        enablePan
        autoRotate
        autoRotateSpeed={0.3}
        maxPolarAngle={Math.PI / 2.1}
        minDistance={150}
        maxDistance={3200}
        target={[360, 40, -180]}
      />

      <EffectComposer>
        <Bloom intensity={0.5} luminanceThreshold={0.3} luminanceSmoothing={0.8} mipmapBlur radius={0.6} />
        <Vignette eskil={false} offset={0.25} darkness={0.82} />
      </EffectComposer>
    </Canvas>
  );
}

export default function CityScene() {
  const [data, setData] = useState<BuildingsResponse | null>(null);
  const disruptions = useStore((s) => s.disruptions);

  // Load the baked City buildings (footprints + heights) once.
  useEffect(() => {
    let alive = true;
    fetch("/citybuildings.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((d: BuildingsResponse | null) => {
        if (alive && d) setData(d);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // Disruption beams: rise at each live disruption (red for road closures).
  const beams = useMemo<BeamSpec[]>(() => {
    if (!data) return [];
    return disruptions
      .map((d, i) => {
        const g = d.geometry?.[0];
        if (!g || !Number.isFinite(g.lat) || !Number.isFinite(g.lng)) return null;
        const [x, z] = project({ lat: g.lat, lon: g.lng }, data.center);
        const closure = d.kind === "road_closure";
        return {
          key: d.id || `d-${i}`,
          position: [x, 0, z] as [number, number, number],
          color: closure ? "#ff4d6d" : "#ffb020",
          height: closure ? 240 : 150,
        };
      })
      .filter((b): b is BeamSpec => b !== null);
  }, [disruptions, data]);

  return (
    <div className="scene-wrap">
      {data ? (
        <Scene data={data} beams={beams} />
      ) : (
        <div className="scene-loading">Loading LiDAR digital twin…</div>
      )}

      <div className="scene-legend glass">
        <div className="sl-title">EA LiDAR · 3.0M pts + facades</div>
        <div className="sl-row">
          <span className="sl-dot" style={{ background: "#5ad1ff" }} />
          Surface + building facades
        </div>
        <div className="sl-row">
          <span className="sl-dot" style={{ background: "#ffb020" }} />
          Disruption beams{beams.length ? ` · ${beams.length}` : ""}
        </div>
        <div className="sl-hint">drag to orbit · scroll to zoom</div>
      </div>
    </div>
  );
}
