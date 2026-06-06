// Top floating row of the command center: PulseGo wordmark · verification badge ·
// theme toggle · account avatar. The avatar dropdown holds the account, the
// Demo-mode toggle, the Operational-Efficiency toggle, and the Scenario Actions.

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "../store";
import type { UseStatus } from "../hooks/useStatus";
import { seedDemo, clearDemo } from "../api";
import DemoControls from "./DemoControls";
import ThemeToggle from "./ThemeToggle";
import RouteSourceToggle from "./RouteSourceToggle";

interface Props {
  status: UseStatus;
  onOpenVerification: () => void;
  showEfficiency: boolean;
  onToggleEfficiency: () => void;
}

export default function TopBar({ status, onOpenVerification, showEfficiency, onToggleEfficiency }: Props) {
  const plan = useStore((s) => s.plan);
  const connected = useStore((s) => s.connected);
  const token = useStore((s) => s.token);
  const role = useStore((s) => s.role);
  const authUser = useStore((s) => s.authUser);
  const clearAuth = useStore((s) => s.clearAuth);
  const navigate = useNavigate();
  const [userOpen, setUserOpen] = useState(false);
  const [demoOn, setDemoOn] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const userRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (userRef.current && !userRef.current.contains(e.target as Node)) setUserOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  // Reflect whether a scenario is loaded so the toggle reads correctly on (re)connect.
  useEffect(() => {
    if ((plan?.routes?.length ?? 0) > 0) setDemoOn(true);
  }, [plan]);

  const summary = status.report?.summary;
  const mustPassGreen = summary?.must_pass_green ?? false;
  const mpVerified = summary?.must_pass_verified ?? 0;
  const mpTotal = summary?.must_pass_total ?? 0;
  const userLabel = authUser?.email ?? role ?? "signed in";
  const initial = (authUser?.email ?? role ?? "U").trim().charAt(0).toUpperCase();

  const handleLogout = () => {
    clearAuth();
    navigate("/");
  };

  const toggleDemo = async () => {
    if (demoBusy) return;
    const next = !demoOn;
    setDemoBusy(true);
    setDemoOn(next);
    try {
      await (next ? seedDemo() : clearDemo());
    } catch {
      setDemoOn(!next); // revert on failure
    } finally {
      setDemoBusy(false);
    }
  };

  const solveMs = plan?.objective?.solve_ms;

  return (
    <>
      {/* TOP-LEFT provenance pill — the "local" story at a glance */}
      <div className="prov-pill glass">
        <span className="prov-shield" aria-hidden>⛨</span>
        <div className="prov-lines">
          <div className="prov-line-1">Local · DGX Spark GB10</div>
          <div className="prov-line-2">
            <span className={`prov-dot ${connected ? "live" : "off"}`} />
            zero egress · {solveMs != null ? Math.round(solveMs) : "—"} ms re-plan
          </div>
        </div>
      </div>

      <nav className="nav-pill glass">
      <span className="nav-mark">Pulse<b>Go</b></span>

      <span className="nav-spacer" />

      {token && (
        <button
          type="button"
          className={`nav-demo ${demoOn ? "on" : ""}`}
          data-testid="demo-mode-primary"
          aria-pressed={demoOn}
          disabled={demoBusy}
          onClick={toggleDemo}
          title="Seed the judge demo scenario"
        >
          {demoBusy ? "Loading…" : demoOn ? "Demo live" : "Start demo"}
        </button>
      )}

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

      <RouteSourceToggle />
      <ThemeToggle />

      {token && (
        <div className="nav-user" ref={userRef}>
          <button
            type="button"
            className="nav-avatar"
            data-testid="user-menu"
            aria-haspopup="menu"
            aria-expanded={userOpen}
            aria-label="Account & controls"
            title={userLabel}
            onClick={() => setUserOpen((v) => !v)}
          >
            {initial}
          </button>
          {userOpen && (
            <div className="user-dropdown glass" role="menu">
              <div className="user-dd-email" title={userLabel}>{userLabel}</div>
              {role && <div className="user-dd-role">{role}</div>}

              <button
                type="button"
                className="user-dd-toggle"
                data-testid="demo-mode"
                role="menuitemcheckbox"
                aria-checked={demoOn}
                disabled={demoBusy}
                onClick={toggleDemo}
              >
                <span>Demo mode</span>
                <span className={`dd-switch ${demoOn ? "on" : ""}`}><i /></span>
              </button>

              <button
                type="button"
                className="user-dd-toggle"
                data-testid="toggle-efficiency"
                role="menuitemcheckbox"
                aria-checked={showEfficiency}
                onClick={onToggleEfficiency}
              >
                <span>Efficiency panel</span>
                <span className={`dd-switch ${showEfficiency ? "on" : ""}`}><i /></span>
              </button>

              <div className="user-dd-sep" />
              <div className="user-dd-section">Scenario actions</div>
              <DemoControls />

              <div className="user-dd-sep" />
              <button
                type="button"
                className="user-dd-item"
                data-testid="btn-logout"
                role="menuitem"
                onClick={handleLogout}
              >
                Log out
              </button>
            </div>
          )}
        </div>
      )}
      </nav>
    </>
  );
}
