// App shell + orchestration.
//   - No driver yet -> Signup.
//   - Otherwise: header (share toggle + live "contributing" indicator), the
//     live driver-centred map, the green-wave + contribution cards, the Ask FAB.
//
// Three polling loops drive the live data, each degrading gracefully:
//   * health   — is the orchestrator reachable? (chooses demo vs hide-card)
//   * telemetry — when sharing, send a DriverPing every ~5s (GPS or simulated)
//   * congestion / guidance — poll the read endpoints, fall back to demo data
//     when offline, or hide a card when the endpoint 404s while online.

import { useEffect, useRef } from "react";
import Signup from "./components/Signup";
import DriverMap from "./components/DriverMap";
import GreenWaveCard from "./components/GreenWaveCard";
import ContributionStats from "./components/ContributionStats";
import AskButton from "./components/AskButton";
import { useStore } from "./store";
import {
  getCongestion,
  getGuidance,
  getGeoFix,
  getSignalAdvice,
  health,
  postTelemetry,
  simulateGps,
} from "./api";
import { demoCongestion, demoGuidance } from "./lib/demo";
import type { DriverPing, GpsFix } from "./types";

const PING_MS = 5000;
const CONGESTION_MS = 6000;
const GUIDANCE_MS = 4000;

export default function App() {
  const driver = useStore((s) => s.driver);

  if (!driver) return <Signup />;
  return <DriverHome />;
}

function DriverHome() {
  const driver = useStore((s) => s.driver)!;
  const sharing = useStore((s) => s.sharing);
  const geoMode = useStore((s) => s.geoMode);
  const pings = useStore((s) => s.pings);
  const congestionSource = useStore((s) => s.congestionSource);
  const online = useStore((s) => s.orchestratorOnline);
  const setSharing = useStore((s) => s.setSharing);
  const signOut = useStore((s) => s.signOut);

  const simRef = useRef<(() => GpsFix) | null>(null);
  const tickRef = useRef(0);

  // -- health probe (and re-probe periodically) -----------------------------
  useEffect(() => {
    let alive = true;
    const probe = async () => {
      const ok = await health();
      if (alive) useStore.getState().setOrchestratorOnline(ok);
    };
    probe();
    const id = window.setInterval(probe, 15000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  // -- congestion poll ------------------------------------------------------
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      const res = await getCongestion();
      if (!alive) return;
      const st = useStore.getState();
      if (res.ok && res.data) {
        st.setCongestion(res.data.cells ?? [], "live");
        st.setOrchestratorOnline(true);
      } else if (res.status === 0 || !st.orchestratorOnline) {
        // Offline -> demo field (breathing via tick).
        st.setCongestion(demoCongestion((tickRef.current += 1)), "demo");
      } else {
        // Online but endpoint missing -> no heat layer.
        st.setCongestion([], "off");
      }
    };
    poll();
    const id = window.setInterval(poll, CONGESTION_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  // -- guidance / green-wave poll -------------------------------------------
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      const st = useStore.getState();
      const id = st.driver?.id;
      if (!id) return;

      const g = await getGuidance(id);
      if (!alive) return;
      if (g.ok && g.data) {
        st.setOrchestratorOnline(true);
        st.setGuidanceAvailable(true);
        st.setGuidance(g.data, "live");
        return;
      }
      if (g.status === 0 || !st.orchestratorOnline) {
        // Offline -> demo guidance (contribution grows with local pings).
        st.setGuidanceAvailable(true);
        st.setGuidance(demoGuidance(id, st.pings, st.lastFix), "demo");
        return;
      }
      // Online but /driver/{id}/guidance 404'd -> try /signals/advice.
      const fix = st.lastFix;
      const a = await getSignalAdvice({
        driver_id: id,
        lat: fix?.lat ?? 51.5033,
        lng: fix?.lng ?? -0.1195,
        heading: fix?.heading_deg ?? 0,
      });
      if (!alive) return;
      if (a.ok && a.data) {
        st.setGuidanceAvailable(true);
        st.setAdvice(a.data);
      } else {
        // Both optional endpoints unavailable -> hide the green-wave card.
        st.setGuidanceAvailable(false);
        st.setGuidance(null, "off");
      }
    };
    poll();
    const t = window.setInterval(poll, GUIDANCE_MS);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  // -- telemetry: send a ping every PING_MS while sharing -------------------
  useEffect(() => {
    if (!sharing) return;
    let alive = true;
    let resolvedMode: "gps" | "sim" | null = null;

    const nextFix = async (): Promise<GpsFix> => {
      // First call resolves whether real GPS is usable; thereafter stick to it.
      if (resolvedMode === null) {
        const fix = await getGeoFix();
        if (fix) {
          resolvedMode = "gps";
          useStore.getState().setGeoMode("gps");
          return fix;
        }
        resolvedMode = "sim";
        useStore.getState().setGeoMode("sim");
      }
      if (resolvedMode === "gps") {
        const fix = await getGeoFix(4000);
        if (fix) return fix;
        // GPS dropped mid-session -> fall back to the simulator.
      }
      if (!simRef.current) simRef.current = simulateGps();
      return simRef.current();
    };

    const sendPing = async () => {
      const st = useStore.getState();
      const id = st.driver?.id;
      if (!id || !alive) return;
      const fix = await nextFix();
      if (!alive) return;
      st.recordFix(fix);
      const ping: DriverPing = {
        driver_id: id,
        lat: fix.lat,
        lng: fix.lng,
        speed_mps: fix.speed_mps,
        heading_deg: fix.heading_deg,
        ts: new Date().toISOString(),
      };
      const res = await postTelemetry({ pings: [ping] });
      if (res.ok) st.setOrchestratorOnline(true);
    };

    sendPing(); // immediate first ping
    const id = window.setInterval(sendPing, PING_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [sharing]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand-mark sm">
          <span className="brand-ring" />
          RLJ <span className="brand-accent">DRIVER</span>
        </div>

        <div className="topbar-right">
          <span className={`net-chip ${online ? "online" : "demo"}`}>
            {online ? "● live" : "◌ demo"}
          </span>
          <span className="driver-chip">
            {driver.name ?? "Driver"} · {driver.vehicle_type}
          </span>
          <button className="ghost-btn" onClick={signOut} title="Sign out">
            ⎋
          </button>
        </div>
      </header>

      <div className="share-row glass">
        <button
          type="button"
          className={`share-toggle ${sharing ? "on" : ""}`}
          data-testid="btn-share-toggle"
          role="switch"
          aria-checked={sharing}
          onClick={() => setSharing(!sharing)}
        >
          <span className="share-knob" />
          <span className="share-label">
            {sharing ? "Sharing location" : "Share location"}
          </span>
        </button>

        <div className={`contributing ${sharing ? "live" : ""}`}>
          {sharing ? (
            <>
              <span className="contrib-dot" />
              <span>
                Contributing
                {geoMode === "sim" ? " (simulated)" : geoMode === "gps" ? " (GPS)" : "…"}
                {" · "}
                {pings} ping{pings === 1 ? "" : "s"}
              </span>
            </>
          ) : (
            <span className="contrib-idle">Toggle on to feed the flywheel</span>
          )}
        </div>
      </div>

      <main className="main">
        <DriverMap />

        <div className="cards">
          <GreenWaveCard />
          <ContributionStats />
          {congestionSource === "demo" && (
            <p className="demo-foot">
              Demo data — start the orchestrator (VITE_ORCHESTRATOR_URL) for live
              congestion &amp; green-wave guidance.
            </p>
          )}
        </div>
      </main>

      <AskButton />
    </div>
  );
}
