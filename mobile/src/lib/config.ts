// Resolves the orchestrator base URL. Default comes from EXPO_PUBLIC_API_URL
// (production: https://api.pulsego.org), but the Settings tab can override it at
// runtime (persisted to AsyncStorage) so a phone can point at a local dev box.

import AsyncStorage from "@react-native-async-storage/async-storage";

const STORAGE_KEY = "pulsego.apiUrl";

export const DEFAULT_API_URL = (
  process.env.EXPO_PUBLIC_API_URL || "https://api.pulsego.org"
).replace(/\/$/, "");

export const LOCAL_NEMOTRON_API_URL = (
  process.env.EXPO_PUBLIC_LOCAL_API_URL || "http://localhost:8000"
).replace(/\/$/, "");

export const MAPBOX_TOKEN = process.env.EXPO_PUBLIC_MAPBOX_TOKEN || "";

// In-memory cache so synchronous callers (api.ts) get the live value without an
// await on every request. Seeded from storage on app start via loadApiUrl().
let current = DEFAULT_API_URL;

export function getApiUrl(): string {
  return current;
}

export async function loadApiUrl(): Promise<string> {
  try {
    const saved = await AsyncStorage.getItem(STORAGE_KEY);
    if (saved) current = saved.replace(/\/$/, "");
  } catch {
    // ignore — fall back to default
  }
  return current;
}

export async function setApiUrl(url: string): Promise<void> {
  current = url.replace(/\/$/, "");
  await AsyncStorage.setItem(STORAGE_KEY, current);
}

/** Derive the WebSocket URL from the REST base (http→ws, https→wss). */
export function wsUrl(): string {
  return current.replace(/^http/, "ws") + "/ws";
}
