// Formatting + metric derivation helpers.

import type { Courier, DeliveryJob, Plan, MetricSample } from "../types";

export function fmtInt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return Math.round(n).toLocaleString("en-GB");
}

export function fmtMs(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${Math.round(n).toLocaleString("en-GB")}`;
}

export function fmtSigned(n: number | null | undefined, unit = ""): string {
  if (n == null || Number.isNaN(n)) return "—";
  const r = Math.round(n);
  const sign = r > 0 ? "+" : "";
  return `${sign}${r}${unit}`;
}

export function fmtClock(ts: string | number | undefined): string {
  if (ts == null) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("en-GB", { hour12: false });
}

export function relativeAge(iso: string | undefined): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const secs = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.round(mins / 60)}h ago`;
}

/** Count of STAT jobs still in flight (not delivered/failed). */
export function statInFlight(jobs: DeliveryJob[]): number {
  return jobs.filter(
    (j) => j.priority === "stat" && j.status !== "delivered" && j.status !== "failed",
  ).length;
}

/** Count of couriers actively en route. */
export function activeCouriers(couriers: Courier[]): number {
  return couriers.filter((c) => c.status === "enroute").length;
}

/**
 * Average ETA slack (minutes) across dropoff stops that have a clinical window:
 * positive = ahead of deadline, negative = late. Returns null if none.
 */
export function avgEtaSlackMin(plan: Plan | null, jobs: DeliveryJob[]): number | null {
  if (!plan) return null;
  const jobById = new Map(jobs.map((j) => [j.id, j]));
  const slacks: number[] = [];
  for (const route of plan.routes ?? []) {
    for (const stop of route.stops ?? []) {
      if (stop.kind !== "dropoff" || !stop.eta) continue;
      const job = jobById.get(stop.job_id);
      const due = job?.time_window?.due_by;
      if (!due) continue;
      const slack = (new Date(due).getTime() - new Date(stop.eta).getTime()) / 60000;
      if (!Number.isNaN(slack)) slacks.push(slack);
    }
  }
  if (!slacks.length) return null;
  return slacks.reduce((a, b) => a + b, 0) / slacks.length;
}

/** Sample current operational metrics for the sparkline history. */
export function sampleMetrics(
  plan: Plan | null,
  jobs: DeliveryJob[],
  couriers: Courier[],
): MetricSample {
  const obj = plan?.objective;
  const windowsMet = obj?.windows_met ?? 0;
  const windowsTotal = obj?.windows_total ?? 0;
  return {
    ts: Date.now(),
    windowsMet,
    windowsTotal,
    windowPct: windowsTotal ? (windowsMet / windowsTotal) * 100 : 0,
    solveMs: obj?.solve_ms ?? null,
    totalTimeMin: obj?.total_time_s != null ? obj.total_time_s / 60 : null,
    activeCouriers: activeCouriers(couriers),
    statInFlight: statInFlight(jobs),
    onTime: windowsMet,
  };
}

/**
 * Schedule offset (minutes) for a courier's route: slack of the next pending
 * dropoff with a clinical window. Positive = ahead, negative = behind.
 */
export function courierScheduleOffset(
  plan: Plan | null,
  courierId: string,
  jobs: DeliveryJob[],
): { offsetMin: number | null; nextStopEta: string | null; nextStopName: string | null } {
  const route = plan?.routes?.find((r) => r.courier_id === courierId);
  if (!route) return { offsetMin: null, nextStopEta: null, nextStopName: null };
  const jobById = new Map(jobs.map((j) => [j.id, j]));
  const now = Date.now();
  const upcoming = (route.stops ?? [])
    .filter((s) => s.eta)
    .sort((a, b) => new Date(a.eta!).getTime() - new Date(b.eta!).getTime());
  const next = upcoming.find((s) => new Date(s.eta!).getTime() >= now) ?? upcoming[0];
  if (!next) return { offsetMin: null, nextStopEta: null, nextStopName: null };
  const due = jobById.get(next.job_id)?.time_window?.due_by;
  const offsetMin =
    next.kind === "dropoff" && due
      ? (new Date(due).getTime() - new Date(next.eta!).getTime()) / 60000
      : null;
  return {
    offsetMin,
    nextStopEta: next.eta ?? null,
    nextStopName: next.location?.name ?? `${next.kind} ${next.job_id}`,
  };
}
