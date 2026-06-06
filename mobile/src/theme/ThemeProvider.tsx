// Theme context: exposes the active Calm Command theme + a toggle, persisted to
// AsyncStorage. Defaults to the OS colour scheme on first run (mirrors the web's
// default-dark / light-toggle behaviour).

import AsyncStorage from "@react-native-async-storage/async-storage";
import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useColorScheme } from "react-native";
import { THEMES, type Theme, type ThemeName } from "./tokens";

const STORAGE_KEY = "pulsego.theme";

interface ThemeContextValue {
  theme: Theme;
  name: ThemeName;
  setTheme: (name: ThemeName) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: THEMES.dark,
  name: "dark",
  setTheme: () => {},
  toggle: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const os = useColorScheme();
  const [name, setName] = useState<ThemeName>("dark");

  useEffect(() => {
    (async () => {
      const saved = (await AsyncStorage.getItem(STORAGE_KEY)) as ThemeName | null;
      if (saved === "dark" || saved === "light") setName(saved);
      else setName(os === "light" ? "light" : "dark");
    })();
    // run once on mount; OS scheme only seeds the very first choice
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setTheme = (next: ThemeName) => {
    setName(next);
    AsyncStorage.setItem(STORAGE_KEY, next).catch(() => {});
  };

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme: THEMES[name],
      name,
      setTheme,
      toggle: () => setTheme(name === "dark" ? "light" : "dark"),
    }),
    [name],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
