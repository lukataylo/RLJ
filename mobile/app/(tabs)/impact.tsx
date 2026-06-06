// Impact tab — contribution / gamification: pings sent, couriers helped,
// points, and a "minutes faster" hero. RN port of the PWA's ContributionStats.
import { MaterialCommunityIcons } from "@expo/vector-icons";
import React from "react";
import { ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { GlassCard } from "../../src/components/GlassCard";
import { GreenWaveCard } from "../../src/components/GreenWaveCard";
import { useStore } from "../../src/lib/store";
import { useTheme } from "../../src/theme/ThemeProvider";
import { FONT } from "../../src/theme/tokens";
import { Header } from "./jobs";

export default function Impact() {
  const { theme } = useTheme();
  const insets = useSafeAreaInsets();

  const pings = useStore((s) => s.sessionPings);
  const guidance = useStore((s) => s.guidance);
  const consent = useStore((s) => s.consent);

  const couriersHelped = guidance?.contribution?.couriers_helped ?? 0;
  const points = pings * 10 + couriersHelped * 25;
  const minutesSaved = Math.max(0, Math.round((couriersHelped * 90 + pings * 3) / 60));

  return (
    <View style={{ flex: 1, backgroundColor: theme.bg, paddingTop: insets.top + 12 }}>
      <Header title="Impact" subtitle="Your contribution to the flywheel" theme={theme} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 24, gap: 14 }}>
        {/* hero */}
        <GlassCard style={{ alignItems: "center", paddingVertical: 26 }}>
          <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 6 }}>
            <Text style={{ color: theme.amber, fontFamily: FONT.head, fontSize: 64, fontVariant: ["tabular-nums"] }}>
              {minutesSaved}
            </Text>
            <Text style={{ color: theme.muted, fontFamily: FONT.headMed, fontSize: 20, marginBottom: 12 }}>
              min
            </Text>
          </View>
          <Text style={{ color: theme.muted, fontFamily: FONT.bodyMed, fontSize: 13, letterSpacing: 0.4 }}>
            you made London faster
          </Text>
        </GlassCard>

        {/* stat grid */}
        <View style={{ flexDirection: "row", gap: 10 }}>
          <StatCell theme={theme} value={pings} cap="pings sent" tone={theme.text} />
          <StatCell theme={theme} value={couriersHelped} cap="couriers helped" tone={theme.text} />
          <StatCell theme={theme} value={points} cap="points" tone={theme.accent} />
        </View>

        {/* sharing status */}
        <GlassCard style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
          <MaterialCommunityIcons
            name={consent ? "crosshairs-gps" : "crosshairs-off"}
            size={18}
            color={consent ? theme.green : theme.faint}
          />
          <Text style={{ color: theme.text, fontFamily: FONT.bodyMed, fontSize: 13, flex: 1 }}>
            {consent
              ? "Sharing GPS while navigating — feeding the flywheel."
              : "Location sharing is off. Enable it in Settings to contribute."}
          </Text>
        </GlassCard>

        {/* live green-wave (also shown on Navigate) */}
        <GreenWaveCard />
      </ScrollView>
    </View>
  );
}

function StatCell({
  theme,
  value,
  cap,
  tone,
}: {
  theme: ReturnType<typeof useTheme>["theme"];
  value: number;
  cap: string;
  tone: string;
}) {
  return (
    <GlassCard style={{ flex: 1, alignItems: "center", paddingVertical: 16 }}>
      <Text style={{ color: tone, fontFamily: FONT.head, fontSize: 26, fontVariant: ["tabular-nums"] }}>
        {value}
      </Text>
      <Text
        style={{
          color: theme.muted,
          fontFamily: FONT.bodyMed,
          fontSize: 10,
          letterSpacing: 0.6,
          marginTop: 4,
          textAlign: "center",
        }}
      >
        {cap}
      </Text>
    </GlassCard>
  );
}
