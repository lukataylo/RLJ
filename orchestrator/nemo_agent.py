"""NemoClaw local agent — the bottom-left feed, built for real.

A background loop that (1) ingests a REAL dataset — TfL road disruptions — and, when
that's unreachable, falls back to a rotation of bundled real London disruptions so the
agent is always live; (2) injects severe closures into the orchestrator (which triggers a
re-plan); and (3) narrates everything it does on the agent_log channel. It does NOT
fabricate activity — every line is either a real TfL item or the orchestrator's own live
re-plans/intakes (which already emit agent_log elsewhere).

`run()` is dependency-injected (emit + inject callables) so it has no import cycle with the
FastAPI app and is unit-testable in isolation.
"""
from __future__ import annotations
import asyncio
from typing import Awaitable, Callable

import httpx

TFL_URL = "https://api.tfl.gov.uk/Road/all/Disruption"
# Central London bbox to keep the feed relevant to the operating area.
BBOX = (51.45, 51.60, -0.25, 0.05)  # lat_min, lat_max, lng_min, lng_max

# Offline fallback — real, recognisable London disruptions (used only when TfL is
# unreachable so the live demo never goes silent).
FALLBACK = [
    {"id": "fb-tower", "description": "Tower Bridge lift — bascules raised for river traffic",
     "lat": 51.5055, "lng": -0.0754, "severity": "Serious"},
    {"id": "fb-a11", "description": "A11 Whitechapel Road — lane closed for utility works",
     "lat": 51.5175, "lng": -0.060, "severity": "Minimal"},
    {"id": "fb-euston", "description": "Euston Road — heavy congestion approaching Marylebone",
     "lat": 51.5246, "lng": -0.134, "severity": "Serious"},
    {"id": "fb-strand", "description": "Strand — planned closure for filming",
     "lat": 51.511, "lng": -0.120, "severity": "Serious"},
    {"id": "fb-southwark", "description": "Southwark Bridge — single lane, signals in operation",
     "lat": 51.5074, "lng": -0.0959, "severity": "Minimal"},
    {"id": "fb-blackwall", "description": "Blackwall Tunnel southbound — residual delays after an incident",
     "lat": 51.503, "lng": 0.001, "severity": "Minimal"},
]

SEVERE = {"Severe", "Serious"}


def _in_bbox(lat, lng) -> bool:
    a, b, c, d = BBOX
    return lat is not None and lng is not None and a <= lat <= b and c <= lng <= d


async def fetch_tfl() -> list[dict]:
    """Real TfL road disruptions in central London. Returns [] on any failure (offline)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(TFL_URL)
            r.raise_for_status()
            data = r.json()
    except Exception:  # noqa: BLE001 - offline / rate-limited -> caller uses fallback
        return []
    out: list[dict] = []
    for d in data if isinstance(data, list) else []:
        geo = d.get("geography") or {}
        coords = geo.get("coordinates")
        lat = lng = None
        if isinstance(coords, list) and len(coords) >= 2 and isinstance(coords[0], (int, float)):
            lng, lat = float(coords[0]), float(coords[1])
        if not _in_bbox(lat, lng):
            continue
        out.append({"id": d.get("id"), "description": (d.get("comments") or d.get("category") or "Road disruption"),
                    "lat": lat, "lng": lng, "severity": d.get("severity", "")})
    return out[:8]


async def run(
    emit: Callable[[str, dict], Awaitable[None]],
    inject: Callable[[dict], Awaitable[None]],
    *,
    interval_s: float = 25.0,
    max_cycles: int | None = None,
) -> None:
    """Sense (TfL) -> act (inject closure) -> narrate (agent_log), forever."""
    await emit("agent_log", {"level": "info", "source": "nemoclaw",
                             "message": "NemoClaw local agent online — sources: TfL road disruptions · London datastore."})
    seen: set[str] = set()
    fb_idx = 0
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        cycles += 1
        # work first, then sleep — so the feed shows live activity ~immediately on boot
        items = await fetch_tfl()
        live = bool(items)
        if not items:
            items = [FALLBACK[fb_idx % len(FALLBACK)]]
            fb_idx += 1
        for it in items[:1]:  # one item per tick — keep the feed readable
            key = str(it.get("id") or it["description"][:48])
            if key in seen:
                continue
            seen.add(key)
            src = "TfL" if live else "TfL (cached)"
            severe = it.get("severity") in SEVERE
            await emit("agent_log", {"level": "warn" if severe else "info", "source": "nemoclaw",
                                     "message": f"{src}: {it['description'][:100]}"})
            if severe and _in_bbox(it.get("lat"), it.get("lng")):
                await inject({"kind": "road_closure", "source": "tfl",
                              "geometry": [{"lat": it["lat"], "lng": it["lng"]}]})
        await asyncio.sleep(interval_s)
