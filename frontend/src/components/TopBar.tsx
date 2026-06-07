// Top floating row of the command center:
//   LEFT  — merged brand + local-RTX indicator (PulseGo · DGX Spark · re-plan ms)
//   CENTRE— Map ⇄ LiDAR toggle (rendered by App, sits on this same line)
//   RIGHT — theme toggle + account avatar (dropdown: Verification, Demo, Efficiency,
//           map-source toggle, Scenario actions, Log out)

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "../store";
import type { UseStatus } from "../hooks/useStatus";
import { seedDemo, clearDemo, getHealth, injectBridgeClosure, setLlmEnabled } from "../api";
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
  // Whether a cloud model is active. Defaults false so the on-prem DGX Spark indicator
  // shows on localhost / local model and is hidden only once we learn it's a cloud model.
  const [cloudModel, setCloudModel] = useState(false);
  // On-prem model toggle (Nemotron) reflected from /healthz.
  const [llmEnabled, setLlmEnabledState] = useState(true);
  const [llmLabel, setLlmLabel] = useState("Nemotron");
  const userRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (userRef.current && !userRef.current.contains(e.target as Node)) setUserOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  // Keep the Demo-mode switch in sync with reality BOTH ways, so it never desyncs after
  // a clear/seed (was set-true-only, which left the toggle stuck on after clearing).
  useEffect(() => {
    setDemoOn((plan?.routes?.length ?? 0) > 0);
  }, [plan]);

  // Ask the orchestrator which LLM is active; re-check periodically in case it restarts
  // into a different mode (local DGX vs cloud). Hide the DGX indicator when cloud.
  useEffect(() => {
    let alive = true;
    const check = async () => {
      const h = await getHealth();
      if (alive && h) {
        setCloudModel(h.cloud_model);
        setLlmEnabledState(h.llm_enabled ?? true);
        setLlmLabel(h.llm_label ?? "Nemotron");
      }
    };
    check();
    const id = setInterval(check, 30_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

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
          {/* On-prem DGX Spark indicator — shown only when the model runs locally;
              hidden when a cloud model is active (e.g. OpenAI in production). */}
          {!cloudModel && (
            <div className="brand-sub" data-testid="dgx-indicator">
              <span className={`prov-dot ${connected ? "live" : "off"}`} />
              Local · DGX Spark GB10 · {solveMs != null ? Math.round(solveMs) : "—"} ms
            </div>
          )}
        </div>
      </div>

      {/* RIGHT — theme toggle next to the account avatar. The controls menu is always
          available (Demo mode, Verification, Scenario actions) — it does not require a
          login; account-only items (email, Log out) are gated on the token below. */}
      <div className="account-pill glass" ref={userRef}>
        <ThemeToggle />
        <span className="account-sep" />
        <button
          type="button"
          className="nav-avatar"
          data-testid="user-menu"
          aria-haspopup="menu"
          aria-expanded={userOpen}
          aria-label="Account & controls"
          title={token ? userLabel : "Controls"}
          onClick={() => setUserOpen((v) => !v)}
        >
          {token ? initial : "≡"}
        </button>
        {userOpen && (
          <div className="user-dropdown glass" role="menu">
            {token && <div className="user-dd-email" title={userLabel}>{userLabel}</div>}
            {token && role && <div className="user-dd-role">{role}</div>}

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

            <button
              type="button"
              className="user-dd-toggle"
              data-testid="toggle-model"
              role="menuitemcheckbox"
              aria-checked={llmEnabled}
              onClick={() => {
                const next = !llmEnabled;
                setLlmEnabledState(next); // optimistic
                void setLlmEnabled(next).catch(() => setLlmEnabledState(!next));
              }}
            >
              <span>{llmLabel} model</span>
              <span className={`dd-switch ${llmEnabled ? "on" : ""}`}><i /></span>
            </button>

            <div className="user-dd-sep" />
            <div className="user-dd-section">Map routing source</div>
            <div className="user-dd-rowctl"><RouteSourceToggle /></div>

            <div className="user-dd-sep" />
            <div className="user-dd-section">Scenario actions</div>
            <button
              type="button"
              className="user-dd-item"
              data-testid="scenario-bridge"
              role="menuitem"
              onClick={() => {
                setUserOpen(false);
                void injectBridgeClosure().catch(() => {});
              }}
            >
              Tower Bridge closure
            </button>
            <DemoControls />

            {token && (
              <>
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
              </>
            )}
          </div>
        )}
      </div>
    </>
  );
}
