"""TfL roadside Variable Message Sign integration.

TfL exposes VariableMessageSign places through the Unified API. The live fetch is
best-effort; the committed demo uses a representative offline bundle so the
first-minute scenario works without network.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent
ROOT = DATA_DIR.parent
ROADSIGNS_PATH = DATA_DIR / "roadsigns.json"
FRONTEND_ROADSIGNS_PATH = ROOT / "frontend" / "public" / "data" / "roadsigns.json"

BUNDLE_FETCHED_AT = "2026-06-01T00:00:00+00:00"
SOURCE = "live-with-fallback"

BUNDLED_SIGNS = [
    {
        "id": "vms-waterloo-bridge",
        "name": "Waterloo Bridge northbound VMS",
        "lat": 51.5090,
        "lng": -0.1168,
        "message": "WATERLOO BRIDGE DELAYS - USE BLACKFRIARS",
        "severity": "severe",
        "route_hint": "protect Guy's -> St Thomas STAT route",
        "updated_at": BUNDLE_FETCHED_AT,
        "active": True,
    },
    {
        "id": "vms-strand",
        "name": "Strand / Aldwych VMS",
        "lat": 51.5113,
        "lng": -0.1197,
        "message": "STRAND WORKS - EXPECT DELAYS",
        "severity": "moderate",
        "route_hint": "avoid westbound handoff via Strand",
        "updated_at": BUNDLE_FETCHED_AT,
        "active": True,
    },
    {
        "id": "vms-euston",
        "name": "Euston Road VMS",
        "lat": 51.5249,
        "lng": -0.1341,
        "message": "EUSTON RD GAS WORKS - QUEUES",
        "severity": "moderate",
        "route_hint": "prefer Tavistock Place for UCLH pickup",
        "updated_at": BUNDLE_FETCHED_AT,
        "active": True,
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_property(props: list[dict[str, Any]], *names: str) -> str | None:
    wanted = {n.lower() for n in names}
    for p in props:
        key = str(p.get("key") or p.get("name") or "").lower()
        if key in wanted:
            val = p.get("value")
            return str(val) if val is not None else None
    return None


def normalize_tfl_vms(payload: list[dict[str, Any]], limit: int = 40) -> list[dict]:
    signs: list[dict] = []
    for item in payload:
        lat, lng = item.get("lat"), item.get("lon") or item.get("lng")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue
        props = item.get("additionalProperties") or []
        if not isinstance(props, list):
            props = []
        message = (
            _extract_property(props, "message", "currentmessage", "displaytext", "text")
            or item.get("commonName")
            or item.get("name")
            or "TfL roadside message"
        )
        signs.append(
            {
                "id": str(item.get("id") or f"vms-{len(signs) + 1}"),
                "name": str(item.get("commonName") or item.get("name") or "TfL VMS"),
                "lat": float(lat),
                "lng": float(lng),
                "message": str(message),
                "severity": "moderate",
                "route_hint": "live TfL roadside message",
                "updated_at": _now_iso(),
                "active": bool(item.get("active", True)),
            }
        )
        if len(signs) >= limit:
            break
    return signs


def _try_fetch() -> list[dict] | None:
    try:
        import requests

        params = {
            "type": "VariableMessageSign",
            "activeOnly": "true",
            "numberOfPlacesToReturn": "40",
        }
        app_key = os.getenv("TFL_APP_KEY")
        if app_key:
            params["app_key"] = app_key
        response = requests.get("https://api.tfl.gov.uk/Place", params=params, timeout=3)
        response.raise_for_status()
        signs = normalize_tfl_vms(response.json())
        return signs or None
    except Exception:
        return None


def build_roadsigns(allow_network: bool = False) -> dict:
    signs = _try_fetch() if allow_network else None
    return {
        "source": "live" if signs else SOURCE,
        "live": bool(signs),
        "fetched_at": _now_iso() if signs else BUNDLE_FETCHED_AT,
        "provider": "TfL Unified API Place/VariableMessageSign",
        "signs": signs or BUNDLED_SIGNS,
    }


def write_roadsigns(path: Path | str = ROADSIGNS_PATH, allow_network: bool = False) -> dict:
    payload = build_roadsigns(allow_network=allow_network)
    blob = json.dumps(payload, indent=2) + "\n"
    Path(path).write_text(blob)
    FRONTEND_ROADSIGNS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_ROADSIGNS_PATH.write_text(blob)
    return payload


if __name__ == "__main__":
    write_roadsigns()
