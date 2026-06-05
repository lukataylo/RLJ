// Shared command-center palette — TRON neon edition.
// Hex for CSS-in-JS, RGB tuples for deck.gl layers.
//
// Direction: near-black base, electric cyan primary, hot-orange secondary
// (classic Tron cyan-vs-orange). Status colours keep their meaning:
//   STAT = neon red/orange · urgent = amber · routine = cyan-blue.

import type { Priority, CourierStatus } from "../types";

export const HEX = {
  bg0: "#05070d",
  bg1: "#060a12",
  panel: "rgba(120,200,255,0.045)",
  panelBorder: "rgba(0,229,255,0.22)",
  muted: "#7f93ad",
  text: "#eaf6ff",
  // Tron accents
  cyan: "#18f0ff", // primary
  cyanDeep: "#00e5ff",
  orange: "#ff9d2f", // secondary / contrast
  orangeHot: "#ff7a18",
  blue: "#4ea8ff", // electric mid
  // status
  green: "#23f0c7", // neon mint (idle / good)
  amber: "#ffc24b",
  red: "#ff3b5c",
} as const;

// Priority colours (UI + map). STAT pops neon red, urgent amber, routine cyan-blue.
export const PRIORITY_HEX: Record<Priority, string> = {
  stat: "#ff3b5c",
  urgent: "#ffc24b",
  routine: "#4ea8ff",
};

export const PRIORITY_RGB: Record<Priority, [number, number, number]> = {
  stat: [255, 59, 92],
  urgent: [255, 194, 75],
  routine: [78, 168, 255],
};

export const COURIER_HEX: Record<CourierStatus, string> = {
  idle: "#23f0c7",
  enroute: "#18f0ff",
  offline: "#5d6b82",
};

export const COURIER_RGB: Record<string, [number, number, number]> = {
  idle: [35, 240, 199],
  enroute: [24, 240, 255],
  offline: [93, 107, 130],
};

// Disruptions glow hot-orange (the Tron contrast accent).
export const DISRUPTION_RGB: [number, number, number] = [255, 122, 24];

// Per-class disruption colours so bridge / event / congestion / manual read apart.
export const DISRUPTION_CLASS_RGB: Record<string, [number, number, number]> = {
  bridge: [255, 122, 24], // hot orange
  event: [197, 122, 255], // violet
  congestion: [255, 59, 92], // red
  courier: [255, 194, 75], // amber
  manual: [255, 157, 47], // orange
};

export const DISRUPTION_CLASS_HEX: Record<string, string> = {
  bridge: "#ff7a18",
  event: "#c57aff",
  congestion: "#ff3b5c",
  courier: "#ffc24b",
  manual: "#ff9d2f",
};

// NHS facility colours by kind (cyan-family clinical palette).
export const FACILITY_RGB: Record<string, [number, number, number]> = {
  hospital: [255, 86, 120], // clinical red-pink
  lab: [24, 240, 255], // cyan
  gp: [35, 240, 199], // mint
  clinic: [120, 220, 120], // green
  pharmacy: [78, 168, 255], // blue
};

export const FACILITY_HEX: Record<string, string> = {
  hospital: "#ff5678",
  lab: "#18f0ff",
  gp: "#23f0c7",
  clinic: "#78dc78",
  pharmacy: "#4ea8ff",
};

export function facilityRGB(type: string): [number, number, number] {
  return FACILITY_RGB[type] ?? [180, 200, 230];
}

// Crowdsourced driver / probe fleet — electric cyan dots.
export const DRIVER_RGB: [number, number, number] = [120, 240, 255];
export const DRIVER_HEX = "#78f0ff";

// Junction signal phase colours (green-wave readout).
export const SIGNAL_GREEN_RGB: [number, number, number] = [35, 240, 199];
export const SIGNAL_RED_RGB: [number, number, number] = [255, 59, 92];

// Traffic congestion ramp: neon cyan -> amber -> hot-red over a 0..1 value.
export function congestionRGB(c: number): [number, number, number] {
  const t = Math.max(0, Math.min(1, c));
  const stops: [number, [number, number, number]][] = [
    [0, [24, 240, 255]],
    [0.5, [255, 194, 75]],
    [1, [255, 59, 92]],
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
  return [255, 59, 92];
}
