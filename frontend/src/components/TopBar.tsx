// Command-center header: brand, live-link status, planning clock, and the
// overall verification badge that opens the Verification drawer.

import { useStore } from "../store";
import type { UseStatus } from "../hooks/useStatus";
import { fmtClock, relativeAge } from "../lib/format";

interface Props {
  status: UseStatus;
  onOpenVerification: () => void;
}

export default function TopBar({ status, onOpenVerification }: Props) {
  const connected = useStore((s) => s.connected);
  const plan = useStore((s) => s.plan);
  const summary = status.report?.summary;

  const mustPassGreen = summary?.must_pass_green ?? false;
  const verified = summary?.verified ?? 0;
  const total = summary?.total ?? 0;

  return (
    <header className="topbar">
      <div className="tb-brand">
        <div className="tb-mark">RLJ</div>
        <div className="tb-titles">
          <div className="tb-title">TRAFFIC MANAGEMENT</div>
          <div className="tb-sub">London Medical Courier · DGX Spark Command Center</div>
        </div>
      </div>

      <div className="tb-right">
        <div className="tb-clock">
          <span className="tb-clock-label">PLAN GENERATED</span>
          <span className="tb-clock-val">
            {plan?.generated_at ? `${fmtClock(plan.generated_at)} · ${relativeAge(plan.generated_at)}` : "—"}
          </span>
        </div>

        <button
          className={`tb-verify ${status.loaded ? (mustPassGreen ? "ok" : "fail") : "unknown"}`}
          data-testid="verification-badge"
          data-must-pass-green={String(mustPassGreen)}
          onClick={onOpenVerification}
          title="Open verification panel"
        >
          <span className="tb-verify-dot" />
          <span className="tb-verify-main">
            {status.loaded ? `Verified ${verified}/${total}` : "Verification —"}
          </span>
          <span className="tb-verify-sub">
            must-pass {status.loaded ? (mustPassGreen ? "GREEN" : "RED") : "—"}
          </span>
        </button>

        <div className={`tb-link ${connected ? "up" : "down"}`}>
          <span className="tb-link-dot" />
          {connected ? "LIVE" : "OFFLINE"}
        </div>
      </div>
    </header>
  );
}
