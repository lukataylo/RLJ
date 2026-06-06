// Top floating row of the command center:
//   - TOP-LEFT pill: local-compute provenance (DGX Spark, zero-egress, live re-plan ms)
//   - TOP-CENTER nav pill: ☰ menu (scenario actions) + PulseGo wordmark + tabs +
//     verification badge ("must-pass N/M", opens the Verification drawer) + live clock
//
// The ☰ menu hosts the demo Actions (Close road / Add STAT / Courier down /
// Re-optimize) via the existing DemoControls component.

import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import type { UseStatus } from "../hooks/useStatus";
import DemoControls from "./DemoControls";

interface Props {
  status: UseStatus;
  onOpenVerification: () => void;
}

const TABS = ["Live Map", "Fleet", "Routes", "Analytics", "Incidents"];

export default function TopBar({ status, onOpenVerification }: Props) {
  const connected = useStore((s) => s.connected);
  const plan = useStore((s) => s.plan);
  const [now, setNow] = useState(() => new Date());
  const [menuOpen, setMenuOpen] = useState(false);
  const [tab, setTab] = useState("Live Map");
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [menuOpen]);

  const summary = status.report?.summary;
  const mustPassGreen = summary?.must_pass_green ?? false;
  const mpVerified = summary?.must_pass_verified ?? 0;
  const mpTotal = summary?.must_pass_total ?? 0;
  const solveMs = plan?.objective?.solve_ms;
  const clock = now.toLocaleTimeString("en-GB", { hour12: false });

  return (
    <>
      {/* TOP-LEFT provenance pill */}
      <div className="prov-pill glass">
        <span className="prov-shield" aria-hidden>⛨</span>
        <div className="prov-lines">
          <div className="prov-line-1">RUNNING LOCAL · DGX SPARK GB10</div>
          <div className="prov-line-2">
            <span className={`prov-dot ${connected ? "live" : "off"}`} />
            ZERO EGRESS · {solveMs != null ? Math.round(solveMs) : "—"} ms re-plan
          </div>
        </div>
      </div>

      {/* TOP-CENTER nav pill */}
      <nav className="nav-pill glass">
        <div className="nav-menu-wrap" ref={menuRef}>
          <button
            type="button"
            className={`nav-burger ${menuOpen ? "open" : ""}`}
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="Scenario menu"
          >
            ☰
          </button>
          {menuOpen && (
            <div className="nav-menu glass">
              <div className="nav-menu-title">Scenario Actions</div>
              <DemoControls />
            </div>
          )}
        </div>

        <span className="nav-mark">PulseGo</span>

        <div className="nav-tabs">
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              className={`nav-tab ${tab === t ? "active" : ""}`}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </div>

        <button
          type="button"
          className={`nav-verify ${status.loaded ? (mustPassGreen ? "ok" : "fail") : "unknown"}`}
          data-testid="verification-badge"
          data-must-pass-green={String(mustPassGreen)}
          onClick={onOpenVerification}
          title="Open verification panel"
        >
          <span className="nav-verify-dot" />
          {status.loaded ? `${mpVerified}/${mpTotal}` : "—/—"}
        </button>

        <span className="nav-clock">{clock}</span>
      </nav>
    </>
  );
}
