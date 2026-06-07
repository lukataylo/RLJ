/**
 * Emoji "sticker" map markers for the deck.gl `IconLayer`.
 *
 * Each marker is a tiny inline SVG (served as a data-URL image): a white teardrop pin or
 * round badge with a colour-accent ring and a full-colour emoji glyph in the middle. SVG
 * (not an icon atlas) keeps markers crisp at any zoom and needs no binary assets; `mask:
 * false` tells deck.gl to keep the emoji full-colour instead of tinting it.
 *
 * API consumed by `MapView.tsx`:
 *   sticker(emoji, [r,g,b], teardrop) -> deck.gl icon def
 *   vehicleEmoji / pickupEmoji / dropoffEmoji / facilityEmoji -> the glyph for an entity
 *
 * (This module backs the emoji-sticker markers MapView already references; it was missing
 * from the tree, which broke the Vite build with "Failed to resolve import ../lib/emojiMarkers".)
 */

export interface StickerIcon {
  /** data-URL of the rendered SVG. */
  url: string;
  /** source image size (px); deck.gl scales it to the layer's `getSize`. */
  width: number;
  height: number;
  /** anchor in source-image px — pin tip for teardrops, centre for badges. */
  anchorX: number;
  anchorY: number;
  /** false → keep the emoji full-colour (no tinting). */
  mask: boolean;
  /** stable id so deck.gl rasterises each distinct sticker only once. */
  id: string;
}

type RGB = [number, number, number];

// MapView re-derives icons on every render; memoise by (shape, emoji, colour).
const _cache = new Map<string, StickerIcon>();

function _dataUrl(svg: string): string {
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}

/**
 * A white **teardrop pin** (`teardrop=true`, anchored at its tip) or **round badge**
 * (`teardrop=false`, centre-anchored) with a coloured ring and the emoji centred inside.
 */
export function sticker(emoji: string, rgb: RGB, teardrop: boolean): StickerIcon {
  const ring = `rgb(${rgb[0] | 0},${rgb[1] | 0},${rgb[2] | 0})`;
  const key = `${teardrop ? "pin" : "badge"}|${emoji}|${ring}`;
  const cached = _cache.get(key);
  if (cached) return cached;

  let svg: string;
  let width: number;
  let height: number;
  let anchorX: number;
  let anchorY: number;

  if (teardrop) {
    width = 64;
    height = 80;
    anchorX = 32;
    anchorY = 78; // tip
    svg =
      `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 64 80">` +
      `<path d="M32 3C16 3 3 16 3 31c0 19 29 46 29 46s29-27 29-46C61 16 48 3 32 3z" ` +
      `fill="#ffffff" stroke="${ring}" stroke-width="5" stroke-linejoin="round"/>` +
      `<text x="32" y="32" font-size="30" text-anchor="middle" dominant-baseline="central">${emoji}</text>` +
      `</svg>`;
  } else {
    width = 64;
    height = 64;
    anchorX = 32;
    anchorY = 32; // centre
    svg =
      `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 64 64">` +
      `<circle cx="32" cy="32" r="27" fill="#ffffff" stroke="${ring}" stroke-width="5"/>` +
      `<text x="32" y="33" font-size="32" text-anchor="middle" dominant-baseline="central">${emoji}</text>` +
      `</svg>`;
  }

  const icon: StickerIcon = {
    url: _dataUrl(svg),
    width,
    height,
    anchorX,
    anchorY,
    mask: false,
    id: key,
  };
  _cache.set(key, icon);
  return icon;
}

/** Courier vehicle glyph (Courier.vehicle_type: "van" | "scooter" | "bike"). */
export function vehicleEmoji(vehicleType?: string): string {
  switch (vehicleType) {
    case "scooter":
      return "🛵";
    case "bike":
      return "🚲";
    case "van":
    default:
      return "🚐";
  }
}

/** Pickup glyph (JobType: "sample_pickup" | "med_delivery"). */
export function pickupEmoji(jobType?: string): string {
  return jobType === "sample_pickup" ? "🧪" : "💊";
}

/** Drop-off glyph — where the item is going (lab for samples, facility for meds). */
export function dropoffEmoji(jobType?: string): string {
  return jobType === "sample_pickup" ? "🔬" : "🏥";
}

/** Facility glyph (Facility.type: hospital | lab | gp | clinic | pharmacy). */
export function facilityEmoji(facilityType?: string): string {
  switch ((facilityType || "").toLowerCase()) {
    case "lab":
      return "🔬";
    case "gp":
      return "🩺";
    case "clinic":
      return "🩹";
    case "pharmacy":
      return "💊";
    case "hospital":
    default:
      return "🏥";
  }
}
