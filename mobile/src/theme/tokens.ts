// PulseGo "Calm Command" design tokens — ported verbatim from the web app
// (frontend/src/index.css :root + [data-theme="light"], frontend/src/lib/palette.ts)
// so the native app reads as the same product. Pulse Red accent on a charcoal
// (dark) or cream (light) base; Poppins for headings/numerals, Inter for body.

export type ThemeName = "dark" | "light";

export interface Theme {
  name: ThemeName;
  // accent (Pulse Red — identical across themes)
  accent: string;
  accentPress: string;
  accentContrast: string;
  accentSoft: string;
  // base surfaces
  bg: string;
  bg1: string;
  panel: string;
  panelSolid: string;
  hair: string;
  hairStrong: string;
  fill: string;
  fill2: string;
  // text
  text: string;
  muted: string;
  faint: string;
  // status palette
  green: string;
  amber: string;
  // map
  mapBg: string;
  // geometry
  radius: number;
  radiusCard: number;
  radiusBtn: number;
}

export const DARK: Theme = {
  name: "dark",
  accent: "#ff3b30",
  accentPress: "#e22e24",
  accentContrast: "#ffffff",
  accentSoft: "rgba(255,59,48,0.14)",
  bg: "#0e0d0c",
  bg1: "#181715",
  panel: "rgba(27,25,23,0.82)",
  panelSolid: "rgba(21,19,18,0.96)",
  hair: "rgba(255,246,238,0.10)",
  hairStrong: "rgba(255,246,238,0.18)",
  fill: "rgba(255,246,238,0.06)",
  fill2: "rgba(255,246,238,0.10)",
  text: "#fff6ee",
  muted: "#9b948b",
  faint: "#5d574f",
  green: "#2bb37c",
  amber: "#f5a623",
  mapBg: "#0e0d0c",
  radius: 18,
  radiusCard: 13,
  radiusBtn: 11,
};

export const LIGHT: Theme = {
  ...DARK,
  name: "light",
  bg: "#f6ece0",
  bg1: "#fffaf4",
  panel: "rgba(255,255,255,0.92)",
  panelSolid: "rgba(255,255,255,0.97)",
  hair: "rgba(17,17,17,0.09)",
  hairStrong: "rgba(17,17,17,0.16)",
  fill: "rgba(17,17,17,0.045)",
  fill2: "rgba(17,17,17,0.08)",
  text: "#1a1410",
  muted: "#7c736a",
  faint: "#a89d90",
  green: "#1a9e63",
  mapBg: "#e9ded0",
};

export const THEMES: Record<ThemeName, Theme> = { dark: DARK, light: LIGHT };

// Priority colours (UI + map) — palette.ts PRIORITY_HEX.
// stat pops red, urgent amber, routine olive.
export const PRIORITY_HEX = {
  stat: "#FF4D4D",
  urgent: "#E0A23A",
  routine: "#9FB85A",
} as const;

// Job status accent colours for pills / history outcomes.
export const STATUS_HEX = {
  new: "#9b948b",
  assigned: "#64D2FF",
  in_transit: "#BFE36B",
  delivered: "#2bb37c",
  failed: "#FF4D4D",
} as const;

// Fonts (loaded via @expo-google-fonts in the root layout).
export const FONT = {
  head: "Poppins_700Bold",
  headSemi: "Poppins_600SemiBold",
  headMed: "Poppins_500Medium",
  body: "Inter_400Regular",
  bodyMed: "Inter_500Medium",
  bodySemi: "Inter_600SemiBold",
  bodyBold: "Inter_700Bold",
} as const;

// react-native-maps dark style JSON — charcoal base to echo --map-bg #0e0d0c.
export const MAP_STYLE_DARK = [
  { elementType: "geometry", stylers: [{ color: "#15130f" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#9b948b" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#0e0d0c" }] },
  { featureType: "poi", stylers: [{ visibility: "off" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
  {
    featureType: "road",
    elementType: "geometry",
    stylers: [{ color: "#26221d" }],
  },
  {
    featureType: "road.arterial",
    elementType: "geometry",
    stylers: [{ color: "#2f2a23" }],
  },
  {
    featureType: "road.highway",
    elementType: "geometry",
    stylers: [{ color: "#3a332a" }],
  },
  {
    featureType: "road",
    elementType: "labels.text.fill",
    stylers: [{ color: "#7c736a" }],
  },
  {
    featureType: "water",
    elementType: "geometry",
    stylers: [{ color: "#0a1418" }],
  },
  {
    featureType: "administrative",
    elementType: "geometry",
    stylers: [{ color: "#5d574f" }],
  },
];
