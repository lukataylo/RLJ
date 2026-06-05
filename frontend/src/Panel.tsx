// Right-hand HUD: scoreboard + demo controls + live agent log.

import { useEffect, useMemo, useRef, useState } from "react";
import { optimize, postDisruption, postJob } from "./api";
import { useStore } from "./store";
import type { DeliveryJob, DisruptionEvent } from "./types";

// A London street segment to "close" for the re-route money shot
// (Waterloo Bridge approach — sits between several of the seed jobs).
const ROAD_CLOSURE_GEOMETRY = [
  { lat: 51.5085, lng: -0.1175 },
  { lat: 51.5065, lng: -0.1165 },
];

// Sample STAT job injected by the demo button (fresh window from "now").
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

const LEVEL_CLASS: Record<string, string> = {
  warn: "log-warn",
  error: "log-error",
  info: "log-info",
};

export default function Panel() {
  const connected = useStore((s) => s.connected);
  const plan = useStore((s) => s.plan);
  const couriers = useStore((s) => s.couriers);
  const jobs = useStore((s) => s.jobs);
  const logs = useStore((s) => s.logs);

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const logEndRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll the log to the latest line.
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  const obj = plan?.objective;
  const totalTimeMin = useMemo(
    () => (obj?.total_time_s != null ? Math.round(obj.total_time_s / 60) : null),
    [obj?.total_time_s],
  );

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

  const windowsMet = obj?.windows_met ?? 0;
  const windowsTotal = obj?.windows_total ?? 0;
  const windowPct = windowsTotal ? Math.round((windowsMet / windowsTotal) * 100) : 0;

  return (
    <aside className="panel">
      <header className="panel-head">
        <div className="brand">
          <span className="logo">RLJ</span>
          <span className="brand-sub">London Medical Courier Ops</span>
        </div>
        <span className={`conn ${connected ? "conn-up" : "conn-down"}`}>
          {connected ? "LIVE" : "OFFLINE"}
        </span>
      </header>

      {/* Scoreboard / HUD — sells the GPU story. */}
      <section className="scoreboard">
        <div className="stat big">
          <div className="stat-value">
            {windowsMet}
            <span className="stat-sub">/{windowsTotal}</span>
          </div>
          <div className="stat-label">clinical windows met</div>
          <div className="bar">
            <div
              className="bar-fill"
              style={{
                width: `${windowPct}%`,
                background: windowPct === 100 ? "#4caf50" : "#ffb300",
              }}
            />
          </div>
        </div>
        <div className="stat-row">
          <div className="stat">
            <div className="stat-value sm">{obj?.solver ?? "—"}</div>
            <div className="stat-label">active solver</div>
          </div>
          <div className="stat">
            <div className="stat-value sm">
              {obj?.solve_ms != null ? `${Math.round(obj.solve_ms)} ms` : "—"}
            </div>
            <div className="stat-label">solve time</div>
          </div>
        </div>
        <div className="stat-row">
          <div className="stat">
            <div className="stat-value sm">{totalTimeMin != null ? `${totalTimeMin} min` : "—"}</div>
            <div className="stat-label">total route time</div>
          </div>
          <div className="stat">
            <div className="stat-value sm">
              {plan?.routes.length ?? 0}r · {Object.keys(jobs).length}j
            </div>
            <div className="stat-label">routes · jobs</div>
          </div>
        </div>
        {plan?.unassigned && plan.unassigned.length > 0 && (
          <div className="unassigned">⚠ unassigned: {plan.unassigned.join(", ")}</div>
        )}
      </section>

      {/* Legend */}
      <section className="legend">
        <span><i className="dot stat" /> stat</span>
        <span><i className="dot urgent" /> urgent</span>
        <span><i className="dot routine" /> routine</span>
        <span className="legend-sep" />
        <span><i className="dot idle" /> idle</span>
        <span><i className="dot enroute" /> enroute</span>
        <span><i className="dot offline" /> offline</span>
      </section>

      {/* Demo controls */}
      <section className="controls">
        <button className="btn danger" onClick={closeRoad} disabled={!!busy}>
          {busy === "road" ? "…" : "Close road"}
        </button>
        <button className="btn danger" onClick={courierDown} disabled={!!busy}>
          {busy === "courier" ? "…" : "Courier down"}
        </button>
        <button className="btn warn" onClick={addStat} disabled={!!busy}>
          {busy === "stat" ? "…" : "Add STAT job"}
        </button>
        <button className="btn primary" onClick={reoptimize} disabled={!!busy}>
          {busy === "optimize" ? "…" : "Re-optimize"}
        </button>
      </section>
      {error && <div className="error">{error}</div>}

      {/* Agent log */}
      <section className="log">
        <div className="log-title">Agent log</div>
        <div className="log-body">
          {logs.length === 0 && <div className="log-empty">Waiting for events…</div>}
          {logs.map((l, i) => (
            <div key={i} className={`log-line ${LEVEL_CLASS[l.level] ?? "log-info"}`}>
              <span className="log-ts">{new Date(l.ts).toLocaleTimeString()}</span>
              <span className={`log-tag tag-${l.source}`}>{l.source}</span>
              <span className="log-msg">{l.message}</span>
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      </section>
    </aside>
  );
}
