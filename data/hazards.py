"""TfL live road-disruption / hazard integration (offline-safe, bundled fallback).

TfL exposes current road disruptions (accidents, broken-down vehicles, severe
delays, closures) through the Unified API ``Road/All/Disruption`` endpoint, which
is open and keyless. These are the live hazards a delivery driver should avoid.

The live fetch is best-effort (see :func:`data.integrations.fetch_road_hazards`);
the committed demo uses a representative offline bundle so the first-minute
scenario works without network.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
ROOT = DATA_DIR.parent
HAZARDS_PATH = DATA_DIR / "hazards.json"
FRONTEND_HAZARDS_PATH = ROOT / "frontend" / "public" / "data" / "hazards.json"

BUNDLE_FETCHED_AT = "2026-06-01T00:00:00+00:00"
SOURCE = "live-with-fallback"

# Allowed normalized severities (shared with the frontend colour ramp).
HAZARD_SEVERITIES = ("low", "moderate", "severe")

# Representative live road disruptions across London (in-bbox, deterministic).
BUNDLED_HAZARDS = [
    {
        "id": "haz-a40-westway",
        "description": "A40 Westway — collision, two lanes blocked eastbound",
        "lat": 51.5176,
        "lng": -0.2065,
        "severity": "severe",
        "category": "accident",
    },
    {
        "id": "haz-elephant-castle",
        "description": "Elephant & Castle — broken-down HGV blocking nearside lane",
        "lat": 51.4946,
        "lng": -0.0997,
        "severity": "moderate",
        "category": "obstruction",
    },
    {
        "id": "haz-blackwall-tunnel",
        "description": "Blackwall Tunnel southbound — closed for emergency repairs",
        "lat": 51.5025,
        "lng": 0.0050,
        "severity": "severe",
        "category": "closure",
    },
    {
        "id": "haz-vauxhall-cross",
        "description": "Vauxhall Cross — signal fault causing heavy queues",
        "lat": 51.4861,
        "lng": -0.1230,
        "severity": "moderate",
        "category": "congestion",
    },
    {
        "id": "haz-old-street",
        "description": "Old Street roundabout — surface water, drive with care",
        "lat": 51.5256,
        "lng": -0.0875,
        "severity": "low",
        "category": "hazard",
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def severity_band(raw: str | None) -> str:
    """Map a TfL severity string to the normalized low/moderate/severe band."""
    s = str(raw or "").strip().lower()
    if s in ("severe", "serious"):
        return "severe"
    if s in ("moderate", "minimal", "minor"):
        return "moderate" if s == "moderate" else "low"
    if s in ("low", "slight"):
        return "low"
    # Unknown/blank → treat as moderate so it is still surfaced to the driver.
    return "moderate"


def build_hazards() -> dict:
    return {
        "source": SOURCE,
        "live": False,
        "fetched_at": BUNDLE_FETCHED_AT,
        "provider": "TfL Unified API Road/All/Disruption (bundled)",
        "hazards": BUNDLED_HAZARDS,
    }


def write_hazards(path: Path | str = HAZARDS_PATH) -> dict:
    payload = build_hazards()
    blob = json.dumps(payload, indent=2) + "\n"
    Path(path).write_text(blob)
    FRONTEND_HAZARDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_HAZARDS_PATH.write_text(blob)
    return payload


if __name__ == "__main__":
    write_hazards()
