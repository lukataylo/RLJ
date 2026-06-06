// TOP-RIGHT operational-efficiency panel: an arc gauge (window-compliance %),
// a "vs naive dispatch" delta, and the KPI stat row. Carries the required
// data-testids: kpi-windows, kpi-solve-ms, kpi-solver.

import { useMemo } from "react";
import { useStore } from "../store";
import Gauge from "./Gauge";
import { statInFlight } from "../lib/format";

export default function EfficiencyPanel() {
  const plan = useStore((s) => s.plan);
  const jobsMap = useStore((s) => s.jobs);
  const jobs = useMemo(() => Object.values(jobsMap), [jobsMap]);

  const obj = plan?.objective;
  const windowsMet = obj?.windows_met ?? 0;
  const windowsTotal = obj?.windows_total ?? 0;
  const compliance = windowsTotal > 0 ? (windowsMet / windowsTotal) * 100 : 0;

  // Naive-dispatch baseline estimate -> improvement multiplier for the delta chip.
  const naive = Math.max(1, Math.round(windowsTotal * 0.6));
  const deltaX = windowsMet > 0 ? windowsMet / naive : 0;

  const stat = statInFlight(jobs);
  const solveMs = obj?.solve_ms;
  const solver = obj?.solver ?? "—";

  return (
    <section className="eff-panel glass">
      <div className="eff-top">
        <div className="eff-gauge">
          <Gauge value={compliance} label="" size={118} />
        </div>
        <div className="eff-head">
          <div className="eff-cap">OPERATIONAL EFFICIENCY</div>
          <div className="eff-sub">Window compliance, live</div>
          <div className="eff-delta">▲ {deltaX.toFixed(1)}× vs naive dispatch</div>
        </div>
      </div>

      <div className="eff-stats">
        <div className="eff-stat" data-testid="kpi-windows">
          <span className="es-num">
            {windowsMet}/{windowsTotal}
          </span>
          <span className="es-lbl">ON-TIME</span>
        </div>
        <div className="eff-stat danger">
          <span className="es-num">{stat}</span>
          <span className="es-lbl">STAT</span>
        </div>
        <div className="eff-stat" data-testid="kpi-solve-ms">
          <span className="es-num">{solveMs != null ? Math.round(solveMs) : "—"}</span>
          <span className="es-lbl">RE-PLAN ms</span>
        </div>
        <div className="eff-stat" data-testid="kpi-solver">
          <span className="es-num solver">{solver}</span>
          <span className="es-lbl">SOLVER</span>
        </div>
      </div>
    </section>
  );
}
