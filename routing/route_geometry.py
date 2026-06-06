"""Road-following route geometry — Valhalla ``/route`` shapes over HTTP (IMPLEMENTED).

The solvers produce an ordered list of stops per courier; the UI wants to draw the
route as it actually runs over London's streets, not as straight "as-the-crow-flies"
segments between stops. This module asks a local **Valhalla** routing server for the
real road shape through the ordered stops and returns it as a list of ``{lat, lng}``
points the frontend can render directly.

Mirrors the style of ``traveltime.valhalla_matrix``:
  * base URL from ``$VALHALLA_URL`` (default ``http://localhost:8002``);
  * lazy, guarded import of an HTTP client (``httpx`` preferred, else ``requests``);
  * **every component has a fallback** — on *any* failure (no client, connection
    refused, non-200, malformed body, fewer than two usable points) we return ``[]``
    so the caller keeps the existing straight-line polyline and ``/optimize`` never
    blocks on Valhalla being up.

Valhalla returns each leg's geometry as an **encoded polyline6** string (the standard
Google polyline algorithm at precision 1e6). We decode it in-process with the small
pure-Python ``decode_polyline6`` below so this module adds no pip dependency.
"""
from __future__ import annotations

import os
from typing import List, Sequence


def decode_polyline6(encoded: str, *, precision: int = 6) -> List[list]:
    """Decode an encoded polyline string into ``[[lat, lng], ...]``.

    Implements the standard Google polyline algorithm. Valhalla uses
    ``precision=6`` (coordinates scaled by 1e6); the default reflects that. Returns
    an empty list for empty/falsey input. Pure Python — no dependencies.
    """
    if not encoded:
        return []

    factor = float(10 ** precision)
    coords: List[list] = []
    index = 0
    lat = 0
    lng = 0
    length = len(encoded)

    while index < length:
        # Each coordinate component is a varint-style chunked, zig-zag encoded delta.
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
            # zig-zag decode
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
    """Return the real road path through the ordered points as ``[{lat, lng}, ...]``.

    POSTs the ordered stops to Valhalla's ``{base_url}/route`` endpoint as ``break``
    locations, then decodes and concatenates the ``trip.legs[*].shape`` polyline6
    strings (deduping the shared point between consecutive legs) into a single list
    of ``{"lat": float, "lng": float}`` dicts.

    Parameters mirror :func:`traveltime.valhalla_matrix`:
      * ``base_url`` — Valhalla base URL; defaults to ``$VALHALLA_URL`` then
        ``http://localhost:8002``.
      * ``costing`` — Valhalla costing model (``auto``, ``bicycle``, ``pedestrian`` ...).
      * ``timeout_s`` — per-request HTTP timeout.

    Robustness: requires at least two input points; on **any** failure (HTTP client
    absent, connection refused, non-200, malformed/empty body, <2 resulting points)
    returns ``[]`` so the caller keeps its existing straight-line polyline.
    """
    try:
        if len(lats) < 2 or len(lngs) < 2 or len(lats) != len(lngs):
            return []

        url = (base_url or os.environ.get("VALHALLA_URL", "http://localhost:8002"))
        url = url.rstrip("/") + "/route"

        # Lazy, guarded import so importing this module never requires an HTTP client.
        try:
            import httpx as _http  # transitive FastAPI dep; preferred when available
        except Exception:  # noqa: BLE001
            import requests as _http  # declared in requirements.txt

        locations = [
            {"lat": float(la), "lon": float(ln), "type": "break"}
            for la, ln in zip(lats, lngs)
        ]
        payload = {
            "locations": locations,
            "costing": costing,
            "directions_options": {"units": "kilometers"},
        }

        resp = _http.post(url, json=payload, timeout=timeout_s)
        if getattr(resp, "status_code", None) != 200:
            raise ValueError(f"valhalla returned status {getattr(resp, 'status_code', '?')}")

        legs = resp.json()["trip"]["legs"]
        shape: List[dict] = []
        for leg in legs:
            pts = decode_polyline6(leg.get("shape") or "")
            for la, ln in pts:
                # Dedupe the shared point between consecutive legs.
                if shape and shape[-1]["lat"] == la and shape[-1]["lng"] == ln:
                    continue
                shape.append({"lat": la, "lng": ln})

        if len(shape) < 2:
            return []
        return shape
    except Exception:  # noqa: BLE001 - every component has a fallback
        return []
