// Settings — server URL (persisted), theme toggle, telemetry consent, account.
import { MaterialCommunityIcons } from "@expo/vector-icons";
import React, { useState } from "react";
import { ScrollView, Switch, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { GlassCard } from "../../src/components/GlassCard";
import { PrimaryButton } from "../../src/components/PrimaryButton";
import { health } from "../../src/lib/api";
import { clearToken } from "../../src/lib/auth";
import { DEFAULT_API_URL, LOCAL_NEMOTRON_API_URL, getApiUrl, setApiUrl } from "../../src/lib/config";
import { useStore } from "../../src/lib/store";
import { connectWs, disconnectWs } from "../../src/lib/ws";
import { useTheme } from "../../src/theme/ThemeProvider";
import { FONT } from "../../src/theme/tokens";
import { Header } from "./jobs";

export default function Settings() {
  const { theme, name, toggle } = useTheme();
  const insets = useSafeAreaInsets();
  const email = useStore((s) => s.email);
  const consent = useStore((s) => s.consent);
  const courierId = useStore((s) => s.courierId);

  const [url, setUrl] = useState(getApiUrl());
  const [probe, setProbe] = useState<string | null>(null);

  async function saveUrl() {
    await setApiUrl(url || DEFAULT_API_URL);
    disconnectWs();
    connectWs();
    setProbe("Checking…");
    const ok = await health();
    setProbe(ok ? "Reachable ✓" : "Not reachable");
  }

  async function useLocalNemotronBox() {
    const next = LOCAL_NEMOTRON_API_URL;
    setUrl(next);
    await setApiUrl(next);
    disconnectWs();
    connectWs();
    setProbe("Checking local Nemotron box…");
    const ok = await health();
    setProbe(ok ? "Local box reachable ✓" : "Local box not reachable");
  }

  function signOut() {
    clearToken();
    disconnectWs();
    useStore.getState().signOut();
    connectWs();
  }

  return (
    <View style={{ flex: 1, backgroundColor: theme.bg, paddingTop: insets.top + 12 }}>
      <Header title="Settings" theme={theme} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 24, gap: 14 }}>
        {/* Account */}
        <GlassCard>
          <SectionLabel theme={theme}>ACCOUNT</SectionLabel>
          <Row theme={theme} icon="account-circle-outline" label={email || "Signed in"} />
          <Row theme={theme} icon="truck-outline" label={`Courier: ${courierId || "—"}`} />
          <View style={{ marginTop: 12 }}>
            <PrimaryButton label="Sign out" variant="danger" onPress={signOut} />
          </View>
        </GlassCard>

        {/* Appearance */}
        <GlassCard>
          <SectionLabel theme={theme}>APPEARANCE</SectionLabel>
          <ToggleRow
            theme={theme}
            icon={name === "dark" ? "weather-night" : "weather-sunny"}
            label="Dark theme"
            value={name === "dark"}
            onChange={toggle}
          />
        </GlassCard>

        {/* Telemetry */}
        <GlassCard>
          <SectionLabel theme={theme}>FLYWHEEL</SectionLabel>
          <ToggleRow
            theme={theme}
            icon="crosshairs-gps"
            label="Share GPS for green-wave routing"
            value={consent}
            onChange={(v) => useStore.getState().setConsent(v)}
          />
          <Text style={{ color: theme.faint, fontFamily: FONT.body, fontSize: 12, marginTop: 8 }}>
            Anonymous speed/position pings improve congestion estimates for the whole fleet.
          </Text>
        </GlassCard>

        {/* Server */}
        <GlassCard>
          <SectionLabel theme={theme}>SERVER</SectionLabel>
          <TextInput
            value={url}
            onChangeText={setUrl}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            placeholder={DEFAULT_API_URL}
            placeholderTextColor={theme.faint}
            style={{
              backgroundColor: theme.fill,
              borderColor: theme.hair,
              borderWidth: 1,
              borderRadius: theme.radiusBtn,
              paddingHorizontal: 14,
              paddingVertical: 12,
              color: theme.text,
              fontFamily: FONT.body,
              fontSize: 14,
              marginBottom: 10,
            }}
          />
          <View style={{ marginBottom: 10 }}>
            <PrimaryButton label="Use local Nemotron box" variant="ghost" onPress={useLocalNemotronBox} />
          </View>
          <PrimaryButton label="Save & test" variant="ghost" onPress={saveUrl} />
          {probe ? (
            <Text style={{ color: theme.muted, fontFamily: FONT.bodyMed, fontSize: 12, marginTop: 8 }}>
              {probe}
            </Text>
          ) : null}
        </GlassCard>

        <Text style={{ color: theme.faint, fontFamily: FONT.body, fontSize: 11, textAlign: "center" }}>
          PulseGo Driver · v0.1.0
        </Text>
      </ScrollView>
    </View>
  );
}

function SectionLabel({
  children,
  theme,
}: {
  children: React.ReactNode;
  theme: ReturnType<typeof useTheme>["theme"];
}) {
  return (
    <Text
      style={{
        color: theme.muted,
        fontFamily: FONT.bodySemi,
        fontSize: 10,
        letterSpacing: 1.4,
        marginBottom: 10,
      }}
    >
      {children}
    </Text>
  );
}

function Row({
  theme,
  icon,
  label,
}: {
  theme: ReturnType<typeof useTheme>["theme"];
  icon: any;
  label: string;
}) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 4 }}>
      <MaterialCommunityIcons name={icon} size={18} color={theme.muted} />
      <Text style={{ color: theme.text, fontFamily: FONT.bodyMed, fontSize: 14 }}>{label}</Text>
    </View>
  );
}

function ToggleRow({
  theme,
  icon,
  label,
  value,
  onChange,
}: {
  theme: ReturnType<typeof useTheme>["theme"];
  icon: any;
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 4 }}>
      <MaterialCommunityIcons name={icon} size={18} color={theme.muted} />
      <Text style={{ color: theme.text, fontFamily: FONT.bodyMed, fontSize: 14, flex: 1 }}>{label}</Text>
      <Switch
        value={value}
        onValueChange={onChange}
        trackColor={{ true: theme.accent, false: theme.fill2 }}
        thumbColor="#fff"
      />
    </View>
  );
}
