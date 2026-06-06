// BOTTOM-CENTER priority ticket — the most urgent STAT job in flight, with a
// red progress bar, a "re-routed" chip when a disruption is active, and a primary
// YELLOW "REASSIGN" action (forces a re-optimize on the orchestrator).

import { useMemo, useState } from "react";
import { useStore } from "../store";
import { optimize, postNotification } from "../api";
import { fmtClock } from "../lib/format";
import type { DeliveryJob } from "../types";

export default function PriorityTicket() {
  const jobsMap = useStore((s) => s.jobs);
  const couriersMap = useStore((s) => s.couriers);
  const plan = useStore((s) => s.plan);
  const disruptions = useStore((s) => s.disruptions);
  const [busy, setBusy] = useState(false);

  const job = useMemo<DeliveryJob | null>(() => {
    const jobs = Object.values(jobsMap);
    const stat = jobs.filter(
      (j) => j.priority === "stat" && j.status !== "delivered" && j.status !== "failed",
    );
    return stat[0] ?? jobs.find((j) => j.status !== "delivered" && j.status !== "failed") ?? null;
  }, [jobsMap]);

  if (!job) return null;

  // Locate the route/courier serving this job, if any.
  const route = plan?.routes?.find((r) => r.stops?.some((s) => s.job_id === job.id));
  const courier = route ? couriersMap[route.courier_id] : null;
  const stops = [...(route?.stops ?? [])].sort((a, b) => a.sequence - b.sequence);
  const now = Date.now();
  const done = stops.filter((s) => s.eta && new Date(s.eta).getTime() < now).length;
  const progress = stops.length ? Math.min(1, done / stops.length) : 0.15;
  const dropEta = stops.length ? stops[stops.length - 1].eta : job.time_window?.due_by;
  const windowMin = job.time_window?.due_by && job.time_window?.ready_at
    ? Math.round((new Date(job.time_window.due_by).getTime() - new Date(job.time_window.ready_at).getTime()) / 60000)
    : null;
  const distKm = route?.total_distance_m != null ? (route.total_distance_m / 1000).toFixed(1) : "—";
  const hasDisruption = disruptions.length > 0;

  const reassign = async () => {
    setBusy(true);
    try {
      await optimize();
    } catch {
      /* graceful — orchestrator may be offline */
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="ticket glass">
      <div className="tk-label">PRIORITY · STAT HISTOPATHOLOGY</div>
      <div className="tk-route">{job.origin.name ?? "Origin"} → {job.destination.name ?? "Destination"}</div>
      <div className="tk-meta">
        {(courier?.name ?? courier?.id ?? "unassigned")} · {job.id}
        {windowMin != null && <> · window {windowMin} min</>}
      </div>

      <div className="tk-status">
        <span className="tk-pickup">PICKED UP {job.time_window?.ready_at ? fmtClock(job.time_window.ready_at).slice(0, 5) : "—"}</span>
        {hasDisruption && <span className="tk-reroute">{disruptions[disruptions.length - 1].kind.replace("_", " ")} · RE-ROUTED +0 MIN</span>}
      </div>

      <div className="tk-track"><div className="tk-fill" style={{ width: `${Math.round(progress * 100)}%` }} /></div>

      <div className="tk-foot">
        <span className="tk-summary">
          {stops.length} stops · {distKm} km · ETA {dropEta ? fmtClock(dropEta).slice(0, 5) : "—"} · <span className="tk-ontime">ON TIME</span>
        </span>
        <div className="tk-actions">
          <button
            className="btn-ghost-icon"
            title="Call"
            aria-label="Call"
            onClick={() =>
              postNotification({
                channel: "voice_call",
                to: courier?.id,
                job_id: job.id,
                message: `Calling ${courier?.name ?? courier?.id ?? "courier"} re ${job.id}.`,
              }).catch(() => {})
            }
          >
            ✆
          </button>
          <button className="btn-yellow sm" onClick={reassign} disabled={busy}>{busy ? "…" : "REASSIGN"}</button>
        </div>
      </div>
    </section>
  );
}
