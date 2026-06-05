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

Everything is written through the module-level array namespace ``xp`` (CuPy if present,
else NumPy) so the haversine baseline itself already runs on the GPU when one exists.
"""
from __future__ import annotations

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
