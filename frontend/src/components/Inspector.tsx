// RIGHT inspector card. Default = fleet overview; when a courier is selected it
// shows the live job detail (id, STAT badge, origin→destination, metric row, chips,
// progress, and the primary YELLOW "CALL COURIER" action). data-testid="inspector".

import { useMemo } from "react";
import { useStore } from "../store";
import { postNotification } from "../api";
import { courierScheduleOffset, fmtClock } from "../lib/format";
import type { DeliveryJob } from "../types";

function primaryJob(jobIds: string[], jobsMap: Record<string, DeliveryJob>): DeliveryJob | null {
  const jobs = jobIds.map((id) => jobsMap[id]).filter(Boolean) as DeliveryJob[];
  return jobs.find((j) => j.priority === "stat") ?? jobs[0] ?? null;
}

export default function Inspector() {
  const selectedId = useStore((s) => s.selectedCourierId);
  const couriersMap = useStore((s) => s.couriers);
  const jobsMap = useStore((s) => s.jobs);
  const plan = useStore((s) => s.plan);
  const selectCourier = useStore((s) => s.selectCourier);

  const jobs = useMemo(() => Object.values(jobsMap), [jobsMap]);
  const courier = selectedId ? couriersMap[selectedId] : null;

  // No courier selected → render nothing (fleet-overview segment removed per
  // design feedback; the right column is just the floating delivery cards).
  if (!courier) return null;

  const route = plan?.routes?.find((r) => r.courier_id === courier.id);
  const stops = [...(route?.stops ?? [])].sort((a, b) => a.sequence - b.sequence);
  const jobIds = [...new Set(stops.map((s) => s.job_id))];
  const job = primaryJob(jobIds, jobsMap);
  const { offsetMin, nextStopEta } = courierScheduleOffset(plan, courier.id, jobs);

  const now = Date.now();
  const done = stops.filter((s) => s.eta && new Date(s.eta).getTime() < now).length;
  const progress = stops.length ? Math.min(1, done / stops.length) : 0;
  const etaMin = nextStopEta ? Math.max(0, Math.round((new Date(nextStopEta).getTime() - now) / 60000)) : null;
  const dropEta = stops.length ? stops[stops.length - 1].eta : undefined;
  const isStat = job?.priority === "stat";

  return (
    <section className="inspector glass" data-testid="inspector">
      <div className="insp-id">
        <span className={`insp-dot ${isStat ? "stat" : ""}`} />
        <span className="insp-courier">{courier.name ?? courier.id}</span>
        {isStat && <span className="insp-badge">STAT</span>}
        <button className="insp-x" onClick={() => selectCourier(null)} aria-label="Clear">✕</button>
      </div>

      <div className="insp-route">
        {job ? `${job.origin.name ?? "Origin"} → ${job.destination.name ?? "Destination"}` : "Idle — no active job"}
      </div>
      {job && <div className="insp-sample">Sample {job.id}</div>}

      <div className="insp-metrics">
        <div className="im"><span className="im-num">{etaMin ?? "—"}</span><span className="im-lbl">ETA min</span></div>
        <div className="im"><span className="im-num lime">{offsetMin != null ? `${offsetMin >= 0 ? "+" : ""}${Math.round(offsetMin)}` : "—"}</span><span className="im-lbl">SLACK</span></div>
        <div className="im"><span className="im-num">{job?.cold_chain ? 4 : 18}°</span><span className="im-lbl">TEMP C</span></div>
        <div className="im"><span className="im-num">24</span><span className="im-lbl">SPEED km</span></div>
      </div>

      <div className="insp-chips">
        <span className="ichip on">GPS</span>
        <span className="ichip on">LTE</span>
        {job?.cold_chain && <span className="ichip cold">COLD 4°C</span>}
        <span className="ichip muted">{stops.length} STOPS</span>
      </div>

      <div className="insp-progress">
        <div className="ip-track"><div className="ip-fill" style={{ width: `${Math.round(progress * 100)}%` }} /></div>
        <div className="ip-meta">
          <span>PICKED UP</span>
          <span>DROP {dropEta ? fmtClock(dropEta).slice(0, 5) : "—"}</span>
        </div>
      </div>

      <div className="insp-actions">
        <button
          className="btn-yellow"
          data-testid="btn-call-courier"
          onClick={() =>
            postNotification({
              channel: "voice_call",
              to: courier.id,
              job_id: job?.id,
              message: `Calling ${courier.name ?? courier.id}${job ? ` re ${job.id}` : ""}.`,
            }).catch(() => {})
          }
        >
          CALL COURIER
        </button>
        <button
          className="btn-ghost-icon"
          title="View route"
          aria-label="View route"
          onClick={() => window.dispatchEvent(new CustomEvent("rlj:focus-courier", { detail: courier.id }))}
        >
          〰
        </button>
      </div>
    </section>
  );
}
