"""Travel-time engine for the router.

Produces an ``N x N`` matrix of node-to-node travel times (seconds) over the set of
stops in an :class:`~models.OptimizeRequest` (courier depots + every job pickup and
dropoff). The solver consumes only this matrix, so the *quality* of routing scales
directly with the quality of this engine — making it the natural place to spend GPU.

Three tiers, in order of fidelity (see the fallback ladder in README.md):

  1. **GPU batched single-source-shortest-path (SSSP)**  — the planned headline kernel.
     Load the London road graph once onto the GB10, then for every stop launch a
     batched Δ-stepping / Bellman-Ford relaxation across all source nodes in parallel
     (one CUDA block per source). This turns an O(V·E) per-source classical SSSP into a
     single fused, memory-bound kernel that fills the whole matrix in one pass. Seam +
     signature below (``gpu_sssp_matrix``); not implemented on this dev box.
  2. **OSMnx / networkx road-graph shortest paths** — CPU correctness baseline that uses
     real street distances. Stub + signature below (``osmnx_matrix``); documented only.
  3. **Haversine great-circle / numpy** — the always-available default used here. Fully
     vectorised; identical distance model to the orchestrator's greedy fallback so the
     two are directly comparable in bench.py.

In addition to those in-process tiers there is an **out-of-process road-graph tier** that
talks to a local **Valhalla** routing server over HTTP (``valhalla_matrix``). Unlike the
two seams below it is fully implemented: it asks Valhalla's ``/sources_to_targets`` matrix
API for real street travel times, and — true to the repo's "every component has a
fallback" rule — silently degrades to the haversine default on any error so the service
never blocks on Valhalla being up.

Everything is written through the module-level array namespace ``xp`` (CuPy if present,
else NumPy) so the haversine baseline itself already runs on the GPU when one exists.
"""
from __future__ import annotations

import os
from collections import OrderedDict
from typing import Iterable, Sequence

# --- array backend: CuPy on the GB10, NumPy on this Mac -----------------------------
try:  # pragma: no cover - exercised only on GPU hardware
    import cupy as xp  # type: ignore

    GPU_BACKEND = True
except Exception:  # noqa: BLE001 - any import failure means "no GPU here"
    import numpy as xp  # type: ignore

    GPU_BACKEND = False

import numpy as np  # always available; used for host-side return values

EARTH_RADIUS_M = 6_371_000.0
# ~23 km/h urban average including stops.
AVG_SPEED_MPS = 6.5
# Straight-line -> road distance multiplier (urban circuity). Real driving distance is
# ~1.3-1.5x great-circle; using it makes ETAs realistic vs the greedy straight-line model.
CIRCUITY = 1.4
# Disruption model (approximate, no road graph): a leg whose straight segment passes
# within CLOSURE_RADIUS_M of a closure/traffic geometry is inflated by these factors.
CLOSURE_RADIUS_M = 350.0
ROAD_CLOSURE_FACTOR = 6.0   # detour: effectively forces the solver around the closure
TRAFFIC_FACTOR = 2.0        # congestion: slower but passable


def haversine_matrix(lats: Sequence[float], lngs: Sequence[float]) -> np.ndarray:
    """Vectorised great-circle distance matrix in metres for ``N`` coordinates.

    Returns an ``(N, N)`` host (NumPy) array. Computation runs on ``xp`` (GPU when
    available) and is copied back to host for the solver.
    """
    lat = xp.radians(xp.asarray(lats, dtype=xp.float64))
    lng = xp.radians(xp.asarray(lngs, dtype=xp.float64))
    # Pairwise differences via broadcasting -> (N, N).
    dlat = lat[:, None] - lat[None, :]
    dlng = lng[:, None] - lng[None, :]
    a = (
        xp.sin(dlat / 2.0) ** 2
        + xp.cos(lat[:, None]) * xp.cos(lat[None, :]) * xp.sin(dlng / 2.0) ** 2
    )
    dist = 2.0 * EARTH_RADIUS_M * xp.arcsin(xp.sqrt(xp.clip(a, 0.0, 1.0)))
    # asnumpy round-trips GPU -> host; on NumPy it is a no-op cast.
    return np.asarray(xp.asnumpy(dist) if GPU_BACKEND else dist, dtype=np.float64)


def build_travel_time_matrix(
    lats: Sequence[float],
    lngs: Sequence[float],
    *,
    speed_mps: float = AVG_SPEED_MPS,
    disruptions: Iterable | None = None,
) -> np.ndarray:
    """Return an ``(N, N)`` travel-time matrix in **seconds**.

    The default model is ``haversine_distance / speed``. ``disruptions`` is accepted so
    the signature is stable across tiers; the haversine baseline applies a coarse
    multiplier seam (see below) but does not yet do true edge-level closures — that is
    the job of the road-graph tiers.
    """
    dist_m = haversine_matrix(lats, lngs) * CIRCUITY
    travel_s = dist_m / max(speed_mps, 1e-6)

    # --- disruption penalties -------------------------------------------------------
    # Approximation of the road-graph tiers' edge removal: inflate any leg whose straight
    # segment passes within CLOSURE_RADIUS_M of a closure/traffic geometry. This is what
    # makes "close a road" actually re-route the solver without a full road graph.
    if disruptions:
        travel_s = _apply_disruptions(travel_s, np.asarray(lats, dtype=np.float64),
                                      np.asarray(lngs, dtype=np.float64), disruptions)
    return travel_s


def _point_seg_min_m(plat, plng, alat, alng, blat, blng, samples: int = 5) -> float:
    """Min great-circle distance (m) between sampled points of segment a->b and point p.
    Cheap equirectangular approximation — fine at city scale."""
    ts = np.linspace(0.0, 1.0, samples)
    slat = alat + (blat - alat) * ts
    slng = alng + (blng - alng) * ts
    mlat = np.radians((slat + plat) / 2.0)
    dx = np.radians(slng - plng) * np.cos(mlat)
    dy = np.radians(slat - plat)
    return float(np.min(np.hypot(dx, dy)) * EARTH_RADIUS_M)


def _disruption_points(d) -> list[tuple[float, float]]:
    geom = d.geometry if hasattr(d, "geometry") else d.get("geometry")
    pts = []
    for g in (geom or []):
        if hasattr(g, "lat"):
            pts.append((g.lat, g.lng))
        else:
            pts.append((g["lat"], g["lng"]))
    return pts


def _apply_disruptions(travel_s: np.ndarray, lats, lngs, disruptions) -> np.ndarray:
    out = travel_s.copy()
    N = len(lats)
    for d in disruptions:
        kind = d.kind if hasattr(d, "kind") else d.get("kind")
        if kind == "courier_down":
            continue  # handled by marking the courier offline upstream
        factor = ROAD_CLOSURE_FACTOR if kind == "road_closure" else TRAFFIC_FACTOR
        pts = _disruption_points(d)
        if not pts:
            continue
        for i in range(N):
            for j in range(i + 1, N):
                hit = any(
                    _point_seg_min_m(plat, plng, lats[i], lngs[i], lats[j], lngs[j]) < CLOSURE_RADIUS_M
                    for plat, plng in pts
                )
                if hit:
                    out[i, j] *= factor
                    out[j, i] *= factor
    return out


# =====================================================================================
# Out-of-process road-graph tier — Valhalla matrix API over HTTP (IMPLEMENTED).
# =====================================================================================
def _valhalla_exclude_polygons(disruptions) -> list:
    """Translate road-closure disruptions into Valhalla ``exclude_polygons``.

    Valhalla expects each polygon as a list of ``[lon, lat]`` rings. We only emit a
    polygon for ``road_closure`` geometries with **>= 3 points** (a genuine area Valhalla
    can route around). Point/line closures and ``traffic``/``courier_down`` events are
    intentionally skipped here — there is no robust 1:1 mapping to an avoidance polygon,
    so we keep it simple and let the haversine-style penalties handle those upstream.
    Never raises: odd/partial disruption objects are quietly ignored.
    """
    polys: list = []
    for d in disruptions or []:
        try:
            kind = d.kind if hasattr(d, "kind") else d.get("kind")
            if kind != "road_closure":
                continue
            pts = _disruption_points(d)
            if len(pts) >= 3:
                polys.append([[float(lng), float(lat)] for (lat, lng) in pts])
        except Exception:  # noqa: BLE001 - a malformed disruption must not break the request
            continue
    return polys


def valhalla_matrix(
    lats: Sequence[float],
    lngs: Sequence[float],
    *,
    base_url: str | None = None,
    costing: str = "auto",
    disruptions: Iterable | None = None,
    timeout_s: float = 10.0,
) -> np.ndarray:
    """Road-graph travel-time tier backed by a local **Valhalla** server (seconds).

    POSTs the ``N`` stops as both sources and targets to Valhalla's
    ``{base_url}/sources_to_targets`` matrix endpoint and parses the *concise* response
    (``sources_to_targets.durations``, an ``N x N`` array of seconds) into an ``(N, N)``
    host (NumPy) ``float64`` matrix with a zeroed diagonal — drop-in compatible with
    :func:`build_travel_time_matrix`.

    Parameters mirror the other tiers:
      * ``base_url`` — Valhalla base URL; defaults to ``$VALHALLA_URL`` then
        ``http://localhost:8002``.
      * ``costing`` — Valhalla costing model (``auto``, ``bicycle``, ``pedestrian`` ...).
      * ``disruptions`` — road closures with >= 3-point geometries are forwarded as
        ``exclude_polygons`` so Valhalla routes around them (see
        :func:`_valhalla_exclude_polygons`); other kinds are left to the haversine seam.
      * ``timeout_s`` — per-request HTTP timeout.

    Robustness: any ``null`` duration Valhalla returns for an unreachable pair is filled
    from the haversine baseline so the matrix is always finite. And on **any** failure
    (HTTP client absent, connection refused, non-200, malformed/empty body) the function
    degrades silently to ``build_travel_time_matrix(lats, lngs, disruptions=disruptions)``
    — the always-available default — honouring the repo's fallback ladder.
    """
    # The haversine baseline doubles as both the universal fallback and the null-filler.
    baseline = build_travel_time_matrix(lats, lngs, disruptions=disruptions)
    try:
        n = len(baseline)
        url = (base_url or os.environ.get("VALHALLA_URL", "http://localhost:8002"))
        url = url.rstrip("/") + "/sources_to_targets"

        # Lazy, guarded import so importing this module never requires an HTTP client.
        try:
            import httpx as _http  # transitive FastAPI dep; preferred when available
        except Exception:  # noqa: BLE001
            import requests as _http  # declared in requirements.txt

        stops = [{"lat": float(la), "lon": float(ln)} for la, ln in zip(lats, lngs)]
        payload: dict = {
            "sources": stops,
            "targets": stops,
            "costing": costing,
            "verbose": False,
        }
        exclude = _valhalla_exclude_polygons(disruptions)
        if exclude:
            payload["exclude_polygons"] = exclude

        resp = _http.post(url, json=payload, timeout=timeout_s)
        if getattr(resp, "status_code", None) != 200:
            raise ValueError(f"valhalla returned status {getattr(resp, 'status_code', '?')}")

        durations = resp.json()["sources_to_targets"]["durations"]
        if len(durations) != n:
            raise ValueError("valhalla durations shape mismatch")

        out = np.array(baseline, dtype=np.float64, copy=True)
        for i, row in enumerate(durations):
            if len(row) != n:
                raise ValueError("valhalla durations row shape mismatch")
            for j, val in enumerate(row):
                if val is not None:  # None -> keep the haversine fallback already in out
                    out[i, j] = float(val)
        np.fill_diagonal(out, 0.0)
        return out
    except Exception:  # noqa: BLE001 - every component has a fallback
        return baseline


# --- per-process travel-time matrix cache -------------------------------------------
# The /optimize portfolio builds the SAME matrix many times: every metaheuristic member
# (insertion/HGS/GARNET/local-search refine/pick_best) calls travel_time_matrix with the
# identical node ordering for one request, and the orchestrator re-optimises the same
# fleet repeatedly. Under Valhalla that was one /sources_to_targets HTTP round-trip PER
# member — several seconds per /optimize. Caching by (backend, coords, disruptions)
# collapses them to ONE call per distinct request (and zero on an unchanged re-plan),
# which is the difference between blowing and meeting the orchestrator's routing budget.
# Keyed on the backend URL so a haversine result never aliases a Valhalla one.
_MATRIX_CACHE: "OrderedDict[tuple, np.ndarray]" = OrderedDict()
_MATRIX_CACHE_MAX = 128


def _matrix_disruption_sig(disruptions) -> tuple:
    """Hashable signature of only the disruptions that change the matrix (road closures +
    traffic). ``courier_down`` has no geometric effect, so it is excluded to keep hits."""
    if not disruptions:
        return ()
    sig = []
    for d in disruptions:
        kind = d.kind if hasattr(d, "kind") else d.get("kind")
        if kind not in ("road_closure", "traffic"):
            continue
        pts = tuple((round(la, 6), round(ln, 6)) for la, ln in _disruption_points(d))
        sig.append((kind, pts))
    return tuple(sorted(sig))


def clear_matrix_cache() -> None:
    """Empty the matrix cache (for tests, or when the road graph / costing changes)."""
    _MATRIX_CACHE.clear()


def travel_time_matrix(
    lats: Sequence[float],
    lngs: Sequence[float],
    *,
    disruptions: Iterable | None = None,
) -> np.ndarray:
    """Active travel-time matrix the solvers consume — the one place tier selection lives.

    When ``$VALHALLA_URL`` is set, route over the real London road graph via
    :func:`valhalla_matrix` (which itself degrades to haversine on any failure). Otherwise
    use the always-available haversine baseline. This keeps the dev box / CI / benchmarks on
    the deterministic haversine model by default, and lights up real roads on the GB10 demo
    box simply by exporting ``VALHALLA_URL``.

    Results are memoised per (backend, coords, disruptions) — see ``_MATRIX_CACHE`` — so the
    many identical calls a single ``/optimize`` makes hit the network (or even the haversine
    math) only once. Returned arrays are private copies; mutating them never corrupts the
    cache.
    """
    backend = os.environ.get("VALHALLA_URL", "")
    key = (
        backend,
        tuple(round(float(x), 6) for x in lats),
        tuple(round(float(x), 6) for x in lngs),
        _matrix_disruption_sig(disruptions),
    )
    cached = _MATRIX_CACHE.get(key)
    if cached is not None:
        _MATRIX_CACHE.move_to_end(key)          # LRU touch
        return cached.copy()

    out = (valhalla_matrix(lats, lngs, disruptions=disruptions) if backend
           else build_travel_time_matrix(lats, lngs, disruptions=disruptions))
    out = np.asarray(out, dtype=np.float64)
    _MATRIX_CACHE[key] = out.copy()
    if len(_MATRIX_CACHE) > _MATRIX_CACHE_MAX:
        _MATRIX_CACHE.popitem(last=False)       # evict oldest
    return out


# =====================================================================================
# Higher-fidelity tiers — SEAMS. Documented signatures; not implemented on this dev box.
# =====================================================================================
def gpu_sssp_matrix(
    lats: Sequence[float],
    lngs: Sequence[float],
    *,
    road_graph,  # cuGraph / CSR adjacency resident in GPU memory
    disruptions: Iterable | None = None,
) -> np.ndarray:
    """PLANNED GB10 kernel: batched single-source-shortest-path over the road graph.

    Design (drop-in replacement for :func:`build_travel_time_matrix`):
      * Pre-load the London drive network as a CSR (indptr/indices/weights) on device.
      * Snap each of the ``N`` stops to its nearest graph node.
      * Launch a batched Δ-stepping relaxation: one CUDA block per source node, all ``N``
        sources resident at once, so the entire matrix is produced in a single fused,
        memory-bound pass instead of ``N`` independent Dijkstra runs.
      * Apply ``disruptions`` by zeroing/penalising the affected edge weights before the
        launch — re-optimising after a road closure is then just one more kernel call,
        which is the whole point of keeping this on the box.

    Raises ``NotImplementedError`` on this dev machine.
    """
    raise NotImplementedError(
        "GPU batched-SSSP kernel runs on the DGX Spark (GB10); "
        "use build_travel_time_matrix() (haversine) on CPU."
    )


def osmnx_matrix(
    lats: Sequence[float],
    lngs: Sequence[float],
    *,
    place: str = "London, England",
    disruptions: Iterable | None = None,
) -> np.ndarray:
    """CPU road-graph baseline via OSMnx + networkx (correctness tier).

    Sketch: ``ox.graph_from_place(place, network_type='drive')`` once, cache it, snap
    stops with ``ox.distance.nearest_nodes``, then fill the matrix with
    ``nx.shortest_path_length(..., weight='travel_time')``. Closures map to removed
    edges before the shortest-path sweep. Intentionally a stub — documented only.

    Raises ``NotImplementedError``.
    """
    raise NotImplementedError(
        "OSMnx road-graph tier is a documented stub; "
        "use build_travel_time_matrix() (haversine) as the default."
    )
