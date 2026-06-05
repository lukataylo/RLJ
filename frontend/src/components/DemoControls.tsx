// Demo controls wired to the existing orchestrator endpoints. Each action mutates
// server state; the map redraws when the resulting plan_updated arrives on the WS.

import { useState } from "react";
import { optimize, postDisruption, postJob } from "../api";
import { useStore } from "../store";
import type { DeliveryJob, DisruptionEvent } from "../types";

// Waterloo Bridge approach in central London — sits between several seed jobs so
// closing it forces a visible re-route.
const ROAD_CLOSURE_GEOMETRY = [
  { lat: 51.5085, lng: -0.1175 },
  { lat: 51.5065, lng: -0.1165 },
];

function sampleStatJob(): Partial<DeliveryJob> {
  const now = Date.now();
  return {
    type: "sample_pickup",
    priority: "stat",
    cold_chain: true,
    capacity_units: 1,
    status: "new",
    origin: { lat: 51.5246, lng: -0.134, name: "UCLH A&E" },
    destination: {
      lat: 51.498,
      lng: -0.1188,
      name: "St Thomas' Hospital lab",
      facility_id: "RJ122",
    },
    time_window: {
      ready_at: new Date(now).toISOString(),
      due_by: new Date(now + 45 * 60 * 1000).toISOString(),
    },
    raw_text: "STAT crossmatch sample — UCLH A&E to St Thomas lab within 45 minutes.",
  };
}

export default function DemoControls() {
  const couriers = useStore((s) => s.couriers);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(name: string, fn: () => Promise<unknown>) {
    setBusy(name);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const closeRoad = () =>
    run("road", () =>
      postDisruption({
        kind: "road_closure",
        source: "manual",
        geometry: ROAD_CLOSURE_GEOMETRY,
      } as Partial<DisruptionEvent>),
    );

  const courierDown = () => {
    const victim = Object.values(couriers).find((c) => c.status !== "offline");
    if (!victim) {
      setError("No online courier to take down.");
      return;
    }
    return run("courier", () =>
      postDisruption({
        kind: "courier_down",
        source: "manual",
        courier_id: victim.id,
      } as Partial<DisruptionEvent>),
    );
  };

  const addStat = () => run("stat", () => postJob(sampleStatJob()));
  const reoptimize = () => run("optimize", () => optimize());

  return (
    <section className="demo">
      <div className="demo-title">Scenario Controls</div>
      <div className="demo-grid">
        <button
          className="cbtn danger"
          data-testid="btn-close-road"
          onClick={closeRoad}
          disabled={!!busy}
        >
          <span className="cbtn-icon">⛔</span>
          {busy === "road" ? "Closing…" : "Close road"}
        </button>
        <button className="cbtn danger" onClick={courierDown} disabled={!!busy}>
          <span className="cbtn-icon">⚠</span>
          {busy === "courier" ? "…" : "Courier down"}
        </button>
        <button
          className="cbtn warn"
          data-testid="btn-add-stat"
          onClick={addStat}
          disabled={!!busy}
        >
          <span className="cbtn-icon">＋</span>
          {busy === "stat" ? "Adding…" : "Add STAT job"}
        </button>
        <button className="cbtn primary" onClick={reoptimize} disabled={!!busy}>
          <span className="cbtn-icon">↻</span>
          {busy === "optimize" ? "Solving…" : "Re-optimize"}
        </button>
      </div>
      {error && <div className="demo-error">{error}</div>}
    </section>
  );
}
