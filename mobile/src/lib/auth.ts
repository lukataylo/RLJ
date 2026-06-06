// JWT auth: token lives in expo-secure-store. Mirrors orchestrator /auth/login.
// Kept separate from api.ts so api.ts can read the token without a cycle.

import * as SecureStore from "expo-secure-store";

const TOKEN_KEY = "pulsego_token";

// In-memory mirror so api.ts can attach the Bearer header synchronously.
let token: string | null = null;

export function getToken(): string | null {
  return token;
}

export async function loadToken(): Promise<string | null> {
  try {
    token = await SecureStore.getItemAsync(TOKEN_KEY);
  } catch {
    token = null;
  }
  return token;
}

export async function saveToken(value: string): Promise<void> {
  token = value;
  await SecureStore.setItemAsync(TOKEN_KEY, value);
}

export async function clearToken(): Promise<void> {
  token = null;
  await SecureStore.deleteItemAsync(TOKEN_KEY);
}
