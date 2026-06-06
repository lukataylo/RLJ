// First-run identity: pick which Courier (vehicle) this driver is operating.
// Also registers a Driver record so telemetry pings have an owner.
import { MaterialCommunityIcons } from "@expo/vector-icons";
import React, { useEffect, useState } from "react";
import { FlatList, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { GlassCard } from "../src/components/GlassCard";
import { StatusPill } from "../src/components/StatusPill";
import { getCouriers, postDriver } from "../src/lib/api";
import { useStore } from "../src/lib/store";
import type { Courier } from "../src/lib/types";
import { useTheme } from "../src/theme/ThemeProvider";
import { FONT } from "../src/theme/tokens";

const VEHICLE_ICON: Record<string, any> = {
  van: "truck-outline",
  scooter: "moped",
  bike: "bike",
};

const COURIER_STATUS_COLOR: Record<string, string> = {
  idle: "#9FB85A",
  enroute: "#BFE36B",
  offline: "#5d6b62",
};

export default function SelectCourier() {
  const { theme } = useTheme();
  const insets = useSafeAreaInsets();
  const [couriers, setCouriers] = useState<Courier[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const res = await getCouriers();
      setCouriers(res.data ?? []);
      useStore.getState().setCouriers(res.data ?? []);
      setLoading(false);
    })();
  }, []);

  async function choose(c: Courier) {
    useStore.getState().setCourierId(c.id);
    // Register a driver for the telemetry flywheel (best-effort).
    const driverId = useStore.getState().driverId;
    if (!driverId) {
      const res = await postDriver({
        name: c.name || c.id,
        vehicle_type: (c.vehicle_type as any) || "van",
        consent: useStore.getState().consent,
      });
      if (res.ok && res.data?.id) useStore.getState().setDriverId(res.data.id);
    }
  }

  return (
    <View style={{ flex: 1, backgroundColor: theme.bg, paddingTop: insets.top + 16 }}>
      <View style={{ paddingHorizontal: 18, marginBottom: 12 }}>
        <Text style={{ color: theme.text, fontFamily: FONT.head, fontSize: 22 }}>
          Which vehicle are you?
        </Text>
        <Text style={{ color: theme.muted, fontFamily: FONT.body, fontSize: 14, marginTop: 4 }}>
          Pick the courier you're driving today. Your route and jobs follow this choice.
        </Text>
      </View>

      <FlatList
        data={couriers}
        keyExtractor={(c) => c.id}
        contentContainerStyle={{ padding: 18, paddingTop: 4 }}
        ListEmptyComponent={
          <Text style={{ color: theme.muted, fontFamily: FONT.body, textAlign: "center", marginTop: 40 }}>
            {loading ? "Loading couriers…" : "No couriers available from the server."}
          </Text>
        }
        renderItem={({ item }) => (
          <Pressable onPress={() => choose(item)}>
            <GlassCard style={{ marginBottom: 10, flexDirection: "row", alignItems: "center", gap: 14 }}>
              <View
                style={{
                  width: 46,
                  height: 46,
                  borderRadius: 12,
                  backgroundColor: theme.fill,
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <MaterialCommunityIcons
                  name={VEHICLE_ICON[item.vehicle_type || "van"] || "truck-outline"}
                  size={24}
                  color={theme.accent}
                />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ color: theme.text, fontFamily: FONT.headSemi, fontSize: 16 }}>
                  {item.name || item.id}
                </Text>
                <Text style={{ color: theme.muted, fontFamily: FONT.body, fontSize: 12, marginTop: 2 }}>
                  {item.location?.name || "London"} · {item.vehicle_type || "van"}
                </Text>
              </View>
              <StatusPill
                label={item.status}
                color={COURIER_STATUS_COLOR[item.status] || theme.muted}
              />
            </GlassCard>
          </Pressable>
        )}
      />
    </View>
  );
}
