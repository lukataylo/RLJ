// RIGHT-COLUMN ACTIVE DELIVERY LIST (replaces the old centre/bottom ticket).
// One card per active delivery (each served job in plan.routes[].stops), with a
// vehicle icon, FROM → TO, a route-progress bar, an on-time pill and a priority
// dot. Clicking a card selects its courier — which highlights the route on the map.

import { useMemo } from "react";
import { useStore } from "../store";
import DeliveryCard, { type DeliveryItem, type OnTimeKind } from "./DeliveryCard";
import type { Priority, Stop } from "../types";

const PRIORITY_ORDER: Record<Priority, number> = { stat: 0, urgent: 1, routine: 2 };
const RISK_WINDOW_MIN = 5;

/** Classify on-time status from dropoff ETA vs the clinical due_by (+ window_met). */
function classifyOnTime(
  etaIso: string | undefined,
  dueIso: string | undefined,
  windowMet: boolean | undefined,
): OnTimeKind {
  if (windowMet === false) return "late";
  if (etaIso && dueIso) {
    const slackMin = (new Date(dueIso).getTime() - new Date(etaIso).getTime()) / 60000;
    if (Number.isFinite(slackMin)) {
      if (slackMin < 0) return "late";
      if (slackMin <= RISK_WINDOW_MIN) return "risk";
      return "ontime";
    }
  }
  return "ontime";
}

export default function DeliveryList() {
  const jobsMap = useStore((s) => s.jobs);
  const couriersMap = useStore((s) => s.couriers);
  const plan = useStore((s) => s.plan);
  const selectedId = useStore((s) => s.selectedCourierId);
  const selectCourier = useStore((s) => s.selectCourier);

  const items = useMemo<DeliveryItem[]>(() => {
    const out: DeliveryItem[] = [];
    const now = Date.now();
    for (const route of plan?.routes ?? []) {
      const courier = couriersMap[route.courier_id];
      const stops = [...(route.stops ?? [])].sort((a, b) => a.sequence - b.sequence);
      if (!stops.length) continue;

      // Route-level progress: stops whose ETA is already in the past / total.
      const done = stops.filter((s) => s.eta && new Date(s.eta).getTime() < now).length;
      const progress = stops.length ? Math.min(1, done / stops.length) : 0;

      const seen = new Set<string>();
      for (const stop of stops) {
        if (seen.has(stop.job_id)) continue;
        seen.add(stop.job_id);
        const job = jobsMap[stop.job_id];
        if (!job || job.status === "delivered" || job.status === "failed") continue;

        const drop: Stop | undefined =
          stops.find((s) => s.job_id === stop.job_id && s.kind === "dropoff") ??
          [...stops].reverse().find((s) => s.job_id === stop.job_id);
        const due = job.time_window?.due_by;
        const dueTs = due ? new Date(due).getTime() : null;

        out.push({
          key: `${route.courier_id}:${job.id}`,
          courierId: route.courier_id,
          courierName: courier?.name ?? courier?.id ?? route.courier_id,
          vehicle: courier?.vehicle_type,
          jobId: job.id,
          priority: job.priority,
          fromName: job.origin.name ?? "Origin",
          toName: job.destination.name ?? "Destination",
          progress,
          onTime: classifyOnTime(drop?.eta, due, drop?.window_met),
          dueTs: dueTs != null && Number.isFinite(dueTs) ? dueTs : null,
        });
      }
    }

    // STAT first, then soonest due (unknown due sinks to the bottom).
    out.sort((a, b) => {
      const p = PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority];
      if (p !== 0) return p;
      const da = a.dueTs ?? Number.POSITIVE_INFINITY;
      const db = b.dueTs ?? Number.POSITIVE_INFINITY;
      return da - db;
    });
    return out;
  }, [jobsMap, couriersMap, plan]);

  return (
    <section className="delivery-panel glass">
      <div className="dl-cap">
        <span>ACTIVE DELIVERIES</span>
        <span className="dl-count">{items.length}</span>
      </div>
      <div className="dl-scroll" data-testid="delivery-list">
        {items.length === 0 && <div className="dl-empty">No active deliveries.</div>}
        {items.map((it) => (
          <DeliveryCard
            key={it.key}
            item={it}
            selected={selectedId === it.courierId}
            onSelect={() => selectCourier(selectedId === it.courierId ? null : it.courierId)}
            onClear={() => selectCourier(null)}
          />
        ))}
      </div>
    </section>
  );
}
