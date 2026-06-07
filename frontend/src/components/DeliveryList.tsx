// RIGHT-COLUMN delivery sidebar — tabbed Active | Upcoming. Each row is a single
// line (vehicle icon · Origin → Destination · %) with a progress underline; hover
// reveals vehicle/stops/places. "Active" = each courier's current leg; "Upcoming"
// = the jobs queued behind it. Clicking a card selects its courier on the map.

import { useMemo, useState } from "react";
import { useStore } from "../store";
import DeliveryCard, { type DeliveryItem, type OnTimeKind } from "./DeliveryCard";
import type { CourierVehicle, Priority, Stop } from "../types";

const PRIORITY_ORDER: Record<Priority, number> = { stat: 0, urgent: 1, routine: 2 };
const RISK_WINDOW_MIN = 5;
const VEHICLE_LABEL: Record<string, string> = { van: "Van", scooter: "Scooter", bike: "Bike" };

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
  const fleetAssessments = useStore((s) => s.fleetAssessments);
  const [tab, setTab] = useState<"active" | "upcoming">("active");

  const items = useMemo<DeliveryItem[]>(() => {
    const out: DeliveryItem[] = [];
    const now = Date.now();
    for (const route of plan?.routes ?? []) {
      const courier = couriersMap[route.courier_id];
      const stops = [...(route.stops ?? [])].sort((a, b) => a.sequence - b.sequence);
      if (!stops.length) continue;

      // Route-level fallback progress (stops whose ETA is already in the past).
      const done = stops.filter((s) => s.eta && new Date(s.eta).getTime() < now).length;
      const routeProgress = stops.length ? Math.min(1, done / stops.length) : 0;

      // Ordered unique place names along this courier's route (for the hover detail).
      const routePlaces: string[] = [];
      for (const s of stops) {
        const j = jobsMap[s.job_id];
        const nm = (s.kind === "pickup" ? j?.origin.name : j?.destination.name) ?? undefined;
        if (nm && !routePlaces.includes(nm)) routePlaces.push(nm);
      }
      const vehicle = courier?.vehicle_type as CourierVehicle | undefined;
      const vehicleLabel = VEHICLE_LABEL[vehicle ?? "van"] ?? "Van";

      let firstForCourier = true;
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
        // Realistic progress = elapsed through the clinical window (ready→due), so it
        // reads as "in flight", not stuck at 100%. Falls back to route-stop progress.
        const readyTs = job.time_window?.ready_at ? new Date(job.time_window.ready_at).getTime() : null;
        const progress =
          readyTs != null && dueTs != null && dueTs > readyTs
            ? Math.max(0.02, Math.min(0.98, (now - readyTs) / (dueTs - readyTs)))
            : routeProgress;

        out.push({
          key: `${route.courier_id}:${job.id}`,
          courierId: route.courier_id,
          courierName: courier?.name ?? courier?.id ?? route.courier_id,
          vehicle,
          jobId: job.id,
          priority: job.priority,
          fromName: job.origin.name ?? "Origin",
          toName: job.destination.name ?? "Destination",
          progress,
          onTime: classifyOnTime(drop?.eta, due, drop?.window_met),
          dueTs: dueTs != null && Number.isFinite(dueTs) ? dueTs : null,
          phase: firstForCourier ? "active" : "upcoming",
          vehicleLabel,
          routeStops: stops.length,
          routePlaces,
        });
        firstForCourier = false;
      }
    }

    out.sort((a, b) => {
      const p = PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority];
      if (p !== 0) return p;
      const da = a.dueTs ?? Number.POSITIVE_INFINITY;
      const db = b.dueTs ?? Number.POSITIVE_INFINITY;
      return da - db;
    });
    return out;
  }, [jobsMap, couriersMap, plan]);

  const active = items.filter((i) => i.phase === "active");
  const upcoming = items.filter((i) => i.phase === "upcoming");
  const shown = tab === "active" ? active : upcoming;

  return (
    <div className="delivery-panel">
      <div className="dl-tabs" role="tablist">
        <button
          role="tab"
          aria-selected={tab === "active"}
          className={`dl-tab ${tab === "active" ? "on" : ""}`}
          data-testid="dl-tab-active"
          onClick={() => setTab("active")}
        >
          Active <span className="dl-tab-n">{active.length}</span>
        </button>
        <button
          role="tab"
          aria-selected={tab === "upcoming"}
          className={`dl-tab ${tab === "upcoming" ? "on" : ""}`}
          data-testid="dl-tab-upcoming"
          onClick={() => setTab("upcoming")}
        >
          Upcoming <span className="dl-tab-n">{upcoming.length}</span>
        </button>
      </div>

      <div className="delivery-stack" data-testid="delivery-list">
        {shown.length === 0 && <div className="dl-empty glass">No {tab} deliveries.</div>}
        {shown.map((it) => (
          <DeliveryCard
            key={it.key}
            item={it}
            selected={selectedId === it.courierId}
            assessment={fleetAssessments[it.courierId]}
            onSelect={() => selectCourier(selectedId === it.courierId ? null : it.courierId)}
            onClear={() => selectCourier(null)}
          />
        ))}
      </div>
    </div>
  );
}
