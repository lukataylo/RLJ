// Shared command-center palette. Hex for CSS-in-JS, RGB tuples for deck.gl layers.

import type { Priority, CourierStatus } from "../types";

export const HEX = {
  bg0: "#0a0e16",
  bg1: "#0d1117",
  panel: "rgba(255,255,255,0.04)",
  panelBorder: "rgba(255,255,255,0.08)",
  muted: "#8b97a8",
  text: "#ffffff",
  green: "#3ddc84",
  amber: "#ffb020",
  red: "#ff4d4f",
  blue: "#4da6ff",
  cyan: "#22d3ee",
} as const;

// Priority colours (UI + map).
export const PRIORITY_HEX: Record<Priority, string> = {
  stat: "#ff4d4f",
  urgent: "#ffb020",
  routine: "#4da6ff",
};

export const PRIORITY_RGB: Record<Priority, [number, number, number]> = {
  stat: [255, 77, 79],
  urgent: [255, 176, 32],
  routine: [77, 166, 255],
};

export const COURIER_HEX: Record<CourierStatus, string> = {
  idle: "#3ddc84",
  enroute: "#22d3ee",
  offline: "#6b7689",
};

export const COURIER_RGB: Record<string, [number, number, number]> = {
  idle: [61, 220, 132],
  enroute: [34, 211, 238],
  offline: [107, 118, 137],
};

export const DISRUPTION_RGB: [number, number, number] = [255, 77, 79];

// Traffic congestion ramp: green -> amber -> red over a 0..1 value.
export function congestionRGB(c: number): [number, number, number] {
  const t = Math.max(0, Math.min(1, c));
  const stops: [number, [number, number, number]][] = [
    [0, [61, 220, 132]],
    [0.5, [255, 176, 32]],
    [1, [255, 77, 79]],
  ];
  for (let i = 0; i < stops.length - 1; i++) {
    const [a, ca] = stops[i];
    const [b, cb] = stops[i + 1];
    if (t <= b) {
      const k = (t - a) / (b - a || 1);
      return [
        Math.round(ca[0] + (cb[0] - ca[0]) * k),
        Math.round(ca[1] + (cb[1] - ca[1]) * k),
        Math.round(ca[2] + (cb[2] - ca[2]) * k),
      ];
    }
  }
  return [255, 77, 79];
}
