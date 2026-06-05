// Slide-in drawer listing every verification claim grouped by category, with its
// status and statement. Driven by the same /status.json poll as the badges.

import { useMemo } from "react";
import type { UseStatus } from "../hooks/useStatus";
import type { VerificationClaim } from "../types";
import VerifiedBadge from "./VerifiedBadge";
import { relativeAge } from "../lib/format";

interface Props {
  status: UseStatus;
  open: boolean;
  onClose: () => void;
}

const CATEGORY_ORDER = ["impact", "performance", "contract", "data", "e2e"];

function title(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export default function VerificationPanel({ status, open, onClose }: Props) {
  const grouped = useMemo(() => {
    const map = new Map<string, VerificationClaim[]>();
    for (const c of status.report?.claims ?? []) {
      if (!map.has(c.category)) map.set(c.category, []);
      map.get(c.category)!.push(c);
    }
    const cats = [...map.keys()].sort(
      (a, b) => (CATEGORY_ORDER.indexOf(a) + 99 * (CATEGORY_ORDER.indexOf(a) < 0 ? 1 : 0)) -
        (CATEGORY_ORDER.indexOf(b) + 99 * (CATEGORY_ORDER.indexOf(b) < 0 ? 1 : 0)),
    );
    return cats.map((cat) => ({ cat, claims: map.get(cat)! }));
  }, [status.report]);

  const summary = status.report?.summary;

  return (
    <>
      <div className={`vp-scrim ${open ? "open" : ""}`} onClick={onClose} />
      <aside className={`vp-drawer ${open ? "open" : ""}`} data-testid="verification-panel">
        <header className="vp-head">
          <div>
            <div className="vp-title">Verification</div>
            <div className="vp-sub">
              {status.report
                ? `${summary?.verified ?? 0} verified · ${summary?.failing ?? 0} failing · ${summary?.unverified ?? 0} unverified · updated ${relativeAge(status.report.generated_at)}`
                : "No status.json found — run verification/run.py to populate."}
            </div>
          </div>
          <button className="vp-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        {summary && (
          <div className={`vp-banner ${summary.must_pass_green ? "ok" : "fail"}`}>
            Must-pass gate:{" "}
            <strong>{summary.must_pass_green ? "GREEN" : "RED"}</strong> ·{" "}
            {summary.must_pass_verified}/{summary.must_pass_total} required claims verified
          </div>
        )}

        <div className="vp-body">
          {grouped.length === 0 && (
            <div className="vp-empty">No claims to display.</div>
          )}
          {grouped.map(({ cat, claims }) => (
            <section key={cat} className="vp-group">
              <div className="vp-group-head">
                <span>{title(cat)}</span>
                <span className="vp-group-count">{claims.length}</span>
              </div>
              {claims.map((c) => (
                <div key={c.id} className="vp-claim">
                  <VerifiedBadge
                    status={c.status}
                    claimId={c.id}
                    statement={c.statement}
                    showWord
                  />
                  <div className="vp-claim-body">
                    <div className="vp-claim-statement">{c.statement}</div>
                    <div className="vp-claim-meta">
                      <code>{c.id}</code>
                      {c.must_pass && <span className="vp-mustpass">must-pass</span>}
                      {c.duration_s != null && <span>{c.duration_s.toFixed(2)}s</span>}
                    </div>
                  </div>
                </div>
              ))}
            </section>
          ))}
        </div>
      </aside>
    </>
  );
}
