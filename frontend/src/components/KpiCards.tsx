// Glassmorphic KPI cards (the big-number treatment), each with a sparkline and a
// verification badge bound to a claim id. Required data-testids:
//   kpi-windows, kpi-solver, kpi-solve-ms.

import { useMemo } from "react";
import { useStore } from "../store";
import type { UseStatus } from "../hooks/useStatus";
import { HEX } from "../lib/palette";
import { avgEtaSlackMin, fmtInt, fmtMs, fmtSigned, statInFlight, activeCouriers } from "../lib/format";
import Sparkline from "./Sparkline";
import VerifiedBadge from "./VerifiedBadge";

interface CardProps {
  label: string;
  value: React.ReactNode;
  unit?: string;
  spark: number[];
  color: string;
  claimId: string;
  status: UseStatus;
  testid?: string;
}

function KpiCard({ label, value, unit, spark, color, claimId, status, testid }: CardProps) {
  const claim = status.claimOf(claimId);
  return (
    <div className="kpi" data-testid={testid}>
      <div className="kpi-head">
        <span className="kpi-label">{label}</span>
        <VerifiedBadge
          status={status.statusOf(claimId)}
          claimId={claimId}
          statement={claim?.statement}
        />
      </div>
      <div className="kpi-value">
        {value}
        {unit && <span className="kpi-unit">{unit}</span>}
      </div>
      <Sparkline values={spark} width={150} height={36} color={color} />
    </div>
  );
}

export default function KpiCards({ status }: { status: UseStatus }) {
  const plan = useStore((s) => s.plan);
  const history = useStore((s) => s.history);
  const jobsMap = useStore((s) => s.jobs);
  const couriersMap = useStore((s) => s.couriers);

  const jobs = useMemo(() => Object.values(jobsMap), [jobsMap]);
  const couriers = useMemo(() => Object.values(couriersMap), [couriersMap]);

  const obj = plan?.objective;
  const windowsMet = obj?.windows_met ?? 0;
  const windowsTotal = obj?.windows_total ?? 0;
  const slack = avgEtaSlackMin(plan, jobs);
  const stat = statInFlight(jobs);
  const active = activeCouriers(couriers);

  const statHist = history.map((h) => h.statInFlight);
  const onTimeHist = history.map((h) => h.onTime);
  const slackHist = history.map((h) => (h.windowPct ? h.windowPct / 10 : 0));
  const solveHist = history.map((h) => h.solveMs ?? 0);
  const activeHist = history.map((h) => h.activeCouriers);

  return (
    <div className="kpi-row">
      <KpiCard
        label="STAT in flight"
        value={fmtInt(stat)}
        spark={statHist}
        color={HEX.red}
        claimId="stat-compliance"
        status={status}
      />
      <KpiCard
        label="Samples on-time today"
        value={
          <>
            {fmtInt(windowsMet)}
            <span className="kpi-frac">/{fmtInt(windowsTotal)}</span>
          </>
        }
        spark={onTimeHist}
        color={HEX.green}
        claimId="stat-compliance"
        status={status}
        testid="kpi-windows"
      />
      <KpiCard
        label="Active solver"
        value={obj?.solver ?? "—"}
        spark={onTimeHist}
        color={HEX.cyan}
        claimId="beats-baseline"
        status={status}
        testid="kpi-solver"
      />
      <KpiCard
        label="Re-plan time"
        value={fmtMs(obj?.solve_ms)}
        unit="ms"
        spark={solveHist}
        color={HEX.amber}
        claimId="realtime-replan"
        status={status}
        testid="kpi-solve-ms"
      />
      <KpiCard
        label="Avg ETA slack"
        value={fmtSigned(slack)}
        unit="min"
        spark={slackHist}
        color={HEX.blue}
        claimId="data-demand-valid"
        status={status}
      />
      <KpiCard
        label="Active couriers"
        value={fmtInt(active)}
        spark={activeHist}
        color={HEX.green}
        claimId="eta-sane"
        status={status}
      />
    </div>
  );
}
