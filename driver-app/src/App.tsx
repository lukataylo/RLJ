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

import { useEffect, useRef, useState } from "react";
import Signup from "./components/Signup";
import DriverMap from "./components/DriverMap";
import GreenWaveCard from "./components/GreenWaveCard";
import ContributionStats from "./components/ContributionStats";
import ActiveDelivery from "./components/ActiveDelivery";
import JobsView from "./components/JobsView";
import BottomNav, { type Tab } from "./components/BottomNav";
import VoiceOverlay from "./components/VoiceOverlay";
import { selectActiveRoute, useStore } from "./store";
import {
  getCongestion,
  getGuidance,
  getGeoFix,
  getJobs,
  getPlan,
  getSignalAdvice,
  health,
  postTelemetry,
  simulateGps,
} from "./api";
import { getDirections } from "./lib/directions";
import { haversine } from "./lib/geo";
import { demoCongestion, demoGuidance, demoJobs, demoPlan } from "./lib/demo";
import type { DriverPing, GpsFix, Maneuver, Route } from "./types";

const PING_MS = 5000;
const CONGESTION_MS = 6000;
const GUIDANCE_MS = 4000;
const JOBS_MS = 8000;

const ANNOUNCE_FAR = 250;
const ANNOUNCE_NEAR = 60;
const ARRIVE = 25;

function speak(text: string) {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "en-GB";
  window.speechSynthesis.speak(u);
}

function shortInstruction(m: Maneuver): string {
  if (m.type === "arrive") return "Arriving now.";
  const mod = m.modifier ?? "";
  if (mod.includes("left")) return "Turn left now.";
  if (mod.includes("right")) return "Turn right now.";
  if (mod.includes("straight")) return "Continue straight.";
  return m.instruction;
}

function routeKey(r: Route | null): string {
  if (!r) return "";
  return r.stops.map((s) => `${s.location.lat},${s.location.lng}`).join("|") +
    `#${(r.polyline || []).length}`;
}

export default function App() {
  const driver = useStore((s) => s.driver);
  const setDriver = useStore((s) => s.setDriver);

  // Demo deep-link: ?demo seeds a local driver so the home screen is reachable
  // without onboarding (the app is demo-first; signup still mints a real id).
  useEffect(() => {
    if (driver) return;
    if (new URLSearchParams(window.location.search).has("demo")) {
      setDriver({
        id: "drv_demo01",
        name: "Sam",
        vehicle_type: "scooter",
        consent: true,
        joined_at: new Date().toISOString(),
        points: 240,
      });
    }
  }, [driver, setDriver]);

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

  const params = new URLSearchParams(window.location.search);
  const [tab, setTab] = useState<Tab>(params.get("tab") === "impact" ? "impact" : "drive");
  const [voiceOpen, setVoiceOpen] = useState(params.has("voice"));

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

  // -- jobs + plan poll (active delivery + upcoming/past) -------------------
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      const st = useStore.getState();
      const [jobsRes, planRes] = await Promise.all([getJobs(), getPlan()]);
      if (!alive) return;
      if (jobsRes.ok && jobsRes.data && jobsRes.data.length) {
        st.setJobs(jobsRes.data, "live");
        st.setPlan(planRes.ok ? (planRes.data ?? null) : null);
        st.setOrchestratorOnline(true);
      } else if (jobsRes.status === 0 || !st.orchestratorOnline) {
        // Offline (or server has no jobs) -> demo jobs + plan.
        st.setJobs(demoJobs(), "demo");
        st.setPlan(demoPlan());
      } else {
        st.setJobs([], "off");
        st.setPlan(null);
      }
    };
    poll();
    const id = window.setInterval(poll, JOBS_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  // -- directions: (re)build when the active route geometry changes ---------
  const keyRef = useRef("");
  const activeRoute = useStore(selectActiveRoute);
  const key = routeKey(activeRoute);
  useEffect(() => {
    if (!activeRoute || activeRoute.stops.length < 1) {
      useStore.getState().setDirections(null);
      return;
    }
    let cancelled = false;
    const navWas = useStore.getState().navigating;
    (async () => {
      const dir = await getDirections(activeRoute, activeRoute.polyline || []);
      if (cancelled) return;
      useStore.getState().setDirections(dir);
      if (navWas && keyRef.current && keyRef.current !== key) speak("Route updated.");
      keyRef.current = key;
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // -- turn-by-turn: announce maneuvers as the driver approaches them --------
  const navigating = useStore((s) => s.navigating);
  const directions = useStore((s) => s.directions);
  const lastFix = useStore((s) => s.lastFix);
  const maneuverIdx = useRef(0);
  const announced = useRef<Record<number, Set<string>>>({});
  useEffect(() => {
    maneuverIdx.current = directions && directions.maneuvers.length > 1 ? 1 : 0;
    announced.current = {};
  }, [directions]);
  useEffect(() => {
    if (!navigating || !directions || !lastFix) return;
    const mans = directions.maneuvers;
    if (!mans.length) return;
    const idx = Math.min(maneuverIdx.current, mans.length - 1);
    const target = mans[idx];
    const d = haversine(lastFix, target.location);
    useStore.getState().setManeuver(target, d);
    const fired = (announced.current[idx] ||= new Set<string>());
    if (d <= ANNOUNCE_FAR && !fired.has("far")) {
      fired.add("far");
      speak(target.instruction);
    }
    if (d <= ANNOUNCE_NEAR && !fired.has("near")) {
      fired.add("near");
      speak(shortInstruction(target));
    }
    if (d <= ARRIVE) {
      if (idx < mans.length - 1) maneuverIdx.current = idx + 1;
      else if (!fired.has("arrived")) {
        fired.add("arrived");
        speak("You have arrived.");
      }
    }
  }, [lastFix, navigating, directions]);

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
          PulseGo <span className="brand-accent">DRIVER</span>
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
        {tab === "drive" && (
          <>
            <DriverMap />
            <div className="cards">
              <ActiveDelivery />
              <GreenWaveCard />
              {congestionSource === "demo" && (
                <p className="demo-foot">
                  Demo data — start the orchestrator (VITE_ORCHESTRATOR_URL) for live
                  congestion &amp; green-wave guidance.
                </p>
              )}
            </div>
          </>
        )}
        {tab === "jobs" && (
          <div className="cards">
            <JobsView />
          </div>
        )}
        {tab === "impact" && (
          <div className="cards">
            <ContributionStats />
          </div>
        )}
      </main>

      <BottomNav tab={tab} onTab={setTab} onVoice={() => setVoiceOpen(true)} />

      {voiceOpen && (
        <VoiceOverlay name={driver.name ?? undefined} onClose={() => setVoiceOpen(false)} />
      )}
    </div>
  );
}
