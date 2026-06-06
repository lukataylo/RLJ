// Flywheel polling: keeps congestion + green-wave guidance fresh while the app
// is open, degrading gracefully exactly like the PWA (driver-app/src/App.tsx):
//   • live   — endpoint returned data
//   • demo   — orchestrator unreachable → synthesise data so screens stay alive
//   • off    — orchestrator up but the optional endpoint 404'd → hide the card
import { useEffect, useRef } from "react";
import { getCongestion, getGuidance, getSignalAdvice, health } from "./api";
import { demoCongestion, demoGuidance } from "./demo";
import { useStore } from "./store";

const CONGESTION_MS = 6000;
const GUIDANCE_MS = 4000;
const HEALTH_MS = 15000;

/** Mount once (e.g. in the tabs layout) to drive the flywheel data sources. */
export function useFlywheel() {
  const driverId = useStore((s) => s.driverId);
  const tick = useRef(0);

  // health probe
  useEffect(() => {
    let alive = true;
    const probe = async () => {
      const ok = await health();
      if (alive) useStore.getState().setOnline(ok);
    };
    probe();
    const id = setInterval(probe, HEALTH_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // congestion poll
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      const res = await getCongestion();
      if (!alive) return;
      const st = useStore.getState();
      if (res.ok && res.data) {
        st.setCongestion(res.data.cells ?? [], "live");
        st.setOnline(true);
      } else if (res.status === 0 || !st.online) {
        st.setCongestion(demoCongestion((tick.current += 1)), "demo");
      } else {
        st.setCongestion([], "off");
      }
    };
    poll();
    const id = setInterval(poll, CONGESTION_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // guidance / green-wave poll
  useEffect(() => {
    if (!driverId) return;
    let alive = true;
    const poll = async () => {
      const st = useStore.getState();
      const g = await getGuidance(driverId);
      if (!alive) return;
      if (g.ok && g.data) {
        st.setOnline(true);
        st.setGuidanceAvailable(true);
        st.setGuidance(g.data, "live");
        // server guidance carries no advice yet → backfill from /signals/advice
        if (!g.data.signal_advice) {
          const fix = st.lastFix;
          const a = await getSignalAdvice({
            driver_id: driverId,
            lat: fix?.lat ?? 51.5033,
            lng: fix?.lng ?? -0.1195,
            heading: fix?.heading_deg ?? 0,
          });
          if (alive && a.ok && a.data) st.setAdvice(a.data);
        }
        return;
      }
      if (g.status === 0 || !st.online) {
        st.setGuidanceAvailable(true);
        st.setGuidance(demoGuidance(driverId, st.sessionPings, st.lastFix), "demo");
        return;
      }
      // online but guidance 404'd → try /signals/advice alone
      const fix = st.lastFix;
      const a = await getSignalAdvice({
        driver_id: driverId,
        lat: fix?.lat ?? 51.5033,
        lng: fix?.lng ?? -0.1195,
        heading: fix?.heading_deg ?? 0,
      });
      if (!alive) return;
      if (a.ok && a.data) {
        st.setGuidanceAvailable(true);
        st.setAdvice(a.data);
      } else {
        st.setGuidanceAvailable(false);
        st.setGuidance(null, "off");
      }
    };
    poll();
    const id = setInterval(poll, GUIDANCE_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [driverId]);
}
