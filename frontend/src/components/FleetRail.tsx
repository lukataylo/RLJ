// Left rail "fleet roster": tabs + per-courier cards (status dot, GPS/LTE chips,
// mini route sparkline) + an Operational Efficiency gauge (window compliance %).

import { useMemo, useState } from "react";
import { useStore } from "../store";
import { COURIER_HEX, PRIORITY_HEX } from "../lib/palette";
import { courierScheduleOffset, fmtSigned } from "../lib/format";
import Gauge from "./Gauge";
import Sparkline from "./Sparkline";
import type { Courier, DeliveryJob, Plan } from "../types";

type Tab = "map" | "fleet" | "routes" | "analytics";
const TABS: { id: Tab; label: string }[] = [
  { id: "map", label: "Live Map" },
  { id: "fleet", label: "Fleet" },
  { id: "routes", label: "Routes" },
  { id: "analytics", label: "Analytics" },
];

function statusWord(s: Courier["status"]): string {
  return s === "enroute" ? "EN ROUTE" : s === "idle" ? "IDLE" : "OFFLINE";
}

function routeSparkValues(plan: Plan | null, courierId: string): number[] {
  const route = plan?.routes?.find((r) => r.courier_id === courierId);
  const stops = route?.stops ?? [];
  if (stops.length < 2) return [];
  // Synthesize a smooth profile from sequential ETAs so each courier reads distinct.
  return stops.map((s, i) => {
    const t = s.eta ? new Date(s.eta).getTime() : i;
    return (t % 997) / 997 + i * 0.15;
  });
}

function CourierCard({
  c,
  plan,
  jobs,
  selected,
  onSelect,
}: {
  c: Courier;
  plan: Plan | null;
  jobs: DeliveryJob[];
  selected: boolean;
  onSelect: () => void;
}) {
  const route = plan?.routes?.find((r) => r.courier_id === c.id);
  const { offsetMin } = courierScheduleOffset(plan, c.id, jobs);
  const stopCount = route?.stops?.length ?? 0;
  const color = COURIER_HEX[c.status];
  const online = c.status !== "offline";
  return (
    <button
      className={`courier-card ${selected ? "sel" : ""}`}
      onClick={onSelect}
      data-testid={`courier-card-${c.id}`}
    >
      <div className="cc-top">
        <span className="cc-name">
          <span className="cc-dot" style={{ background: color, boxShadow: `0 0 8px ${color}` }} />
          {c.name ?? c.id}
        </span>
        <span className="cc-status" style={{ color }}>
          {statusWord(c.status)}
        </span>
      </div>
      <div className="cc-chips">
        <span className={`chip ${online ? "chip-ok" : "chip-off"}`}>GPS</span>
        <span className={`chip ${online ? "chip-ok" : "chip-off"}`}>LTE</span>
        <span className="chip chip-muted">{stopCount} stops</span>
        {c.cold_capable !== false && <span className="chip chip-cold">COLD</span>}
      </div>
      <div className="cc-foot">
        <Sparkline values={routeSparkValues(plan, c.id)} width={108} height={26} color={color} />
        <span
          className="cc-offset"
          style={{
            color:
              offsetMin == null ? "var(--muted)" : offsetMin >= 0 ? "var(--green)" : "var(--red)",
          }}
        >
          {offsetMin == null ? "—" : fmtSigned(offsetMin, "m")}
        </span>
      </div>
    </button>
  );
}

export default function FleetRail() {
  const [tab, setTab] = useState<Tab>("fleet");
  const couriersMap = useStore((s) => s.couriers);
  const jobsMap = useStore((s) => s.jobs);
  const plan = useStore((s) => s.plan);
  const selectedId = useStore((s) => s.selectedCourierId);
  const selectCourier = useStore((s) => s.selectCourier);

  const couriers = useMemo(() => Object.values(couriersMap), [couriersMap]);
  const jobs = useMemo(() => Object.values(jobsMap), [jobsMap]);

  const obj = plan?.objective;
  const compliance =
    obj?.windows_total && obj.windows_total > 0
      ? ((obj.windows_met ?? 0) / obj.windows_total) * 100
      : 0;

  const onlineCount = couriers.filter((c) => c.status !== "offline").length;

  return (
    <aside className="fleet-rail" data-testid="fleet-rail">
      <nav className="rail-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`rail-tab ${tab === t.id ? "active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="rail-gauge">
        <Gauge value={compliance} label="Operational Efficiency" />
        <div className="rail-gauge-meta">
          <div>
            <span className="rgm-num">{onlineCount}</span>
            <span className="rgm-lbl">online</span>
          </div>
          <div>
            <span className="rgm-num">{plan?.routes?.length ?? 0}</span>
            <span className="rgm-lbl">routes</span>
          </div>
          <div>
            <span className="rgm-num">{jobs.length}</span>
            <span className="rgm-lbl">jobs</span>
          </div>
        </div>
      </div>

      <div className="rail-section-title">Fleet Roster</div>
      <div className="rail-list">
        {couriers.length === 0 && <div className="rail-empty">No couriers in service.</div>}
        {couriers.map((c) => (
          <CourierCard
            key={c.id}
            c={c}
            plan={plan}
            jobs={jobs}
            selected={selectedId === c.id}
            onSelect={() => selectCourier(selectedId === c.id ? null : c.id)}
          />
        ))}
      </div>

      {tab === "routes" || tab === "analytics" ? (
        <div className="rail-extra">
          <div className="rail-legend">
            <span><i className="ldot" style={{ background: PRIORITY_HEX.stat }} /> STAT</span>
            <span><i className="ldot" style={{ background: PRIORITY_HEX.urgent }} /> Urgent</span>
            <span><i className="ldot" style={{ background: PRIORITY_HEX.routine }} /> Routine</span>
          </div>
        </div>
      ) : null}
    </aside>
  );
}
