"""Road-following geometry for a delivery — Valhalla ``/route`` + matrix over HTTP.

Self-contained copy of ``routing/route_geometry`` for the orchestrator (the two
streams integrate only through ``contracts/``, so each keeps its own small helper —
same pattern as the duplicated greedy fallback). Used by ``/intake`` to return a
clean pickup→dropoff(s) road shape the UI can draw as *this* delivery's route,
instead of the courier's full multi-stop tour.

For MULTI-DROP intake, ``optimized_route`` picks a good visiting order of the
drops (nearest-neighbour from the fixed origin + a light 2-opt), using a Valhalla
duration matrix (``/sources_to_targets``), then draws the road geometry through
that order via ``valhalla_route_shape``.

Fallback-first: on any failure these return empty/identity so /intake never blocks
on Valhalla.
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


def valhalla_matrix_durations(
    lats: Sequence[float],
    lngs: Sequence[float],
    *,
    base_url: str | None = None,
    costing: str = "auto",
    timeout_s: float = 10.0,
) -> List[List[float]] | None:
    """Symmetric duration matrix (seconds) between all points via Valhalla.

    POSTs ``/sources_to_targets`` with sources == targets == the given points
    (``verbose: false``). Returns ``matrix[i][j]`` durations in seconds, or
    ``None`` on any failure (so callers fall back to the input order). Never raises.
    """
    try:
        if len(lats) < 2 or len(lngs) < 2 or len(lats) != len(lngs):
            return None
        url = (base_url or os.environ.get("VALHALLA_URL", "http://localhost:8002"))
        url = url.rstrip("/") + "/sources_to_targets"
        try:
            import httpx as _http
        except Exception:  # noqa: BLE001
            import requests as _http
        points = [{"lat": float(la), "lon": float(ln)} for la, ln in zip(lats, lngs)]
        payload = {"sources": points, "targets": points,
                   "costing": costing, "verbose": False}
        resp = _http.post(url, json=payload, timeout=timeout_s)
        if getattr(resp, "status_code", None) != 200:
            raise ValueError("valhalla non-200")
        data = resp.json()
        # Prefer an explicit `durations` matrix; else derive from Valhalla's
        # `sources_to_targets` rows (each cell carries a `time` in seconds).
        matrix = data.get("durations")
        if matrix is None:
            rows = data["sources_to_targets"]
            matrix = [[(cell.get("time") if isinstance(cell, dict) else cell)
                       for cell in row] for row in rows]
        n = len(lats)
        if len(matrix) != n or any(len(row) != n for row in matrix):
            raise ValueError("matrix shape mismatch")
        return [[float(v) if v is not None else None for v in row] for row in matrix]
    except Exception:  # noqa: BLE001 - matrix is optional; caller falls back
        return None


def _cost(matrix: List[List[float]], i: int, j: int) -> float:
    v = matrix[i][j]
    return float("inf") if v is None else v


def _tour_cost(order: List[int], matrix: List[List[float]]) -> float:
    return sum(_cost(matrix, order[k], order[k + 1]) for k in range(len(order) - 1))


def _nearest_neighbour(matrix: List[List[float]], n: int) -> List[int]:
    """Open-path NN starting at index 0 (the fixed origin/pickup)."""
    order = [0]
    unvisited = set(range(1, n))
    cur = 0
    while unvisited:
        nxt = min(unvisited, key=lambda j: _cost(matrix, cur, j))
        order.append(nxt)
        unvisited.discard(nxt)
        cur = nxt
    return order


def _two_opt(order: List[int], matrix: List[List[float]]) -> List[int]:
    """Light 2-opt on the open path, keeping index 0 (origin) fixed first."""
    best = order[:]
    improved = True
    while improved:
        improved = False
        for i in range(1, len(best) - 1):
            for k in range(i + 1, len(best)):
                cand = best[:i] + best[i:k + 1][::-1] + best[k + 1:]
                if _tour_cost(cand, matrix) < _tour_cost(best, matrix) - 1e-9:
                    best = cand
                    improved = True
    return best


def optimized_route(
    lats: Sequence[float],
    lngs: Sequence[float],
    *,
    base_url: str | None = None,
    costing: str = "auto",
) -> dict:
    """Optimised multi-stop route. Input is ``[origin, dest1, dest2, ...]``.

    Index 0 (origin/pickup) is fixed first. Returns
    ``{"order": [input indices in visiting order], "polyline": [{lat,lng}, ...]}``.

    Ordering: a Valhalla duration matrix → nearest-neighbour from index 0, then a
    light 2-opt when there are ≤ 9 points. If the matrix is unavailable, the input
    order is kept. Geometry: ``valhalla_route_shape`` through the reordered points.
    On any failure returns ``{"order": identity, "polyline": []}`` — never raises.
    """
    n = len(lats)
    try:
        if n != len(lngs) or n == 0:
            return {"order": list(range(n)), "polyline": []}
        if n == 1:
            return {"order": [0], "polyline": []}

        matrix = valhalla_matrix_durations(lats, lngs, base_url=base_url, costing=costing)
        if matrix:
            order = _nearest_neighbour(matrix, n)
            if n <= 9:
                order = _two_opt(order, matrix)
        else:
            order = list(range(n))

        olats = [lats[i] for i in order]
        olngs = [lngs[i] for i in order]
        polyline = valhalla_route_shape(olats, olngs, base_url=base_url, costing=costing)
        return {"order": order, "polyline": polyline}
    except Exception:  # noqa: BLE001 - every component has a fallback
        return {"order": list(range(n)), "polyline": []}
