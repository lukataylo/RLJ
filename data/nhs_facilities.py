"""Real London NHS facility nodes (pickup/dropoff), geocoded by postcode.

NHS / ODS facility datasets ship **postcodes, not coordinates**, so this module
geocodes them with the free, no-key **postcodes.io** bulk API and normalizes the
result into the repo's facilities schema (see ``quality.FACILITIES_SCHEMA``):

    {"id": str, "name": str, "type": one of quality.FACILITY_TYPES,
     "lat": float, "lng": float}   # lat/lng inside quality.LONDON_BBOX

Geocoder (free, no key):
  * postcodes.io bulk: POST https://api.postcodes.io/postcodes
    body {"postcodes": ["SE1 7EH", ...]} -> per-postcode latitude/longitude.

Facility list — full pull (planned, to replace the embedded seed below):
  The authoritative facility lists are published by NHS ODS / data.gov.uk as
  CSVs keyed by postcode (no coordinates). Wire these for the complete pull:
    * NHS ODS "Pathology Laboratories" (epraccur-style CSV):
      https://www.odsdatapoint.com/  /  https://digital.nhs.uk/services/organisation-data-service/export-data-files
      data.gov.uk: https://www.data.gov.uk/dataset/677c6cda-c50a-4eb1-b07f-2c97d4e9 accept
    * NHS "Hospital" sites:
      https://www.data.gov.uk/dataset/f4191c4d-a86c-4c5a/hospitals  (ODS ``ets.csv``)
    * NHS "GP Practices" (epraccur.csv):
      https://digital.nhs.uk/services/organisation-data-service/export-data-files/csv-downloads/gp-and-gp-practice-related-data
  The pipeline below (fetch list -> extract postcode+type -> bulk geocode ->
  bbox filter -> normalize) is the real one; only the *source* of the list is
  the embedded seed until the ODS CSV pull is wired.

Offline-safe: any network failure falls back to the embedded seed coordinates so
this module never raises and always returns valid records.

CLI: ``python data/nhs_facilities.py`` prints the count and a sample record.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

import requests

import quality

DEFAULT_TIMEOUT_S = 10.0
_USER_AGENT = "RLJ medical-logistics-demo/1.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_postcode(pc: str) -> str:
    """Canonical key for a postcode: uppercase, no internal spaces."""
    return (pc or "").upper().replace(" ", "")


# --------------------------------------------------------------------------- #
# Embedded seed: ~20 real, well-known London NHS sites.
# (name, postcode, type, bundled lat, bundled lng)
# `bundled_lat/lng` are approximate real coordinates used ONLY as the offline
# fallback when postcodes.io is unreachable. The live path overwrites them with
# the geocoder's coordinates. SEED — replace the *list source* with the ODS pull
# documented in the module docstring; the geocode/normalize pipeline is real.
# --------------------------------------------------------------------------- #
SEED_FACILITIES: list[dict] = [
    # ---- hospitals -------------------------------------------------------- #
    {"id": "RJ1-STH", "name": "St Thomas' Hospital", "type": "hospital", "postcode": "SE1 7EH", "bundled_lat": 51.4980, "bundled_lng": -0.1188},
    {"id": "RJ1-GUY", "name": "Guy's Hospital", "type": "hospital", "postcode": "SE1 9RT", "bundled_lat": 51.5033, "bundled_lng": -0.0875},
    {"id": "R1H-RLH", "name": "Royal London Hospital", "type": "hospital", "postcode": "E1 1FR", "bundled_lat": 51.5190, "bundled_lng": -0.0590},
    {"id": "RRV-UCH", "name": "University College Hospital (UCLH)", "type": "hospital", "postcode": "NW1 2BU", "bundled_lat": 51.5246, "bundled_lng": -0.1357},
    {"id": "RJZ-KCH", "name": "King's College Hospital", "type": "hospital", "postcode": "SE5 9RS", "bundled_lat": 51.4685, "bundled_lng": -0.0937},
    {"id": "RRV-BART", "name": "St Bartholomew's Hospital", "type": "hospital", "postcode": "EC1A 7BE", "bundled_lat": 51.5176, "bundled_lng": -0.1003},
    {"id": "RYJ-CXH", "name": "Charing Cross Hospital", "type": "hospital", "postcode": "W6 8RF", "bundled_lat": 51.4870, "bundled_lng": -0.2186},
    {"id": "RAL-RFH", "name": "Royal Free Hospital", "type": "hospital", "postcode": "NW3 2QG", "bundled_lat": 51.5530, "bundled_lng": -0.1647},
    {"id": "RQM-CWH", "name": "Chelsea and Westminster Hospital", "type": "hospital", "postcode": "SW10 9NH", "bundled_lat": 51.4842, "bundled_lng": -0.1817},
    {"id": "RYJ-SMH", "name": "St Mary's Hospital, Paddington", "type": "hospital", "postcode": "W2 1NY", "bundled_lat": 51.5170, "bundled_lng": -0.1736},
    {"id": "RYJ-HMH", "name": "Hammersmith Hospital", "type": "hospital", "postcode": "W12 0HS", "bundled_lat": 51.5167, "bundled_lng": -0.2360},
    {"id": "RKE-WHT", "name": "Whittington Hospital", "type": "hospital", "postcode": "N19 5NF", "bundled_lat": 51.5658, "bundled_lng": -0.1390},
    {"id": "RQX-HOM", "name": "Homerton University Hospital", "type": "hospital", "postcode": "E9 6SR", "bundled_lat": 51.5497, "bundled_lng": -0.0445},
    # ---- pathology / labs ------------------------------------------------- #
    {"id": "LAB-HSL", "name": "Health Services Laboratories (The Halo Building)", "type": "lab", "postcode": "WC1H 9AX", "bundled_lat": 51.5290, "bundled_lng": -0.1290},
    {"id": "LAB-TDL", "name": "The Doctors Laboratory (TDL)", "type": "lab", "postcode": "W1T 4EU", "bundled_lat": 51.5210, "bundled_lng": -0.1370},
    {"id": "LAB-SYN", "name": "Synnovis Pathology (Guy's)", "type": "lab", "postcode": "SE1 9RT", "bundled_lat": 51.5030, "bundled_lng": -0.0882},
    # ---- GP surgeries / clinics ------------------------------------------ #
    {"id": "GP-HURLEY", "name": "The Hurley Clinic", "type": "gp", "postcode": "SE11 4HJ", "bundled_lat": 51.4920, "bundled_lng": -0.1100},
    {"id": "GP-HAMP", "name": "Hampstead Group Practice", "type": "gp", "postcode": "NW3 2QU", "bundled_lat": 51.5550, "bundled_lng": -0.1780},
    # ---- pharmacies ------------------------------------------------------- #
    {"id": "PH-JBC", "name": "John Bell & Croyden Pharmacy", "type": "pharmacy", "postcode": "W1G 8NY", "bundled_lat": 51.5176, "bundled_lng": -0.1510},
    {"id": "PH-BOOTS-PIC", "name": "Boots Pharmacy, Piccadilly Circus", "type": "pharmacy", "postcode": "W1B 5LA", "bundled_lat": 51.5098, "bundled_lng": -0.1342},
]


# --------------------------------------------------------------------------- #
# postcodes.io geocoder adapter (mirrors integrations.JsonFeedClient style)
# --------------------------------------------------------------------------- #
@dataclass
class PostcodesIoClient:
    """Tiny requests wrapper around the free, no-key postcodes.io bulk API."""

    base_url: str = "https://api.postcodes.io"
    timeout_s: float = DEFAULT_TIMEOUT_S
    session: requests.Session | None = None

    def bulk_lookup(self, postcodes: Sequence[str]) -> dict[str, tuple[float, float]]:
        """Geocode many postcodes at once.

        Returns ``{normalized_postcode: (lat, lng)}``. postcodes.io accepts up to
        100 postcodes per request, so we chunk. Postcodes that fail to resolve
        are simply omitted from the result.
        """
        out: dict[str, tuple[float, float]] = {}
        session = self.session or requests.Session()
        url = self.base_url.rstrip("/") + "/postcodes"
        cleaned = [p for p in postcodes if p]
        for start in range(0, len(cleaned), 100):
            batch = cleaned[start : start + 100]
            response = session.post(
                url,
                json={"postcodes": list(batch)},
                timeout=self.timeout_s,
                headers={"user-agent": _USER_AGENT},
            )
            response.raise_for_status()
            payload = response.json()
            for row in payload.get("result") or []:
                query = row.get("query")
                result = row.get("result")
                if not result:
                    continue
                lat = result.get("latitude")
                lng = result.get("longitude")
                if lat is None or lng is None:
                    continue
                key = _norm_postcode(result.get("postcode") or query or "")
                if key:
                    out[key] = (float(lat), float(lng))
        return out


# --------------------------------------------------------------------------- #
# pipeline: list -> geocode -> bbox filter -> normalize
# --------------------------------------------------------------------------- #
def _seed_list(limit: int | None = None) -> list[dict]:
    rows = [dict(r) for r in SEED_FACILITIES]
    if limit is not None:
        rows = rows[:limit]
    return rows


def normalize_records(
    rows: Iterable[dict],
    coords: dict[str, tuple[float, float]],
) -> list[dict]:
    """Join the facility rows with geocoded coordinates and normalize.

    For each row we prefer the geocoded coordinate (keyed by normalized
    postcode); if absent, we fall back to the row's ``bundled_lat/lng``. Rows
    whose final coordinate is outside :data:`quality.LONDON_BBOX` are dropped.
    Output records contain exactly ``{id, name, type, lat, lng}``.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        fid = row.get("id")
        if not fid or fid in seen:
            continue
        ftype = row.get("type")
        if ftype not in quality.FACILITY_TYPES:
            continue
        key = _norm_postcode(row.get("postcode", ""))
        if key in coords:
            lat, lng = coords[key]
        elif row.get("bundled_lat") is not None and row.get("bundled_lng") is not None:
            lat, lng = float(row["bundled_lat"]), float(row["bundled_lng"])
        else:
            continue
        if not quality.point_in_bbox(lat, lng):
            continue
        seen.add(fid)
        out.append(
            {
                "id": str(fid),
                "name": str(row.get("name", "")),
                "type": ftype,
                "lat": float(lat),
                "lng": float(lng),
            }
        )
    return out


def _bundled_coords(rows: Iterable[dict]) -> dict[str, tuple[float, float]]:
    """Coordinate map from the embedded seed (offline fallback)."""
    coords: dict[str, tuple[float, float]] = {}
    for row in rows:
        key = _norm_postcode(row.get("postcode", ""))
        if key and row.get("bundled_lat") is not None and row.get("bundled_lng") is not None:
            coords[key] = (float(row["bundled_lat"]), float(row["bundled_lng"]))
    return coords


def fetch_nhs_london(
    *,
    allow_network: bool = True,
    limit: int | None = None,
    client: PostcodesIoClient | None = None,
) -> list[dict]:
    """Return real London NHS facility records, geocoded and bbox-filtered.

    Pipeline: facility list (embedded seed; replace source with the ODS CSV pull
    documented in the module docstring) -> postcodes.io bulk geocode -> filter to
    :data:`quality.LONDON_BBOX` -> normalize to the facilities schema.

    Offline-safe: with ``allow_network=False`` or on any geocoder failure, falls
    back to the embedded seed coordinates. Never raises.
    """
    rows = _seed_list(limit)
    postcodes = [r["postcode"] for r in rows if r.get("postcode")]

    coords: dict[str, tuple[float, float]] = {}
    if allow_network and postcodes:
        try:
            geocoder = client or PostcodesIoClient()
            coords = geocoder.bulk_lookup(postcodes)
        except Exception:
            coords = {}

    # Fill any gaps (failed geocodes / offline) from bundled coordinates.
    bundled = _bundled_coords(rows)
    for key, value in bundled.items():
        coords.setdefault(key, value)

    return normalize_records(rows, coords)


if __name__ == "__main__":
    records = fetch_nhs_london(allow_network=True)
    print(f"{len(records)} NHS facilities")
    if records:
        import json

        print(json.dumps(records[0], indent=2))
