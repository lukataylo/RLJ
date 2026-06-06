"""Road-following geometry for a single delivery leg — Valhalla ``/route`` over HTTP.

Self-contained copy of ``routing/route_geometry`` for the orchestrator (the two
streams integrate only through ``contracts/``, so each keeps its own small helper —
same pattern as the duplicated greedy fallback). Used by ``/intake`` to return a
clean pickup→dropoff road shape the UI can draw as *this* delivery's route, instead
of the courier's full multi-stop tour.

Fallback-first: on any failure returns ``[]`` so /intake never blocks on Valhalla.
"""
from __future__ import annotations

import os
from typing import List, Sequence


def decode_polyline6(encoded: str, *, precision: int = 6) -> List[list]:
    """Decode an encoded polyline6 string into ``[[lat, lng], ...]`` (pure Python)."""
    if not encoded:
        return []
    factor = float(10 ** precision)
    coords: List[list] = []
    index = lat = lng = 0
    length = len(encoded)
    while index < length:
        for is_lng in (False, True):
            result = 0
            shift = 0
            while True:
                if index >= length:
                    return coords
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lng:
                lng += delta
            else:
                lat += delta
        coords.append([lat / factor, lng / factor])
    return coords


def valhalla_route_shape(
    lats: Sequence[float],
    lngs: Sequence[float],
    *,
    base_url: str | None = None,
    costing: str = "auto",
    timeout_s: float = 10.0,
) -> List[dict]:
    """Real road path through the ordered points as ``[{lat, lng}, ...]``; ``[]`` on failure."""
    try:
        if len(lats) < 2 or len(lngs) < 2 or len(lats) != len(lngs):
            return []
        url = (base_url or os.environ.get("VALHALLA_URL", "http://localhost:8002"))
        url = url.rstrip("/") + "/route"
        try:
            import httpx as _http
        except Exception:  # noqa: BLE001
            import requests as _http
        locations = [{"lat": float(la), "lon": float(ln), "type": "break"}
                     for la, ln in zip(lats, lngs)]
        payload = {"locations": locations, "costing": costing,
                   "directions_options": {"units": "kilometers"}}
        resp = _http.post(url, json=payload, timeout=timeout_s)
        if getattr(resp, "status_code", None) != 200:
            raise ValueError("valhalla non-200")
        legs = resp.json()["trip"]["legs"]
        shape: List[dict] = []
        for leg in legs:
            for la, ln in decode_polyline6(leg.get("shape") or ""):
                if shape and shape[-1]["lat"] == la and shape[-1]["lng"] == ln:
                    continue
                shape.append({"lat": la, "lng": ln})
        return shape if len(shape) >= 2 else []
    except Exception:  # noqa: BLE001 - every component has a fallback
        return []
