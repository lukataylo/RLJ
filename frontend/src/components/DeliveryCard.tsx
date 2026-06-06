// One ACTIVE delivery, rendered as a card in the right-column delivery list.
// Clicking the card selects its courier (which highlights the route on the map);
// the ✕ on a selected card clears the selection.

import { VehicleIcon } from "./icons";
import type { CourierVehicle, Priority } from "../types";

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

export default function DeliveryCard({
  item,
  selected,
  onSelect,
  onClear,
}: {
  item: DeliveryItem;
  selected: boolean;
  onSelect: () => void;
  onClear: () => void;
}) {
  const pct = Math.round(Math.max(0, Math.min(1, item.progress)) * 100);
  const isStat = item.priority === "stat";

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
          <div className="dc-sub">
            {item.courierName} · {item.jobId}
          </div>
        </div>

        <span className={`dc-dot ${item.priority}`} title={item.priority.toUpperCase()} />
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

      <div className="dc-prog-track">
        <div className="dc-prog-fill" style={{ width: `${pct}%` }} />
      </div>

      <div className="dc-foot">
        <span className={`dc-pill ${item.onTime}`}>{PILL_LABEL[item.onTime]}</span>
        <span className="dc-pct">{pct}%</span>
      </div>
    </div>
  );
}
