// Top floating row of the command center:
//   LEFT  — merged brand + local-RTX indicator (PulseGo · DGX Spark · re-plan ms)
//   CENTRE— Map ⇄ LiDAR toggle (rendered by App, sits on this same line)
//   RIGHT — theme toggle + account avatar (dropdown: Verification, Demo, Efficiency,
//           map-source toggle, Scenario actions, Log out)

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

  useEffect(() => {
    if ((plan?.routes?.length ?? 0) > 0) setDemoOn(true);
  }, [plan]);

  const summary = status.report?.summary;
  const mustPassGreen = summary?.must_pass_green ?? false;
  const mpVerified = summary?.must_pass_verified ?? 0;
  const mpTotal = summary?.must_pass_total ?? 0;
  const userLabel = authUser?.email ?? role ?? "signed in";
  const initial = (authUser?.email ?? role ?? "U").trim().charAt(0).toUpperCase();
  const solveMs = plan?.objective?.solve_ms;

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
      setDemoOn(!next);
    } finally {
      setDemoBusy(false);
    }
  };

  return (
    <>
      {/* LEFT — brand + local RTX indicator, merged */}
      <div className="brand-pill glass">
        <img src="/pulsego.svg" className="brand-mark" alt="" aria-hidden />
        <div className="brand-lines">
          <div className="brand-name">Pulse<b>Go</b></div>
          <div className="brand-sub">
            <span className={`prov-dot ${connected ? "live" : "off"}`} />
            Local · DGX Spark GB10 · {solveMs != null ? Math.round(solveMs) : "—"} ms
          </div>
        </div>
      </div>

      {/* RIGHT — theme toggle next to the account avatar */}
      <div className="account-pill glass" ref={userRef}>
        <ThemeToggle />
        {token && (
          <>
            <span className="account-sep" />
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
          </>
        )}
        {token && userOpen && (
          <div className="user-dropdown glass" role="menu">
            <div className="user-dd-email" title={userLabel}>{userLabel}</div>
            {role && <div className="user-dd-role">{role}</div>}

            <button
              type="button"
              className="user-dd-item between"
              data-testid="verification-badge"
              data-must-pass-green={String(mustPassGreen)}
              role="menuitem"
              onClick={() => { setUserOpen(false); onOpenVerification(); }}
            >
              <span>Verification</span>
              <span className={`dd-verify ${status.loaded ? (mustPassGreen ? "ok" : "fail") : ""}`}>
                {status.loaded ? `${mpVerified}/${mpTotal}` : "—/—"}
              </span>
            </button>

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
            <div className="user-dd-section">Map routing source</div>
            <div className="user-dd-rowctl"><RouteSourceToggle /></div>

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
    </>
  );
}
