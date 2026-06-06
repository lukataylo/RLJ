// Delivery card — echoes the web `.dcard`: origin→dest, priority pill, ETA,
// cold-chain + type chips. Tappable.
import { MaterialCommunityIcons } from "@expo/vector-icons";
import React from "react";
import { Pressable, Text, View } from "react-native";
import {
  PRIORITY_LABEL,
  STATUS_LABEL,
  etaMinutes,
  fmtTime,
  jobTypeLabel,
} from "../lib/format";
import type { DeliveryJob } from "../lib/types";
import { useTheme } from "../theme/ThemeProvider";
import { FONT, PRIORITY_HEX, STATUS_HEX } from "../theme/tokens";
import { GlassCard } from "./GlassCard";
import { StatusPill } from "./StatusPill";

export function JobCard({
  job,
  onPress,
  showStatus,
  past,
}: {
  job: DeliveryJob;
  onPress?: () => void;
  showStatus?: boolean;
  past?: boolean;
}) {
  const { theme } = useTheme();
  const due = job.time_window?.due_by;

  return (
    <Pressable onPress={onPress} disabled={!onPress}>
      <GlassCard style={{ marginBottom: 10, padding: 13 }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
          <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
            <StatusPill
              label={PRIORITY_LABEL[job.priority]}
              color={PRIORITY_HEX[job.priority]}
            />
            {showStatus && (
              <StatusPill
                label={STATUS_LABEL[job.status]}
                color={STATUS_HEX[job.status]}
              />
            )}
          </View>
          {!past && due ? (
            <Text
              style={{
                color: theme.muted,
                fontFamily: FONT.bodyMed,
                fontSize: 12,
                fontVariant: ["tabular-nums"],
              }}
            >
              {etaMinutes(due) || fmtTime(due)}
            </Text>
          ) : past ? (
            <Text
              style={{
                color: theme.faint,
                fontFamily: FONT.bodyMed,
                fontSize: 12,
              }}
            >
              {fmtTime(job.created_at)}
            </Text>
          ) : null}
        </View>

        {/* origin → destination */}
        <View style={{ marginTop: 10, gap: 4 }}>
          <Row icon="circle-outline" text={job.origin.name || "Pickup"} theme={theme} />
          <Row icon="map-marker" text={job.destination.name || "Dropoff"} theme={theme} accent />
        </View>

        {/* chips */}
        <View style={{ flexDirection: "row", gap: 14, marginTop: 10 }}>
          <Chip icon="package-variant-closed" text={jobTypeLabel(job)} theme={theme} />
          {job.cold_chain && (
            <Chip icon="snowflake" text="Cold chain" theme={theme} color="#64D2FF" />
          )}
        </View>
      </GlassCard>
    </Pressable>
  );
}

function Row({
  icon,
  text,
  theme,
  accent,
}: {
  icon: any;
  text: string;
  theme: ReturnType<typeof useTheme>["theme"];
  accent?: boolean;
}) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
      <MaterialCommunityIcons
        name={icon}
        size={15}
        color={accent ? theme.accent : theme.muted}
      />
      <Text
        style={{ color: theme.text, fontFamily: FONT.bodyMed, fontSize: 14, flex: 1 }}
        numberOfLines={1}
      >
        {text}
      </Text>
    </View>
  );
}

function Chip({
  icon,
  text,
  theme,
  color,
}: {
  icon: any;
  text: string;
  theme: ReturnType<typeof useTheme>["theme"];
  color?: string;
}) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
      <MaterialCommunityIcons name={icon} size={13} color={color || theme.faint} />
      <Text style={{ color: color || theme.muted, fontFamily: FONT.body, fontSize: 11 }}>
        {text}
      </Text>
    </View>
  );
}
