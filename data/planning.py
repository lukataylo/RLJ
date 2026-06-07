"""Major planning developments integration (offline-safe, live-with-fallback).

Large planning applications are a leading indicator of future road impact: a major
construction or infrastructure scheme means hoardings, lane takes, crane oversail and
HGV movements that will affect a courier's routes for months. We surface the *major*
schemes near the operating area so dispatch can anticipate them.

Live source: the national Planning Data platform (``planning.data.gov.uk``), which is
keyless and supports a location-filtered ``entity.json`` query. The committed demo uses
a representative offline bundle of well-known central-London major developments so the
first-minute scenario works with no network.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
ROOT = DATA_DIR.parent
PLANNING_PATH = DATA_DIR / "planning.json"
FRONTEND_PLANNING_PATH = ROOT / "frontend" / "public" / "data" / "planning.json"

BUNDLE_FETCHED_AT = "2026-06-01T00:00:00+00:00"
SOURCE = "live-with-fallback"

# Allowed scales (shared with the frontend colour ramp): how much road impact the
# scheme is likely to bring while under construction.
PLANNING_SCALES = ("large", "major")

# Representative major London developments (public schemes, approximate centroids,
# all inside the London bbox). Used when the live Planning Data fetch is unavailable.
BUNDLED_PLANNING = [
    {
        "id": "pln-nine-elms",
        "reference": "2024/NE/0421",
        "description": "Nine Elms / Battersea — mixed-use towers, ongoing public-realm and highway works",
        "lat": 51.4817,
        "lng": -0.1445,
        "status": "approved",
        "authority": "Wandsworth",
        "received_date": "2024-02-14",
        "decision_date": "2024-09-03",
        "scale": "major",
        "category": "mixed_use",
    },
    {
        "id": "pln-euston-hs2",
        "reference": "2023/EU/1187",
        "description": "Euston — HS2 station enabling works, sustained HGV movements and lane closures",
        "lat": 51.5281,
        "lng": -0.1337,
        "status": "approved",
        "authority": "Camden",
        "received_date": "2023-05-20",
        "decision_date": "2023-11-30",
        "scale": "major",
        "category": "infrastructure",
    },
    {
        "id": "pln-canada-water",
        "reference": "2024/CW/0093",
        "description": "Canada Water masterplan — phased town-centre redevelopment",
        "lat": 51.4980,
        "lng": -0.0497,
        "status": "approved",
        "authority": "Southwark",
        "received_date": "2024-01-08",
        "decision_date": "2024-06-18",
        "scale": "major",
        "category": "mixed_use",
    },
    {
        "id": "pln-olympia",
        "reference": "2023/OL/0762",
        "description": "Olympia London — exhibition-centre redevelopment, Hammersmith Road impact",
        "lat": 51.4969,
        "lng": -0.2103,
        "status": "under_construction",
        "authority": "Hammersmith & Fulham",
        "received_date": "2022-09-12",
        "decision_date": "2023-03-27",
        "scale": "major",
        "category": "commercial",
    },
    {
        "id": "pln-earls-court",
        "reference": "2024/EC/0310",
        "description": "Earls Court regeneration — large-scale demolition and build, phased road works",
        "lat": 51.4895,
        "lng": -0.1995,
        "status": "approved",
        "authority": "Kensington & Chelsea",
        "received_date": "2024-03-01",
        "decision_date": "2024-10-09",
        "scale": "major",
        "category": "mixed_use",
    },
    {
        "id": "pln-silvertown",
        "reference": "2023/SV/0588",
        "description": "Silvertown Quays — riverside redevelopment, Tidal Basin Road works",
        "lat": 51.5020,
        "lng": 0.0260,
        "status": "under_construction",
        "authority": "Newham",
        "received_date": "2022-11-04",
        "decision_date": "2023-05-15",
        "scale": "large",
        "category": "mixed_use",
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_planning(allow_network: bool = False, limit: int = 50) -> dict:
    """Build the major-developments payload.

    When ``allow_network`` is set, attempt a live keyless fetch from the Planning Data
    platform; on any failure (or offline) fall back to the bundled representative set so
    the build always succeeds and the demo is deterministic.
    """
    if allow_network:
        try:
            import integrations

            apps = integrations.fetch_planning_applications(limit=limit)
            if apps:
                return {
                    "source": "live",
                    "live": True,
                    "fetched_at": _now_iso(),
                    "provider": "planning.data.gov.uk (planning-application, major schemes)",
                    "applications": apps,
                }
        except Exception:  # noqa: BLE001 - any failure → deterministic offline bundle
            pass
    return {
        "source": SOURCE,
        "live": False,
        "fetched_at": BUNDLE_FETCHED_AT,
        "provider": "planning.data.gov.uk (bundled representative major schemes)",
        "applications": BUNDLED_PLANNING,
    }


def write_planning(path: Path | str = PLANNING_PATH, allow_network: bool = False) -> dict:
    payload = build_planning(allow_network=allow_network)
    blob = json.dumps(payload, indent=2) + "\n"
    Path(path).write_text(blob)
    FRONTEND_PLANNING_PATH.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_PLANNING_PATH.write_text(blob)
    return payload


if __name__ == "__main__":
    write_planning()
