// Local-metre projection for the Three.js LiDAR scene (ported from Square Mile
// Pulse). Equirectangular lat/lon -> metres around a reference point; accurate
// across the ~1.5 km Square Mile. Returns [x, z] with x = east, z = -north, the
// same frame the citycloud.bin asset is baked in (so facades align with it).

export interface GeoPoint {
  lat: number;
  lon: number;
}

const R = 6378137; // earth radius, metres

export function project(p: GeoPoint, center: GeoPoint): [number, number] {
  const latRad = (center.lat * Math.PI) / 180;
  const x = (((p.lon - center.lon) * Math.PI) / 180) * R * Math.cos(latRad);
  const z = -(((p.lat - center.lat) * Math.PI) / 180) * R;
  return [x, z];
}
