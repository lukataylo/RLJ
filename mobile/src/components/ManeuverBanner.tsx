// Turn-by-turn banner pinned to the top of the Navigate map: a large maneuver
// arrow + the instruction + distance to the turn. Glass-solid for legibility
// over the map.
import { MaterialCommunityIcons } from "@expo/vector-icons";
import React from "react";
import { Text, View } from "react-native";
import { distancePhrase } from "../lib/geo";
import type { Maneuver } from "../lib/types";
import { useTheme } from "../theme/ThemeProvider";
import { FONT } from "../theme/tokens";
import { GlassCard } from "./GlassCard";

function iconFor(m: Maneuver): any {
  if (m.type === "arrive") return "flag-checkered";
  if (m.type === "depart") return "navigation-variant";
  const mod = m.modifier || "";
  if (mod.includes("sharp left")) return "arrow-left-bottom";
  if (mod.includes("sharp right")) return "arrow-right-bottom";
  if (mod.includes("slight left")) return "arrow-top-left";
  if (mod.includes("slight right")) return "arrow-top-right";
  if (mod.includes("left")) return "arrow-left-top";
  if (mod.includes("right")) return "arrow-right-top";
  if (mod.includes("uturn")) return "u-turn-left";
  return "arrow-up";
}

export function ManeuverBanner({
  maneuver,
  distanceM,
  source,
}: {
  maneuver: Maneuver | null;
  distanceM: number;
  source?: "mapbox" | "polyline";
}) {
  const { theme } = useTheme();
  if (!maneuver) return null;
  return (
    <GlassCard solid style={{ flexDirection: "row", alignItems: "center", gap: 14 }}>
      <View
        style={{
          width: 52,
          height: 52,
          borderRadius: 14,
          backgroundColor: theme.accentSoft,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <MaterialCommunityIcons name={iconFor(maneuver)} size={30} color={theme.accent} />
      </View>
      <View style={{ flex: 1 }}>
        <Text
          style={{
            color: theme.text,
            fontFamily: FONT.headSemi,
            fontSize: 17,
          }}
          numberOfLines={2}
        >
          {maneuver.instruction}
        </Text>
        <Text style={{ color: theme.muted, fontFamily: FONT.bodyMed, fontSize: 12, marginTop: 2 }}>
          {distancePhrase(distanceM)}
          {source === "polyline" ? "  ·  estimated turns" : ""}
        </Text>
      </View>
    </GlassCard>
  );
}
