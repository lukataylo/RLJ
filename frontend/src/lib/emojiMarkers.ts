// Sticker-style emoji map markers for deck.gl IconLayer.
//
// Each marker is rasterised once to an offscreen canvas — a glossy white "sticker"
// (a round badge, or a teardrop pin) with a soft drop-shadow and a coloured accent
// ring — with the emoji centred on top, the way Apple/Google corner-style map markers
// look. The canvas is handed to IconLayer as a data-URL icon. Results are cached by a
// composite key, so we only pay the rasterisation cost once per (emoji × colour × shape).

type RGB = [number, number, number];

export interface StickerIcon {
  id: string;
  url: string;
  width: number;
  height: number;
  anchorX: number;
  anchorY: number;
}

const cache = new Map<string, StickerIcon>();

// Rasterisation resolution. IconLayer downsamples to getSize px, so render large for
// crisp emoji at any zoom, then let the GPU scale down.
const RES = 128;
const EMOJI_FONT = `"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif`;

function rgba(c: RGB, a = 1): string {
  return `rgba(${c[0]},${c[1]},${c[2]},${a})`;
}

/**
 * A sticker icon: a white badge (round, or a teardrop pin) with a coloured accent ring
 * and the emoji centred in it.
 *
 * @param emoji   the glyph to stamp (e.g. "🛵", "🩸")
 * @param accent  ring / pin-pointer colour (status or priority RGB)
 * @param pin     true → teardrop pin whose tip sits on the coordinate; false → round badge centred on it
 */
export function sticker(emoji: string, accent: RGB, pin = false): StickerIcon {
  const key = `${pin ? "pin" : "badge"}|${emoji}|${accent.join(",")}`;
  const hit = cache.get(key);
  if (hit) return hit;

  const S = RES;
  const cv = document.createElement("canvas");
  cv.width = S;
  cv.height = S;
  const ctx = cv.getContext("2d");
  if (!ctx) {
    // Headless / no-canvas fallback: a 1×1 transparent icon (never happens in browsers).
    const empty: StickerIcon = { id: key, url: "", width: 1, height: 1, anchorX: 0, anchorY: 0 };
    cache.set(key, empty);
    return empty;
  }

  const cx = S / 2;
  const r = S * 0.3;
  const cy = pin ? S * 0.36 : S * 0.46; // pins sit higher so the tail has room
  const nubBaseY = cy + r * 0.55;
  const nubTipY = cy + r * 1.95;

  // 1. Unified white silhouette (badge + optional tail) with one soft shadow.
  ctx.save();
  ctx.shadowColor = "rgba(0,0,0,0.5)";
  ctx.shadowBlur = S * 0.07;
  ctx.shadowOffsetY = S * 0.025;
  ctx.fillStyle = "#ffffff";
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  if (pin) {
    ctx.moveTo(cx - r * 0.5, nubBaseY);
    ctx.lineTo(cx + r * 0.5, nubBaseY);
    ctx.lineTo(cx, nubTipY);
    ctx.closePath();
  }
  ctx.fill();
  ctx.restore();

  // 2. Accent-coloured pin tail (drawn over the white tail so the pointer reads coloured).
  if (pin) {
    ctx.fillStyle = rgba(accent);
    ctx.beginPath();
    ctx.moveTo(cx - r * 0.42, nubBaseY - r * 0.1);
    ctx.lineTo(cx + r * 0.42, nubBaseY - r * 0.1);
    ctx.lineTo(cx, nubTipY);
    ctx.closePath();
    ctx.fill();
  }

  // 3a. Faint outer hairline so the white badge still reads on a light basemap.
  ctx.beginPath();
  ctx.arc(cx, cy, r + S * 0.02, 0, Math.PI * 2);
  ctx.lineWidth = S * 0.012;
  ctx.strokeStyle = "rgba(0,0,0,0.18)";
  ctx.stroke();

  // 3b. Accent ring around the badge.
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.lineWidth = S * 0.05;
  ctx.strokeStyle = rgba(accent);
  ctx.stroke();

  // 4. Emoji, centred in the badge.
  ctx.font = `${Math.round(r * 1.2)}px ${EMOJI_FONT}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(emoji, cx, cy + S * 0.005);

  const icon: StickerIcon = {
    id: key,
    url: cv.toDataURL(),
    width: S,
    height: S,
    anchorX: cx,
    anchorY: pin ? nubTipY : cy, // pin tip / badge centre lands on the coordinate
  };
  cache.set(key, icon);
  return icon;
}

// ---- Emoji vocabulary --------------------------------------------------------

// Courier vehicle → emoji (defaults to the van/truck).
export const VEHICLE_EMOJI: Record<string, string> = {
  van: "🚚",
  scooter: "🛵",
  bike: "🚲",
};

export function vehicleEmoji(vehicle: string | undefined): string {
  return VEHICLE_EMOJI[vehicle ?? "van"] ?? "🚚";
}

// Job node → emoji, by job type. Pickup = where we collect, dropoff = where we deliver.
export const PICKUP_EMOJI: Record<string, string> = {
  sample_pickup: "🩸", // pathology sample collected from a ward/GP
  med_delivery: "💊", // medication collected from a pharmacy
};
export const DROPOFF_EMOJI: Record<string, string> = {
  sample_pickup: "🔬", // sample delivered to the lab
  med_delivery: "🏥", // medication delivered to the hospital/patient
};

export function pickupEmoji(jobType: string | undefined): string {
  return PICKUP_EMOJI[jobType ?? ""] ?? "📍";
}
export function dropoffEmoji(jobType: string | undefined): string {
  return DROPOFF_EMOJI[jobType ?? ""] ?? "🏁";
}

// NHS facility → emoji (atmosphere markers).
export const FACILITY_EMOJI: Record<string, string> = {
  hospital: "🏥",
  lab: "🔬",
  gp: "🩺",
  clinic: "🩹",
  pharmacy: "💊",
};

export function facilityEmoji(type: string | undefined): string {
  return FACILITY_EMOJI[type ?? ""] ?? "📍";
}
