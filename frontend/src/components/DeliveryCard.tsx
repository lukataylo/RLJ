// One ACTIVE delivery, rendered as a card in the right-column delivery list.
// Clicking the card selects its courier (which highlights the route on the map);
// the ✕ on a selected card clears the selection.

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
  /** Dropoff ETA / due epoch ms for sorting + sub-line, when known. */
  dueTs: number | null;
}

const PILL_LABEL: Record<OnTimeKind, string> = {
  ontime: "✓ ON TIME",
  risk: "⚠ AT RISK",
  late: "✕ LATE",
};

// Per-driver assessment pill copy (on_time is intentionally not shown).
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

  const [redirectState, setRedirectState] = useState<"idle" | "redirecting" | "done" | "error">(
    "idle",
  );

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
      // Briefly show the outcome, then return to idle so the button is reusable.
      window.setTimeout(() => setRedirectState("idle"), 2200);
    }
  };

  const redirectLabel =
    redirectState === "redirecting"
      ? "redirecting…"
      : redirectState === "done"
        ? "✓ redirected"
        : redirectState === "error"
          ? "✕ failed"
          : "Redirect →";

  return (
    <div
      role="button"
      tabIndex={0}
      className={`dcard ${selected ? "selected" : ""} ${isStat ? "stat" : ""}`}
      data-testid="delivery-card"
      data-courier={item.courierId}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <div className="dc-top">
        <span className={`dc-veh status-${item.vehicle ?? "van"}`}>
          <VehicleIcon vehicle={item.vehicle} size={22} />
        </span>

        <div className="dc-route">
          <div className="dc-od">
            <span className="dc-from">{item.fromName}</span>
            <span className="dc-arrow">→</span>
            <span className="dc-to">{item.toName}</span>
          </div>
        </div>

        {selected && (
          <button
            type="button"
            className="dc-x"
            aria-label="Clear selection"
            onClick={(e) => {
              e.stopPropagation();
              onClear();
            }}
          >
            ✕
          </button>
        )}
      </div>

      <div className="dc-prog-track grad">
        <div className="dc-prog-fill" style={{ width: `${pct}%` }} />
      </div>

      {showAssessment && assessment && (
        <div
          className={`dc-assess ${assessment.status}`}
          data-testid="assessment-pill"
          title={assessment.note}
        >
          <span className="dc-assess-pill">{ASSESS_LABEL[assessment.status]}</span>
          {assessment.note && <span className="dc-assess-note">{assessment.note}</span>}
        </div>
      )}

      <div className="dc-foot">
        <span className={`dc-pill ${item.onTime}`}>{PILL_LABEL[item.onTime]}</span>
        <div className="dc-foot-right">
          <span className="dc-pct">{pct}%</span>
          <button
            type="button"
            className={`dc-redirect ${redirectState}`}
            data-testid="btn-redirect"
            disabled={redirectState === "redirecting"}
            aria-busy={redirectState === "redirecting"}
            onClick={(e) => {
              e.stopPropagation();
              void doRedirect();
            }}
          >
            {redirectLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
