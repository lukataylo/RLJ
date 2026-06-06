// Shared command-center palette — "Direction C" mission-control edition.
// Dark, green-tinted, YELLOW primary (NOT blue, NOT neon-tron).
// Hex for CSS-in-JS, RGB tuples for deck.gl layers.
//
//   PRIMARY ACTION = yellow #F2C21A · positive/efficiency = lime #BFE36B/#AEE36B
//   danger = red #FF4D4D (#E8503A deeper for lines) · urgent = amber #E0A23A
//   routine = olive #9FB85A · text #E8EDE6 · muted #7E8A82 · faint #4A554E

import type { Priority, CourierStatus } from "../types";

export const HEX = {
  bg0: "#05090b",
  bg1: "#0a0f10",
  panel: "rgba(10,15,16,0.72)",
  panelBorder: "rgba(200,220,180,0.12)",
  muted: "#7E8A82",
  faint: "#4A554E",
  text: "#E8EDE6",
  // Direction-C accents
  yellow: "#F2C21A", // PRIMARY action
  lime: "#BFE36B", // positive / efficiency
  limeAlt: "#AEE36B",
  amber: "#E0A23A", // urgent / mid
  olive: "#9FB85A", // routine
  red: "#FF4D4D", // stat / danger
  redDeep: "#E8503A", // deeper red for lines
  // ---- legacy keys kept so older components keep compiling ----
  cyan: "#BFE36B",
  cyanDeep: "#AEE36B",
  orange: "#E0A23A",
  orangeHot: "#E8503A",
  blue: "#9FB85A",
  green: "#BFE36B",
} as const;

// Priority colours (UI + map). STAT pops red, urgent amber, routine olive.
export const PRIORITY_HEX: Record<Priority, string> = {
  stat: "#FF4D4D",
  urgent: "#E0A23A",
  routine: "#9FB85A",
};

export const PRIORITY_RGB: Record<Priority, [number, number, number]> = {
  stat: [255, 77, 77],
  urgent: [224, 162, 58],
  routine: [159, 184, 90],
};

export const COURIER_HEX: Record<CourierStatus, string> = {
  idle: "#9FB85A",
  enroute: "#BFE36B",
  offline: "#5d6b62",
};

export const COURIER_RGB: Record<string, [number, number, number]> = {
  idle: [159, 184, 90],
  enroute: [191, 227, 107],
  offline: [93, 107, 98],
};

// Disruptions glow the deep-red line accent.
export const DISRUPTION_RGB: [number, number, number] = [232, 80, 58];

// Per-class disruption colours so bridge / event / congestion / manual read apart.
export const DISRUPTION_CLASS_RGB: Record<string, [number, number, number]> = {
  bridge: [242, 194, 26], // yellow
  event: [224, 162, 58], // amber
  congestion: [255, 77, 77], // red
  courier: [224, 162, 58], // amber
  manual: [232, 80, 58], // deep red
};

export const DISRUPTION_CLASS_HEX: Record<string, string> = {
  bridge: "#F2C21A",
  event: "#E0A23A",
  congestion: "#FF4D4D",
  courier: "#E0A23A",
  manual: "#E8503A",
};

// NHS facility colours by kind.
export const FACILITY_RGB: Record<string, [number, number, number]> = {
  hospital: [255, 77, 77], // red
  lab: [242, 194, 26], // yellow
  gp: [191, 227, 107], // lime
  clinic: [159, 184, 90], // olive
  pharmacy: [224, 162, 58], // amber
};

export const FACILITY_HEX: Record<string, string> = {
  hospital: "#FF4D4D",
  lab: "#F2C21A",
  gp: "#BFE36B",
  clinic: "#9FB85A",
  pharmacy: "#E0A23A",
};

export function facilityRGB(type: string): [number, number, number] {
  return FACILITY_RGB[type] ?? [180, 200, 160];
}

// Crowdsourced driver / probe fleet — lime dots.
export const DRIVER_RGB: [number, number, number] = [174, 227, 107];
export const DRIVER_HEX = "#AEE36B";

// Google-Maps-style route congestion colouring: calm neutral grey-blue for
// free-flowing segments, red where the path passes through live congestion.
export const ROUTE_NEUTRAL_RGB: [number, number, number] = [107, 119, 133]; // #6B7785
export const ROUTE_CONGESTED_RGB: [number, number, number] = [255, 77, 77]; // #FF4D4D
// Vivid blue for a focused/selected route — stands out while others dim.
export const ROUTE_HIGHLIGHT_RGB: [number, number, number] = [42, 127, 255]; // #2A7FFF
export const ROUTE_NEUTRAL_HEX = "#6B7785";
export const ROUTE_CONGESTED_HEX = "#FF4D4D";
export const ROUTE_HIGHLIGHT_HEX = "#2A7FFF";

// Junction signal phase colours.
export const SIGNAL_GREEN_RGB: [number, number, number] = [191, 227, 107];
export const SIGNAL_RED_RGB: [number, number, number] = [255, 77, 77];

// GB10 Nemotron traffic-signal recommendation colours, keyed by action.
//   green_wave = lime #BFE36B · retime = amber #E0A23A
//   hold = red #FF4D4D · clear = cyan #64D2FF
export const SIGNAL_ACTION_RGB: Record<string, [number, number, number]> = {
  green_wave: [191, 227, 107],
  retime: [224, 162, 58],
  hold: [255, 77, 77],
  clear: [100, 210, 255],
};

export const SIGNAL_ACTION_HEX: Record<string, string> = {
  green_wave: "#BFE36B",
  retime: "#E0A23A",
  hold: "#FF4D4D",
  clear: "#64D2FF",
};

export function signalActionRGB(action: string): [number, number, number] {
  return SIGNAL_ACTION_RGB[action] ?? [232, 237, 230];
}

// Traffic congestion ramp: lime -> amber -> deep-red over a 0..1 value (Waze-style).
export function congestionRGB(c: number): [number, number, number] {
  const t = Math.max(0, Math.min(1, c));
  const stops: [number, [number, number, number]][] = [
    [0, [174, 227, 107]],
    [0.5, [224, 162, 58]],
    [1, [232, 80, 58]],
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
  return [232, 80, 58];
}
