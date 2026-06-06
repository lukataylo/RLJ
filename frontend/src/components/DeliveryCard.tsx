// One active delivery — a single-line row: vehicle icon · Origin → Destination · %
// with a hairline progress underline coloured by on-time status. Hovering (or
// selecting) the row reveals the vehicle type, stop count, places, and Redirect.
// Clicking selects the courier (highlights the route on the map).

import { useState } from "react";
import { VehicleIcon } from "./icons";
import { redirectCourier } from "../api";
import type { CourierVehicle, FleetAssessment, Priority } from "../types";

export type OnTimeKind = "ontime" | "risk" | "late";

export interface DeliveryItem {
  key: string;
  courierId: string;
  courierName: string;
  vehicle: CourierVehicle | undefined;
  jobId: string;
  priority: Priority;
  fromName: string;
  toName: string;
  /** 0..1 route progress for the assigned courier. */
  progress: number;
  onTime: OnTimeKind;
  dueTs: number | null;
  /** Active = this courier's current leg; upcoming = queued behind it. */
  phase: "active" | "upcoming";
  /** Hover detail. */
  vehicleLabel: string;
  routeStops: number;
  routePlaces: string[];
}

const PILL_LABEL: Record<OnTimeKind, string> = {
  ontime: "On time",
  risk: "At risk",
  late: "Late",
};

const ASSESS_LABEL: Record<FleetAssessment["status"], string> = {
  on_time: "ON TIME",
  reroute_suggested: "⤳ REROUTE",
  at_risk: "⚠ AT RISK",
};

export default function DeliveryCard({
  item,
  selected,
  assessment,
  onSelect,
  onClear,
}: {
  item: DeliveryItem;
  selected: boolean;
  assessment?: FleetAssessment;
  onSelect: () => void;
  onClear: () => void;
}) {
  const pct = Math.round(Math.max(0, Math.min(1, item.progress)) * 100);
  const isStat = item.priority === "stat";
  const [redirectState, setRedirectState] = useState<"idle" | "redirecting" | "done" | "error">("idle");
  const showAssessment = !!assessment && assessment.status !== "on_time";

  const doRedirect = async () => {
    if (redirectState === "redirecting") return;
    setRedirectState("redirecting");
    try {
      await redirectCourier(item.courierId);
      setRedirectState("done");
    } catch {
      setRedirectState("error");
    } finally {
      window.setTimeout(() => setRedirectState("idle"), 2200);
    }
  };

  const redirectLabel =
    redirectState === "redirecting" ? "redirecting…"
      : redirectState === "done" ? "✓ redirected"
        : redirectState === "error" ? "✕ failed"
          : "Redirect →";

  const hoverTitle = `${item.vehicleLabel} · ${item.routeStops} stops · ${item.routePlaces.join(" · ")}`;

  return (
    <div
      role="button"
      tabIndex={0}
      className={`dcard dc3 ${selected ? "selected" : ""} ${isStat ? "stat" : ""}`}
      data-testid="delivery-card"
      data-courier={item.courierId}
      aria-pressed={selected}
      title={hoverTitle}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <div className="dc3-line">
        <span className={`dc-veh status-${item.vehicle ?? "van"}`}>
          <VehicleIcon vehicle={item.vehicle} size={16} />
        </span>
        <span className="dc3-od">
          <span className="dc-from">{item.fromName}</span>
          <span className="dc3-arrow">→</span>
          <span className="dc-to">{item.toName}</span>
        </span>
        <span className={`dc3-dot ${item.onTime}`} title={PILL_LABEL[item.onTime]} />
        <span className="dc3-pct">{pct}%</span>
        {selected && (
          <button
            type="button"
            className="dc-x"
            aria-label="Clear selection"
            onClick={(e) => { e.stopPropagation(); onClear(); }}
          >
            ✕
          </button>
        )}
      </div>

      <div className="dc3-track">
        <i className={item.onTime} style={{ width: `${pct}%` }} />
      </div>

      {/* revealed on hover / when selected */}
      <div className="dc3-details">
        <span className="dc3-meta">
          {item.vehicleLabel} · {item.routeStops} stops · {item.routePlaces.join(" · ")}
        </span>
        {showAssessment && assessment && (
          <span className={`dc-assess-pill ${assessment.status}`} title={assessment.note}>
            {ASSESS_LABEL[assessment.status]}
          </span>
        )}
        <button
          type="button"
          className={`dc3-redirect ${redirectState}`}
          data-testid="btn-redirect"
          disabled={redirectState === "redirecting"}
          onClick={(e) => { e.stopPropagation(); void doRedirect(); }}
        >
          {redirectLabel}
        </button>
      </div>
    </div>
  );
}
