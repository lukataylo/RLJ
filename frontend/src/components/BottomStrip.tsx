// Bottom detail strip: selected courier — schedule offset (±min) and next-stop ETA.

import { useMemo } from "react";
import { useStore } from "../store";
import { COURIER_HEX } from "../lib/palette";
import { courierScheduleOffset, fmtClock, fmtSigned, relativeAge } from "../lib/format";

export default function BottomStrip() {
  const selectedId = useStore((s) => s.selectedCourierId);
  const couriersMap = useStore((s) => s.couriers);
  const jobsMap = useStore((s) => s.jobs);
  const plan = useStore((s) => s.plan);
  const selectCourier = useStore((s) => s.selectCourier);

  const jobs = useMemo(() => Object.values(jobsMap), [jobsMap]);
  const courier = selectedId ? couriersMap[selectedId] : null;

  if (!courier) {
    return (
      <div className="bottom-strip empty">
        <span className="bs-hint">Select a courier from the roster to inspect schedule & ETA.</span>
      </div>
    );
  }

  const route = plan?.routes?.find((r) => r.courier_id === courier.id);
  const { offsetMin, nextStopEta, nextStopName } = courierScheduleOffset(plan, courier.id, jobs);
  const color = COURIER_HEX[courier.status];
  const distKm = route?.total_distance_m != null ? (route.total_distance_m / 1000).toFixed(1) : "—";
  const timeMin = route?.total_time_s != null ? Math.round(route.total_time_s / 60) : null;

  return (
    <div className="bottom-strip">
      <div className="bs-id">
        <span className="bs-dot" style={{ background: color, boxShadow: `0 0 10px ${color}` }} />
        <div>
          <div className="bs-name">{courier.name ?? courier.id}</div>
          <div className="bs-role">{courier.status.toUpperCase()} · {courier.id}</div>
        </div>
      </div>

      <div className="bs-metrics">
        <div className="bs-metric">
          <span className="bs-m-label">Schedule offset</span>
          <span
            className="bs-m-value"
            style={{ color: offsetMin == null ? "var(--text)" : offsetMin >= 0 ? "var(--green)" : "var(--red)" }}
          >
            {offsetMin == null ? "—" : fmtSigned(offsetMin, " min")}
          </span>
        </div>
        <div className="bs-metric">
          <span className="bs-m-label">Next stop</span>
          <span className="bs-m-value sm">{nextStopName ?? "—"}</span>
        </div>
        <div className="bs-metric">
          <span className="bs-m-label">Next ETA</span>
          <span className="bs-m-value">
            {nextStopEta ? fmtClock(nextStopEta) : "—"}
            {nextStopEta && <span className="bs-m-rel"> · {relativeAge(nextStopEta)}</span>}
          </span>
        </div>
        <div className="bs-metric">
          <span className="bs-m-label">Route</span>
          <span className="bs-m-value">{distKm} km{timeMin != null ? ` · ${timeMin}m` : ""}</span>
        </div>
        <div className="bs-metric">
          <span className="bs-m-label">Stops</span>
          <span className="bs-m-value">{route?.stops?.length ?? 0}</span>
        </div>
      </div>

      <button className="bs-clear" onClick={() => selectCourier(null)}>
        Clear
      </button>
    </div>
  );
}
