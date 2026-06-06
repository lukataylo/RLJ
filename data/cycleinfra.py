"""TfL Cycle Infrastructure & Cycle Hire Integration (offline-safe, bundled fallback).

Exposes:
* ``cycle_infrastructure_ratio(lat, lng)`` -> speed factor multiplier for cycle couriers.
* ``build_cycleinfra()`` -> full bundle payload.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
CYCLEINFRA_PATH = DATA_DIR / "cycleinfra.json"

BUNDLE_FETCHED_AT = "2026-06-01T00:00:00+00:00"
SOURCE = "scheduled"

# Major TfL Cycle Hire stations
STATIONS = [
    {"id": "cycle-st-paul", "name": "St. Paul's Cathedral", "lat": 51.5140, "lng": -0.0980, "capacity": 25},
    {"id": "cycle-waterloo", "name": "Waterloo Station", "lat": 51.5030, "lng": -0.1140, "capacity": 45},
    {"id": "cycle-hyde-park", "name": "Hyde Park Corner", "lat": 51.5030, "lng": -0.1500, "capacity": 30},
    {"id": "cycle-london-bridge", "name": "London Bridge Station", "lat": 51.5060, "lng": -0.0860, "capacity": 35},
]

# Major London Cycle Superhighways (CS) segments modeled as line coordinates
CYCLE_HIGHWAYS = [
    {
        "id": "CS1",
        "name": "Cycle Superhighway 1",
        "geometry": [
            {"lat": 51.5170, "lng": -0.0850},
            {"lat": 51.5300, "lng": -0.0830},
            {"lat": 51.5450, "lng": -0.0760},
        ],
    },
    {
        "id": "CS3",
        "name": "Cycle Superhighway 3",
        "geometry": [
            {"lat": 51.5100, "lng": -0.1500},
            {"lat": 51.5080, "lng": -0.1250},
            {"lat": 51.5110, "lng": -0.0750},
            {"lat": 51.5150, "lng": -0.0200},
        ],
    },
]


def cycle_infrastructure_ratio(lat: float, lng: float) -> float:
    """Return a speed-up factor multiplier for cycling based on proximity to cycle highways."""
    # Find distance squared to nearest cycle highway segment
    best_dist = float("inf")
    for highway in CYCLE_HIGHWAYS:
        for pt in highway["geometry"]:
            dist = (pt["lat"] - lat) ** 2 + (pt["lng"] - lng) ** 2
            if dist < best_dist:
                best_dist = dist
                
    # If within 500m (~0.005 degrees), grant a speed multiplier up to 1.3 (30% speedup)
    if best_dist < 0.000025:  # ~0.005 degrees squared
        return 1.3
    return 1.0


def build_cycleinfra() -> dict:
    return {
        "source": SOURCE,
        "fetched_at": BUNDLE_FETCHED_AT,
        "provider": "TfL Cycle Infrastructure Database + Santander Cycles Open Data (bundled)",
        "stations": STATIONS,
        "highways": CYCLE_HIGHWAYS,
    }


def write_cycleinfra(path: Path | str = CYCLEINFRA_PATH) -> dict:
    payload = build_cycleinfra()
    Path(path).write_text(json.dumps(payload, indent=2) + "\n")
    return payload


if __name__ == "__main__":
    write_cycleinfra()
