// Presentation helpers shared by the active-delivery + jobs views.
import type { DeliveryJob, JobStatus, Priority } from "../types";

export function fmtTime(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? "—"
    : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function etaMinutes(iso?: string): string {
  if (!iso) return "";
  const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  if (isNaN(mins)) return "";
  return mins <= 0 ? "due" : `${mins} min`;
}

export const PRIORITY_LABEL: Record<Priority, string> = {
  stat: "STAT",
  urgent: "URGENT",
  routine: "ROUTINE",
};

export const PRIORITY_COLOR: Record<Priority, string> = {
  stat: "#ff5a52",
  urgent: "#f6c453",
  routine: "#9FB85A",
};

export const STATUS_LABEL: Record<JobStatus, string> = {
  new: "New",
  assigned: "Assigned",
  in_transit: "In transit",
  delivered: "Delivered",
  failed: "Failed",
};

export const STATUS_COLOR: Record<JobStatus, string> = {
  new: "rgba(255,246,238,0.55)",
  assigned: "#64D2FF",
  in_transit: "#34d399",
  delivered: "#34d399",
  failed: "#ff5a52",
};

export function jobTypeLabel(job: DeliveryJob): string {
  return job.type === "sample_pickup" ? "Sample pickup" : "Med delivery";
}
