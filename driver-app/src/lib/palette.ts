// Shared TRON neon palette — kept in sync with frontend/src/lib/palette.ts.
// Near-black base, electric cyan primary, hot-orange secondary.

export const HEX = {
  bg0: "#05070d",
  bg1: "#060a12",
  panel: "rgba(120,200,255,0.045)",
  panelBorder: "rgba(0,229,255,0.22)",
  muted: "#8aa0bd",
  text: "#eaf6ff",
  // Tron accents
  cyan: "#18f0ff", // primary
  cyanDeep: "#00e5ff",
  orange: "#ff9d2f", // secondary / contrast
  orangeHot: "#ff7a18",
  blue: "#4ea8ff", // electric mid
  // status
  green: "#23f0c7", // neon mint (good / go)
  amber: "#ffc24b",
  red: "#ff3b5c",
} as const;

/** Congestion ramp 0..1: neon cyan (free-flow) -> amber -> hot-red (jammed). */
export function congestionHex(c: number): string {
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
      const r = Math.round(ca[0] + (cb[0] - ca[0]) * k);
      const g = Math.round(ca[1] + (cb[1] - ca[1]) * k);
      const bl = Math.round(ca[2] + (cb[2] - ca[2]) * k);
      return `rgb(${r},${g},${bl})`;
    }
  }
  return "#ff3b5c";
}
