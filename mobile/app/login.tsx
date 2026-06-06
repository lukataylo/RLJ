// Sign-in screen — POST /auth/login, store the JWT, flip the store to authed.
import { MaterialCommunityIcons } from "@expo/vector-icons";
import React, { useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { PrimaryButton } from "../src/components/PrimaryButton";
import { login, me } from "../src/lib/api";
import { saveToken } from "../src/lib/auth";
import { getApiUrl } from "../src/lib/config";
import { useStore } from "../src/lib/store";
import { useTheme } from "../src/theme/ThemeProvider";
import { FONT } from "../src/theme/tokens";

export default function Login() {
  const { theme } = useTheme();
  const insets = useSafeAreaInsets();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setError(null);
    setBusy(true);
    const res = await login(email.trim(), password);
    if (!res.ok || !res.data) {
      setBusy(false);
      setError(
        res.status === 0
          ? `Can't reach ${getApiUrl()}. Check the server URL in Settings.`
          : res.status === 401
            ? "Invalid email or password."
            : `Login failed (${res.status}).`,
      );
      return;
    }
    await saveToken(res.data.access_token);
    const profile = await me();
    useStore.getState().setAuthed(true, profile.data?.email ?? email.trim());
    setBusy(false);
  }

  const inputStyle = {
    backgroundColor: theme.fill,
    borderColor: theme.hair,
    borderWidth: 1,
    borderRadius: theme.radiusBtn,
    paddingHorizontal: 14,
    paddingVertical: 13,
    color: theme.text,
    fontFamily: FONT.body,
    fontSize: 15,
  };

  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: theme.bg }}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView
        contentContainerStyle={{
          flexGrow: 1,
          justifyContent: "center",
          padding: 24,
          paddingTop: insets.top + 24,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <MaterialCommunityIcons name="shield-outline" size={26} color={theme.accent} />
          <Text style={{ color: theme.text, fontFamily: FONT.head, fontSize: 26 }}>
            PulseGo <Text style={{ color: theme.accent }}>Driver</Text>
          </Text>
        </View>
        <Text style={{ color: theme.muted, fontFamily: FONT.body, fontSize: 14, marginBottom: 28 }}>
          Live medical logistics for London
        </Text>

        <Text style={labelStyle(theme)}>EMAIL</Text>
        <TextInput
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
          placeholder="you@nhs.uk"
          placeholderTextColor={theme.faint}
          style={[inputStyle, { marginBottom: 16 }]}
        />

        <Text style={labelStyle(theme)}>PASSWORD</Text>
        <TextInput
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          placeholder="••••••••"
          placeholderTextColor={theme.faint}
          onSubmitEditing={submit}
          style={[inputStyle, { marginBottom: 24 }]}
        />

        {error && (
          <Text style={{ color: theme.accent, fontFamily: FONT.bodyMed, fontSize: 13, marginBottom: 16 }}>
            {error}
          </Text>
        )}

        <PrimaryButton label="Sign in" onPress={submit} loading={busy} disabled={!email || !password} />

        <Text style={{ color: theme.faint, fontFamily: FONT.body, fontSize: 12, marginTop: 18, textAlign: "center" }}>
          {getApiUrl()}
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function labelStyle(theme: ReturnType<typeof useTheme>["theme"]) {
  return {
    color: theme.muted,
    fontFamily: FONT.bodySemi,
    fontSize: 10,
    letterSpacing: 1.4,
    marginBottom: 7,
  } as const;
}
