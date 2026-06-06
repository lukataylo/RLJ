// Small presentation helpers shared across screens.

import type { DeliveryJob, JobStatus, Priority } from "./types";

export function fmtTime(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function fmtDateTime(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString([], {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function etaMinutes(iso?: string): string {
  if (!iso) return "";
  const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  if (isNaN(mins)) return "";
  if (mins <= 0) return "due";
  return `${mins} min`;
}

export const PRIORITY_LABEL: Record<Priority, string> = {
  stat: "STAT",
  urgent: "URGENT",
  routine: "ROUTINE",
};

export const STATUS_LABEL: Record<JobStatus, string> = {
  new: "New",
  assigned: "Assigned",
  in_transit: "In transit",
  delivered: "Delivered",
  failed: "Failed",
};

export function jobTitle(job: DeliveryJob): string {
  const from = job.origin.name || "Pickup";
  const to = job.destination.name || "Dropoff";
  return `${from} → ${to}`;
}

export function jobTypeLabel(job: DeliveryJob): string {
  return job.type === "sample_pickup" ? "Sample pickup" : "Med delivery";
}

export const UPCOMING: JobStatus[] = ["new", "assigned", "in_transit"];
export const PAST: JobStatus[] = ["delivered", "failed"];
