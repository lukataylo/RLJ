// Green-wave card — the PWA's headline driver benefit. SignalAdvice message +
// speedometer (current vs target) + seconds-to-green / target / confidence.
// Hidden when the guidance endpoints are unavailable and there's no advice.
import React from "react";
import { Text, View } from "react-native";
import { useStore } from "../lib/store";
import { useTheme } from "../theme/ThemeProvider";
import { FONT } from "../theme/tokens";
import { GlassCard } from "./GlassCard";
import { Speedometer } from "./Speedometer";

const mps2kmh = (m: number) => m * 3.6;

export function GreenWaveCard() {
  const { theme } = useTheme();
  const advice = useStore((s) => s.advice);
  const lastFix = useStore((s) => s.lastFix);
  const source = useStore((s) => s.guidanceSource);
  const available = useStore((s) => s.guidanceAvailable);

  if (!available && !advice) return null;
  if (!advice) return null;

  const curKmh = lastFix ? mps2kmh(lastFix.speed_mps) : 0;
  const targetKmh = advice.target_speed_mps != null ? mps2kmh(advice.target_speed_mps) : undefined;
  const secs = advice.seconds_to_green;
  const conf = advice.confidence;
  const srcColor = source === "live" ? theme.green : source === "demo" ? theme.amber : theme.faint;

  return (
    <GlassCard solid style={{ padding: 14 }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: theme.green }} />
          <Text style={{ color: theme.text, fontFamily: FONT.headSemi, fontSize: 15 }}>
            Green wave
          </Text>
        </View>
        <Text
          style={{
            color: srcColor,
            fontFamily: FONT.bodySemi,
            fontSize: 9,
            letterSpacing: 1.2,
            textTransform: "uppercase",
          }}
        >
          {source}
        </Text>
      </View>

      <Text style={{ color: theme.text, fontFamily: FONT.bodyMed, fontSize: 14, marginTop: 8 }}>
        {advice.message}
      </Text>

      <View style={{ flexDirection: "row", alignItems: "center", gap: 14, marginTop: 8 }}>
        <Speedometer speedKmh={curKmh} targetKmh={targetKmh} />
        <View style={{ flex: 1, gap: 12 }}>
          {secs != null && <Stat theme={theme} value={`${Math.round(secs)}`} cap="sec to green" tone={theme.amber} />}
          {targetKmh != null && <Stat theme={theme} value={`${Math.round(targetKmh)}`} cap="target km/h" tone={theme.text} />}
          {conf != null && <Stat theme={theme} value={`${Math.round(conf * 100)}%`} cap="confidence" tone={theme.text} />}
        </View>
      </View>

      {advice.junction?.name && (
        <Text style={{ color: theme.muted, fontFamily: FONT.body, fontSize: 12, marginTop: 8 }}>
          next: <Text style={{ color: theme.text, fontFamily: FONT.bodySemi }}>{advice.junction.name}</Text>
        </Text>
      )}
    </GlassCard>
  );
}

function Stat({
  theme,
  value,
  cap,
  tone,
}: {
  theme: ReturnType<typeof useTheme>["theme"];
  value: string;
  cap: string;
  tone: string;
}) {
  return (
    <View>
      <Text style={{ color: tone, fontFamily: FONT.head, fontSize: 22, fontVariant: ["tabular-nums"] }}>
        {value}
      </Text>
      <Text style={{ color: theme.muted, fontFamily: FONT.bodyMed, fontSize: 10, letterSpacing: 0.8 }}>
        {cap}
      </Text>
    </View>
  );
}
