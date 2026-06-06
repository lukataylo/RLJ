// Navigate tab — the live driving screen. Resolves turn-by-turn directions for
// my route, runs the navigation engine (GPS + TTS + telemetry), and exposes the
// re-routing comms: "Re-route" (POST /couriers/{id}/redirect) and "Report
// blockage" (POST /disruptions). A new server plan arriving over the WebSocket
// redraws the route and is announced as "Route updated".
import { MaterialCommunityIcons } from "@expo/vector-icons";
import * as Speech from "expo-speech";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { GlassCard } from "../../src/components/GlassCard";
import { GreenWaveCard } from "../../src/components/GreenWaveCard";
import { ManeuverBanner } from "../../src/components/ManeuverBanner";
import { PrimaryButton } from "../../src/components/PrimaryButton";
import { RouteMap } from "../../src/components/RouteMap";
import { postDisruption, redirectCourier } from "../../src/lib/api";
import { getDirections } from "../../src/lib/directions";
import { etaMinutes, fmtTime } from "../../src/lib/format";
import {
  selectMyCourier,
  selectMyRoute,
  useStore,
} from "../../src/lib/store";
import type { DirectionsResult } from "../../src/lib/types";
import { useNavEngine } from "../../src/lib/navigation";
import { useTheme } from "../../src/theme/ThemeProvider";
import { FONT } from "../../src/theme/tokens";

export default function Navigate() {
  const { theme } = useTheme();
  const insets = useSafeAreaInsets();

  const courierId = useStore((s) => s.courierId);
  const driverId = useStore((s) => s.driverId);
  const consent = useStore((s) => s.consent);
  const connected = useStore((s) => s.connected);
  const courier = useStore(selectMyCourier);
  const route = useStore(selectMyRoute);
  const plan = useStore((s) => s.plan);
  const congestion = useStore((s) => s.congestion);

  const [navigating, setNavigating] = useState(false);
  const [muted, setMuted] = useState(false);
  const [directions, setDirections] = useState<DirectionsResult | null>(null);
  const [rerouting, setRerouting] = useState(false);

  // Stable signature of the route geometry so we only recompute on real changes.
  const routeKey = useMemo(() => {
    if (!route) return "";
    const stops = route.stops.map((s) => `${s.location.lat},${s.location.lng}`).join("|");
    const poly = (route.polyline || []).length;
    return `${stops}#${poly}#${plan?.generated_at ?? ""}`;
  }, [route, plan?.generated_at]);

  const prevKey = useRef("");
  useEffect(() => {
    if (!route || route.stops.length < 1) {
      setDirections(null);
      return;
    }
    let cancelled = false;
    (async () => {
      const dir = await getDirections(route, route.polyline || []);
      if (cancelled) return;
      setDirections(dir);
      // Announce a re-route (geometry changed while we were already navigating).
      if (navigating && prevKey.current && prevKey.current !== routeKey && !muted) {
        Speech.speak("Route updated.", { language: "en-GB" });
      }
      prevKey.current = routeKey;
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeKey]);

  const nav = useNavEngine({
    enabled: navigating,
    muted,
    directions,
    driverId,
    consent,
    onOffRoute: () => doReroute(true),
  });

  async function doReroute(silent = false) {
    if (!courierId) return;
    setRerouting(true);
    const res = await redirectCourier(courierId);
    setRerouting(false);
    if (!res.ok && !silent) {
      Alert.alert("Re-route failed", "Couldn't reach the server to request a new route.");
    }
    // The new plan arrives via the WebSocket → routeKey changes → directions
    // recompute → "Route updated" is announced from the effect above.
  }

  async function reportBlockage() {
    if (!nav.fix) {
      Alert.alert("No position yet", "Start navigation so we know where the blockage is.");
      return;
    }
    const res = await postDisruption({
      kind: "road_closure",
      source: "manual",
      geometry: [{ lat: nav.fix.lat, lng: nav.fix.lng }],
      courier_id: courierId,
    });
    if (res.ok) {
      if (!muted) Speech.speak("Blockage reported. Re-planning.", { language: "en-GB" });
      Alert.alert("Reported", "Blockage sent. The route will re-plan around it.");
    } else {
      Alert.alert("Report failed", "Couldn't reach the server.");
    }
  }

  const stops = route?.stops ?? [];
  const lastStop = stops.length ? stops[stops.length - 1] : null;

  return (
    <View style={{ flex: 1, backgroundColor: theme.bg }}>
      <RouteMap
        geometry={directions?.geometry ?? route?.polyline ?? []}
        stops={stops}
        fix={nav.fix}
        follow={navigating}
        congestion={congestion}
      />

      {/* top maneuver banner while navigating */}
      {navigating && (
        <View style={{ position: "absolute", top: insets.top + 8, left: 12, right: 12 }}>
          <ManeuverBanner
            maneuver={nav.nextManeuver}
            distanceM={nav.distanceToNext}
            source={directions?.source}
          />
        </View>
      )}

      {/* connection + sim chip top-right */}
      <View style={{ position: "absolute", top: insets.top + (navigating ? 92 : 10), right: 12 }}>
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            backgroundColor: theme.panelSolid,
            borderColor: theme.hair,
            borderWidth: 1,
            borderRadius: 999,
            paddingHorizontal: 10,
            paddingVertical: 5,
          }}
        >
          <View
            style={{
              width: 7,
              height: 7,
              borderRadius: 4,
              backgroundColor: connected ? theme.green : theme.faint,
            }}
          />
          <Text style={{ color: theme.muted, fontFamily: FONT.bodyMed, fontSize: 11 }}>
            {connected ? "Live" : "Offline"}
            {nav.simulated ? " · sim GPS" : ""}
          </Text>
        </View>
      </View>

      {/* bottom: green-wave + control sheet */}
      <View style={{ position: "absolute", left: 12, right: 12, bottom: 12, gap: 10 }}>
        {navigating && <GreenWaveCard />}
        <GlassCard solid style={{ padding: 14 }}>
          {!route ? (
            <Text style={{ color: theme.muted, fontFamily: FONT.bodyMed, fontSize: 14, textAlign: "center", paddingVertical: 8 }}>
              No active route assigned to {courier?.name || "your vehicle"} yet.
            </Text>
          ) : (
            <>
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
                <View style={{ flex: 1 }}>
                  <Text style={{ color: theme.text, fontFamily: FONT.headSemi, fontSize: 16 }}>
                    {courier?.name || "Route"}
                  </Text>
                  <Text style={{ color: theme.muted, fontFamily: FONT.bodyMed, fontSize: 12, marginTop: 2 }}>
                    {stops.length} stops
                    {lastStop?.eta ? ` · arrive ${fmtTime(lastStop.eta)} (${etaMinutes(lastStop.eta)})` : ""}
                  </Text>
                </View>
                <Pressable
                  onPress={() => setMuted((m) => !m)}
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: 10,
                    backgroundColor: theme.fill,
                    borderColor: theme.hair,
                    borderWidth: 1,
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <MaterialCommunityIcons
                    name={muted ? "volume-off" : "volume-high"}
                    size={20}
                    color={muted ? theme.muted : theme.accent}
                  />
                </Pressable>
              </View>

              <View style={{ marginTop: 12 }}>
                <PrimaryButton
                  label={navigating ? "End navigation" : "Start navigation"}
                  variant={navigating ? "danger" : "primary"}
                  onPress={() => {
                    setNavigating((n) => {
                      const next = !n;
                      if (!next) Speech.stop();
                      return next;
                    });
                  }}
                />
              </View>

              <View style={{ flexDirection: "row", gap: 10, marginTop: 10 }}>
                <PrimaryButton
                  label="Re-route"
                  variant="ghost"
                  loading={rerouting}
                  onPress={() => doReroute(false)}
                  style={{ flex: 1 }}
                />
                <PrimaryButton
                  label="Report blockage"
                  variant="ghost"
                  onPress={reportBlockage}
                  style={{ flex: 1 }}
                />
              </View>
            </>
          )}
        </GlassCard>
      </View>
    </View>
  );
}
