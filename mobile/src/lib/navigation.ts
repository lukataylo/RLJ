// Navigation engine (React hook). While navigating it:
//   • watches GPS (expo-location), falling back to a London-loop simulator when
//     no real fix is available so the app demos on a laptop/simulator;
//   • announces upcoming maneuvers via text-to-speech (expo-speech) at ~250 m,
//     ~60 m and on arrival, each said once;
//   • detects going off-route (distance to the route line) and reports it so the
//     screen can request a server re-route;
//   • batches GPS into DriverPing[] and POSTs /telemetry every ~5 s (consent).

import * as Location from "expo-location";
import * as Speech from "expo-speech";
import { activateKeepAwakeAsync, deactivateKeepAwake } from "expo-keep-awake";
import { useEffect, useRef, useState } from "react";
import { postTelemetry } from "./api";
import { distToPath, haversine, simulateGps } from "./geo";
import type { DirectionsResult, GpsFix, Maneuver } from "./types";

const ANNOUNCE_FAR = 250; // metres
const ANNOUNCE_NEAR = 60;
const ARRIVE = 25;
const OFFROUTE_M = 50;
const OFFROUTE_HITS = 3; // consecutive off-route fixes before reporting
const TELEMETRY_MS = 5000;

interface NavOptions {
  enabled: boolean;
  muted: boolean;
  directions: DirectionsResult | null;
  driverId: string | null;
  consent: boolean;
  onOffRoute: () => void;
}

interface NavState {
  fix: GpsFix | null;
  simulated: boolean;
  nextManeuver: Maneuver | null;
  distanceToNext: number;
  remainingCount: number;
}

export function useNavEngine(opts: NavOptions): NavState {
  const { enabled, muted, directions, driverId, consent, onOffRoute } = opts;

  const [fix, setFix] = useState<GpsFix | null>(null);
  const [simulated, setSimulated] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [distanceToNext, setDistanceToNext] = useState(0);

  const announced = useRef<Record<number, Set<string>>>({});
  const offHits = useRef(0);
  const offReported = useRef(false);
  const pings = useRef<GpsFix[]>([]);
  const mutedRef = useRef(muted);
  mutedRef.current = muted;

  // Reset announcements + index when the route changes (e.g. after a re-route).
  useEffect(() => {
    announced.current = {};
    offHits.current = 0;
    offReported.current = false;
    // first maneuver is "depart"; aim at the first real instruction if present
    setActiveIndex(directions && directions.maneuvers.length > 1 ? 1 : 0);
  }, [directions]);

  function speak(text: string) {
    if (mutedRef.current) return;
    Speech.stop();
    Speech.speak(text, { language: "en-GB", rate: 1.0, pitch: 1.0 });
  }

  // Process one fix: announcements, arrival advance, off-route detection.
  function onFix(next: GpsFix, sim: boolean) {
    setFix(next);
    setSimulated(sim);
    pings.current.push(next);

    if (!directions || directions.maneuvers.length === 0) return;
    const maneuvers = directions.maneuvers;
    const idx = Math.min(activeIndexRef.current, maneuvers.length - 1);
    const target = maneuvers[idx];
    const d = haversine(next, target.location);
    setDistanceToNext(d);

    const fired = (announced.current[idx] ||= new Set<string>());
    if (d <= ANNOUNCE_FAR && !fired.has("far")) {
      fired.add("far");
      speak(target.instruction);
    }
    if (d <= ANNOUNCE_NEAR && !fired.has("near")) {
      fired.add("near");
      // short nudge for the near callout
      speak(shortInstruction(target));
    }
    if (d <= ARRIVE) {
      if (idx < maneuvers.length - 1) {
        setActiveIndex(idx + 1);
      } else if (!fired.has("arrived")) {
        fired.add("arrived");
        speak("You have arrived.");
      }
    }

    // off-route check against the drawn geometry
    const offset = distToPath(next, directions.geometry);
    if (offset > OFFROUTE_M) {
      offHits.current += 1;
      if (offHits.current >= OFFROUTE_HITS && !offReported.current) {
        offReported.current = true;
        speak("You appear to be off route. Requesting a new route.");
        onOffRoute();
      }
    } else {
      offHits.current = 0;
      offReported.current = false;
    }
  }

  // keep a ref of activeIndex so the watch callback reads the latest value
  const activeIndexRef = useRef(activeIndex);
  activeIndexRef.current = activeIndex;

  // GPS subscription (real → simulated fallback).
  useEffect(() => {
    if (!enabled) return;
    let sub: Location.LocationSubscription | null = null;
    let simTimer: ReturnType<typeof setInterval> | null = null;
    let cancelled = false;

    (async () => {
      await activateKeepAwakeAsync("pulsego-nav").catch(() => {});
      let granted = false;
      try {
        const { status } = await Location.requestForegroundPermissionsAsync();
        granted = status === "granted";
      } catch {
        granted = false;
      }

      if (granted && !cancelled) {
        try {
          sub = await Location.watchPositionAsync(
            {
              accuracy: Location.Accuracy.High,
              distanceInterval: 8,
              timeInterval: 2000,
            },
            (pos) =>
              onFix(
                {
                  lat: pos.coords.latitude,
                  lng: pos.coords.longitude,
                  speed_mps: pos.coords.speed ?? 0,
                  heading_deg: pos.coords.heading ?? 0,
                },
                false,
              ),
          );
          return;
        } catch {
          // fall through to simulator
        }
      }

      // No real GPS — simulate a London loop so the demo still moves.
      if (!cancelled) {
        const step = simulateGps(40);
        simTimer = setInterval(() => onFix(step(), true), 3000);
      }
    })();

    return () => {
      cancelled = true;
      if (sub) sub.remove();
      if (simTimer) clearInterval(simTimer);
      deactivateKeepAwake("pulsego-nav").catch(() => {});
      Speech.stop();
    };
    // re-subscribe when navigation toggles; directions handled separately
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  // Telemetry flush loop.
  useEffect(() => {
    if (!enabled || !consent || !driverId) return;
    const t = setInterval(() => {
      if (pings.current.length === 0) return;
      const batch = pings.current.splice(0, pings.current.length);
      const ts = new Date().toISOString();
      postTelemetry({
        pings: batch.map((p) => ({
          driver_id: driverId,
          lat: p.lat,
          lng: p.lng,
          speed_mps: p.speed_mps,
          heading_deg: p.heading_deg,
          ts,
        })),
      }).catch(() => {});
    }, TELEMETRY_MS);
    return () => clearInterval(t);
  }, [enabled, consent, driverId]);

  const maneuvers = directions?.maneuvers ?? [];
  const nextManeuver = maneuvers[Math.min(activeIndex, maneuvers.length - 1)] ?? null;

  return {
    fix,
    simulated,
    nextManeuver,
    distanceToNext,
    remainingCount: Math.max(0, maneuvers.length - activeIndex),
  };
}

function shortInstruction(m: Maneuver): string {
  if (m.type === "arrive") return "Arriving now.";
  if (m.modifier) {
    if (m.modifier.includes("left")) return "Turn left now.";
    if (m.modifier.includes("right")) return "Turn right now.";
    if (m.modifier.includes("straight")) return "Continue straight.";
  }
  return m.instruction;
}
