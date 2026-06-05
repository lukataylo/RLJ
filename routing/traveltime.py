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
# ~23 km/h urban average including stops — matches orchestrator/greedy.py so the
# baseline comparison in bench.py is apples-to-apples.
AVG_SPEED_MPS = 6.5


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
    dist_m = haversine_matrix(lats, lngs)
    travel_s = dist_m / max(speed_mps, 1e-6)

    # --- disruption seam ------------------------------------------------------------
    # Road-graph tiers will remove/penalise the closed edges and re-run SSSP. With only
    # a straight-line model we cannot know which legs cross a closure, so we leave the
    # matrix unchanged here and document the seam. (A cheap approximation a future PR
    # could add: inflate any leg whose segment passes within R metres of a closure
    # polyline by a congestion factor.)
    _ = disruptions
    return travel_s


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
