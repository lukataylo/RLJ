// Minimal inline-SVG icon set (stroke-based, currentColor) so the courier
// surfaces read bold + consistent without pulling in an icon font.
type P = { size?: number; className?: string };
const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
});

export const IconNavigate = ({ size = 22, className }: P) => (
  <svg {...base(size)} className={className}><path d="M3 11l19-9-9 19-2-8-8-2z" /></svg>
);
export const IconStop = ({ size = 22, className }: P) => (
  <svg {...base(size)} className={className}><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
);
export const IconAlert = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}><path d="M12 3 2 20h20L12 3z" /><path d="M12 10v4" /><path d="M12 17.5v.5" /></svg>
);
export const IconSnow = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className}><path d="M12 2v20M4 6l16 12M20 6 4 18" /></svg>
);
export const IconClock = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
);
export const IconPin = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className}><path d="M12 21s7-6.3 7-11a7 7 0 1 0-14 0c0 4.7 7 11 7 11z" /><circle cx="12" cy="10" r="2.5" /></svg>
);

// --- maneuver arrows -------------------------------------------------------
const Arrow = ({ size, d }: { size: number; d: string }) => (
  <svg {...base(size)}>{<path d={d} />}</svg>
);

export function ManeuverIcon({ modifier, type, size = 30 }: { modifier?: string; type?: string; size?: number }) {
  if (type === "arrive")
    return <svg {...base(size)}><path d="M5 21V4l9 3-9 3" /><path d="M5 14h14" /></svg>; // flag
  const m = modifier ?? "";
  // up-then-turn glyphs
  if (m.includes("sharp left")) return <Arrow size={size} d="M16 20V11a4 4 0 0 0-4-4H7m0 0 3 3M7 7l3-3" />;
  if (m.includes("sharp right")) return <Arrow size={size} d="M8 20v-9a4 4 0 0 1 4-4h5m0 0-3 3m3-3-3-3" />;
  if (m.includes("slight left")) return <Arrow size={size} d="M14 20v-6a5 5 0 0 0-2-4l-2-1m0 0 3 0m-3 0 0 3" />;
  if (m.includes("slight right")) return <Arrow size={size} d="M10 20v-6a5 5 0 0 1 2-4l2-1m0 0-3 0m3 0 0 3" />;
  if (m.includes("left")) return <Arrow size={size} d="M15 20v-7a3 3 0 0 0-3-3H6m0 0 3.5 3.5M6 10l3.5-3.5" />;
  if (m.includes("right")) return <Arrow size={size} d="M9 20v-7a3 3 0 0 1 3-3h6m0 0-3.5 3.5M18 10l-3.5-3.5" />;
  return <Arrow size={size} d="M12 20V5m0 0 5 5M12 5 7 10" />; // straight / depart
}
