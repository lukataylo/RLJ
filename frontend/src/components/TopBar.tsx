// Top floating row of the command center:
//   - TOP-LEFT pill: local-compute provenance (DGX Spark, zero-egress, live re-plan ms)
//   - TOP-CENTER nav pill: ☰ scenario menu + PulseGo wordmark + the single live view +
//     Demo-mode button + verification badge + clock + theme toggle + account avatar.
//
// The ☰ menu hosts the working demo Actions (Close road / Add STAT / Courier down /
// Re-optimize) via DemoControls. Non-functional nav tabs were removed.

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "../store";
import type { UseStatus } from "../hooks/useStatus";
import { seedDemo } from "../api";
import DemoControls from "./DemoControls";
import ThemeToggle from "./ThemeToggle";

interface Props {
  status: UseStatus;
  onOpenVerification: () => void;
}

export default function TopBar({ status, onOpenVerification }: Props) {
  const connected = useStore((s) => s.connected);
  const plan = useStore((s) => s.plan);
  const token = useStore((s) => s.token);
  const role = useStore((s) => s.role);
  const authUser = useStore((s) => s.authUser);
  const clearAuth = useStore((s) => s.clearAuth);
  const navigate = useNavigate();
  const [now, setNow] = useState(() => new Date());
  const [menuOpen, setMenuOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const userRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  // Close popovers on outside click.
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
      if (userRef.current && !userRef.current.contains(e.target as Node)) setUserOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const summary = status.report?.summary;
  const mustPassGreen = summary?.must_pass_green ?? false;
  const mpVerified = summary?.must_pass_verified ?? 0;
  const mpTotal = summary?.must_pass_total ?? 0;
  const solveMs = plan?.objective?.solve_ms;
  const clock = now.toLocaleTimeString("en-GB", { hour12: false });
  const userLabel = authUser?.email ?? role ?? "signed in";
  const initial = (authUser?.email ?? role ?? "U").trim().charAt(0).toUpperCase();

  const handleLogout = () => {
    clearAuth();
    navigate("/");
  };

  const runDemo = async () => {
    if (seeding) return;
    setSeeding(true);
    try {
      await seedDemo();
    } catch {
      /* surfaced via the agent log / no-op on failure */
    } finally {
      setSeeding(false);
    }
  };

  return (
    <>
      {/* TOP-LEFT provenance pill — trimmed to the essentials */}
      <div className="prov-pill glass">
        <span className="prov-shield" aria-hidden>⛨</span>
        <div className="prov-lines">
          <div className="prov-line-1">Local · DGX Spark GB10</div>
          <div className="prov-line-2">
            <span className={`prov-dot ${connected ? "live" : "off"}`} />
            {solveMs != null ? Math.round(solveMs) : "—"} ms re-plan
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

        <span className="nav-mark">Pulse<b>Go</b></span>

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

        {/* Demo toggle — subtle, tucked beside the clock (loads a live scenario). */}
        <button
          type="button"
          className="nav-demo-sub"
          data-testid="demo-mode"
          onClick={runDemo}
          disabled={seeding}
          title="Load a live demo scenario (couriers, jobs, routes)"
        >
          {seeding ? "loading…" : "demo"}
        </button>

        <ThemeToggle />

        {token && (
          <div className="nav-user" ref={userRef}>
            <button
              type="button"
              className="nav-avatar"
              data-testid="user-menu"
              aria-haspopup="menu"
              aria-expanded={userOpen}
              aria-label="Account"
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
