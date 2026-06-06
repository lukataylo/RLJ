// Root layout: load brand fonts, provide the theme, bootstrap auth/identity +
// the live WebSocket, and gate navigation (login → courier select → tabs).
import {
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
} from "@expo-google-fonts/inter";
import {
  Poppins_500Medium,
  Poppins_600SemiBold,
  Poppins_700Bold,
  useFonts,
} from "@expo-google-fonts/poppins";
import { Stack, useRouter, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import React, { useEffect, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { me } from "../src/lib/api";
import { loadToken } from "../src/lib/auth";
import { loadApiUrl } from "../src/lib/config";
import { useStore } from "../src/lib/store";
import { connectWs, disconnectWs } from "../src/lib/ws";
import { ThemeProvider, useTheme } from "../src/theme/ThemeProvider";

function Gate() {
  const { theme } = useTheme();
  const router = useRouter();
  const segments = useSegments();
  const [ready, setReady] = useState(false);

  const authed = useStore((s) => s.authed);
  const courierId = useStore((s) => s.courierId);

  // One-time bootstrap: API url, token, identity, WS.
  useEffect(() => {
    (async () => {
      await loadApiUrl();
      await useStore.getState().bootIdentity();
      const token = await loadToken();
      if (token) {
        const res = await me();
        if (res.ok && res.data) {
          useStore.getState().setAuthed(true, res.data.email);
        }
      }
      connectWs();
      setReady(true);
    })();
    return () => disconnectWs();
  }, []);

  // Redirect based on auth + identity once we know the route group.
  useEffect(() => {
    if (!ready) return;
    const group = segments[0]; // "login" | "select-courier" | "(tabs)" | undefined
    if (!authed) {
      if (group !== "login") router.replace("/login");
    } else if (!courierId) {
      if (group !== "select-courier") router.replace("/select-courier");
    } else if (group !== "(tabs)") {
      router.replace("/navigate");
    }
  }, [ready, authed, courierId, segments]);

  if (!ready) {
    return (
      <View style={{ flex: 1, backgroundColor: theme.bg, alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator color={theme.accent} size="large" />
      </View>
    );
  }

  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: theme.bg } }}>
      <Stack.Screen name="login" />
      <Stack.Screen name="select-courier" />
      <Stack.Screen name="(tabs)" />
    </Stack>
  );
}

export default function RootLayout() {
  const [loaded] = useFonts({
    Poppins_500Medium,
    Poppins_600SemiBold,
    Poppins_700Bold,
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
  });

  if (!loaded) {
    return <View style={{ flex: 1, backgroundColor: "#0e0d0c" }} />;
  }

  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <StatusBar style="light" />
        <Gate />
      </ThemeProvider>
    </SafeAreaProvider>
  );
}
