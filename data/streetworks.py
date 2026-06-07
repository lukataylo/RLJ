"""Street Manager planned works integration (offline-safe bundle).

Exposes:
* ``streetwork_disruptions(date)`` -> list of TimedEvent road_closures.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
ROOT = DATA_DIR.parent
STREETWORKS_PATH = DATA_DIR / "streetworks.json"
FRONTEND_STREETWORKS_PATH = ROOT / "frontend" / "public" / "data" / "streetworks.json"

BUNDLE_FETCHED_AT = "2026-06-01T00:00:00+00:00"
SOURCE = "live-with-fallback"

# Populated by build_streetworks() when a live TfL planned-works fetch succeeds; used by
# streetwork_disruptions() so the scheduled timeline reflects live works when available.
_LIVE_STREETWORKS: list[dict] | None = None

# Core London Street Manager-style works (representative fallback).
BUNDLED_STREETWORKS = [
    {
        "id": "stw-whitechapel",
        "description": "Whitechapel Road — utility main replacement by Thames Water",
        "lat": 51.5175,
        "lng": -0.0600,
        "start": "08:00",
        "end": "18:00",
        "date": "2026-06-05",
        "authority": "Tower Hamlets",
        "permit_reference": "SM-TFL-20260605-001",
        "traffic_management": "lane_closure",
        "severity": "severe",
    },
    {
        "id": "stw-strand",
        "description": "Strand — carriageway resurfacing",
        "lat": 51.5110,
        "lng": -0.1200,
        "start": "09:00",
        "end": "17:00",
        "date": "2026-06-06",
        "authority": "Westminster",
        "permit_reference": "SM-TFL-20260606-014",
        "traffic_management": "road_closure",
        "severity": "severe",
    },
    {
        "id": "stw-euston",
        "description": "Euston Road — gas mains renewal",
        "lat": 51.5246,
        "lng": -0.1340,
        "start": "07:00",
        "end": "19:00",
        "date": "2026-06-07",
        "authority": "Camden",
        "permit_reference": "SM-TFL-20260607-021",
        "traffic_management": "multi_way_signals",
        "severity": "moderate",
    },
    {
        "id": "stw-waterloo",
        "description": "Waterloo Bridge approach — emergency telecoms duct works",
        "lat": 51.5085,
        "lng": -0.1175,
        "start": "08:30",
        "end": "16:30",
        "date": "2026-06-05",
        "authority": "Lambeth",
        "permit_reference": "SM-TFL-20260605-031",
        "traffic_management": "lane_closure",
        "severity": "severe",
    },
    {
        "id": "stw-holborn",
        "description": "Holborn Viaduct — burst water main repair",
        "lat": 51.5170,
        "lng": -0.1030,
        "start": "06:00",
        "end": "21:00",
        "date": "2026-06-05",
        "authority": "City of London",
        "permit_reference": "SM-TFL-20260605-044",
        "traffic_management": "contra_flow",
        "severity": "moderate",
    },
]


def _as_date(d: date | datetime | str) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def _box(lat: float, lng: float) -> list[dict]:
    pad = 0.003
    return [
        {"lat": round(lat + pad, 6), "lng": round(lng - pad, 6)},
        {"lat": round(lat + pad, 6), "lng": round(lng + pad, 6)},
        {"lat": round(lat - pad, 6), "lng": round(lng + pad, 6)},
        {"lat": round(lat - pad, 6), "lng": round(lng - pad, 6)},
        {"lat": round(lat + pad, 6), "lng": round(lng - pad, 6)},
    ]


def _active_streetworks() -> list[dict]:
    """Live works when a network fetch has populated the cache, else the bundle."""
    return _LIVE_STREETWORKS if _LIVE_STREETWORKS else BUNDLED_STREETWORKS


def streetwork_disruptions(d: date | datetime | str) -> list[dict]:
    """Get the planned streetwork disruptions for a date."""
    day = _as_date(d)
    iso = day.isoformat()
    out = []
    for idx, sw in enumerate(_active_streetworks()):
        if sw["date"] != iso:
            continue
        shh, smm = (int(x) for x in sw["start"].split(":"))
        ehh, emm = (int(x) for x in sw["end"].split(":"))
        start = datetime(day.year, day.month, day.day, shh, smm, tzinfo=timezone.utc)
        end = datetime(day.year, day.month, day.day, ehh, emm, tzinfo=timezone.utc)

        out.append(
            {
                "id": f"{sw['id']}-{iso}",
                "kind": "road_closure",
                "geometry": _box(sw["lat"], sw["lng"]),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "intensity": 1.0,
                # Provenance vocab for TimedEvents is {scheduled,synthetic,live} — keep
                # it valid regardless of the manifest dataset source label.
                "source": "live" if _LIVE_STREETWORKS else "scheduled",
                "label": sw["description"],
                "authority": sw["authority"],
                "permit_reference": sw["permit_reference"],
                "traffic_management": sw["traffic_management"],
                "severity": sw["severity"],
                "fetched_at": BUNDLE_FETCHED_AT,
            }
        )
    return out


def build_streetworks(allow_network: bool = False) -> dict:
    """Build the planned-works payload.

    When ``allow_network`` is set, attempt a live keyless fetch of dated planned works
    from the TfL Road API; on any failure (or offline) fall back to the bundled
    representative set so the build always succeeds and the demo is deterministic.
    """
    global _LIVE_STREETWORKS
    if allow_network:
        try:
            import integrations

            works = integrations.fetch_planned_streetworks()
            if works:
                _LIVE_STREETWORKS = works
                return {
                    "source": "live",
                    "live": True,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "provider": "TfL Unified API Road/All/Disruption (planned works)",
                    "streetworks": works,
                }
        except Exception:  # noqa: BLE001 - any failure → deterministic offline bundle
            pass
    _LIVE_STREETWORKS = None
    return {
        "source": SOURCE,
        "live": False,
        "fetched_at": BUNDLE_FETCHED_AT,
        "provider": "DfT Street Manager / TfL planned works (bundled representative)",
        "streetworks": BUNDLED_STREETWORKS,
    }


def write_streetworks(path: Path | str = STREETWORKS_PATH, allow_network: bool = False) -> dict:
    payload = build_streetworks(allow_network=allow_network)
    blob = json.dumps(payload, indent=2) + "\n"
    Path(path).write_text(blob)
    FRONTEND_STREETWORKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_STREETWORKS_PATH.write_text(blob)
    return payload


if __name__ == "__main__":
    write_streetworks()
