"""External suite for the GARNET neural route-optimiser (routing/solver_garnet.py + garnet_model.py).

Two tiers of test:

  * **Toggle / integration contract (always runs, no torch needed).** GARNET is off unless
    ``$GARNET_ENABLED`` is set, ``solver_garnet.plan`` returns ``None`` when off, and the
    portfolio is unaffected. This is the safety guarantee: shipping this code changes nothing
    until an operator opts in.

  * **Architecture + quality (needs torch — skipped on the numpy-only box).** The published
    GARNET properties we can verify deterministically: D-RRWP equals the random-walk matrix
    powers, the encoder is permutation-equivariant (Eq. 23), greedy decoding yields a valid
    Hamiltonian tour, and — the integration guarantee that matters — enabling GARNET never
    degrades the portfolio's clinical objective (it only adds a candidate to pick_best).

routing/ is on sys.path via tests/conftest.py, so ``import solver_garnet`` works directly.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

import solver_garnet

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = json.loads((ROOT / "contracts" / "samples" / "optimize_request.json").read_text())

# The orchestrator and routing streams both ship same-named modules (models, solver, ...).
# In the full-suite collection an earlier test (tests/completeness) re-imports the
# orchestrator app, leaving those names bound to the *orchestrator* versions — so a Plan
# built by one module and validated by the other trips pydantic's model_type check. Any
# test that runs a cross-module solve must therefore (re)import the routing set as one
# mutually-consistent group and build its request from that same ``models``.
_ROUTING_MODS = (
    "models", "solver", "solver_garnet", "solver_baseline", "solver_aco",
    "solver_hgs", "solver_ls", "solver_ortools", "traveltime", "route_geometry",
)


def _routing():
    """Return (solver, solver_garnet, models) freshly imported and mutually consistent."""
    for m in _ROUTING_MODS:
        sys.modules.pop(m, None)
    return (
        importlib.import_module("solver"),
        importlib.import_module("solver_garnet"),
        importlib.import_module("models"),
    )


def _sample_req(models):
    return models.OptimizeRequest(**SAMPLE)


def _score(req, plan):
    """Independent re-scorer (tests/benchmarks/instances.py) — never trusts the solver."""
    for sub in ("tests/benchmarks", "tests/backtests"):
        p = str(ROOT / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    from instances import validate_and_score
    return validate_and_score(req, plan)


# --------------------------------------------------------------------- toggle contract
def test_disabled_by_default(monkeypatch):
    """Unset env -> GARNET is off and contributes nothing."""
    monkeypatch.delenv("GARNET_ENABLED", raising=False)
    _solver, sg, models = _routing()
    assert sg.enabled() is False
    assert sg.plan(_sample_req(models)) is None


@pytest.mark.parametrize("val,expect", [
    ("1", True), ("true", True), ("YES", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("off", False),
])
def test_toggle_parsing(monkeypatch, val, expect):
    monkeypatch.setenv("GARNET_ENABLED", val)
    assert solver_garnet.enabled() is expect


def test_portfolio_unaffected_when_off(monkeypatch):
    """With GARNET off, the portfolio still returns a valid, schema-correct plan."""
    monkeypatch.delenv("GARNET_ENABLED", raising=False)
    solver, _sg, models = _routing()
    plan = solver.plan(_sample_req(models))
    assert plan.routes or plan.unassigned is not None
    assert plan.objective.solver == solver.SOLVER_NAME  # not relabelled by GARNET


# ------------------------------------------------------------- architecture (torch only)
torch = pytest.importorskip("torch", reason="GARNET architecture needs torch (optional dep)")
import garnet_model as gm  # noqa: E402  (after importorskip)


def test_drrwp_matches_matrix_powers():
    """D-RRWP P_h must equal T^h for the row-stochastic transition matrix T (Eqs. 12-13)."""
    torch.manual_seed(0)
    coords = torch.rand(15, 2)
    a = gm._knn_adjacency(coords, k=6)
    p = gm._rrwp(a, steps=3)
    t = a / a.sum(1, keepdim=True).clamp_min(1.0)
    assert torch.allclose(p[0], t, atol=1e-6)
    assert torch.allclose(p[1], t @ t, atol=1e-6)
    assert torch.allclose(p[2], t @ t @ t, atol=1e-6)
    # rows of each power are sub-stochastic probabilities in [0,1]
    assert (p >= -1e-6).all() and (p <= 1 + 1e-6).all()


def test_encoder_permutation_equivariant():
    """The D-RRWP + GRASS core is permutation-equivariant (Eq. 23); rewiring is the
    stochastic augmentation, so we test the core with rewiring switched off."""
    torch.manual_seed(0)
    model = gm.GarnetTSP(gm.Config(rewire_r=0))
    model.eval()
    coords = torch.rand(14, 2)
    node, graph = model.encoder(coords)
    perm = torch.randperm(14)
    node_p, graph_p = model.encoder(coords[perm])
    assert torch.allclose(node[perm], node_p, atol=1e-4)   # node emb permutes with input
    assert torch.allclose(graph, graph_p, atol=1e-4)        # graph emb is permutation-invariant


@pytest.mark.parametrize("n", [2, 5, 10, 20])
def test_greedy_decode_is_valid_tour(n):
    """Greedy decoding visits every city exactly once (a valid Hamiltonian permutation)."""
    torch.manual_seed(1)
    model = gm.GarnetTSP()
    coords = torch.rand(n, 2)
    tour = model.tour(coords)
    assert sorted(tour) == list(range(n))


def test_tour_is_deterministic():
    """Greedy decode is deterministic — same instance, same tour (reproducible inference)."""
    model = gm.GarnetTSP()
    coords = torch.rand(12, 2)
    assert model.tour(coords) == model.tour(coords)


def test_enabling_garnet_never_degrades(monkeypatch):
    """The integration guarantee: switching GARNET on yields a clinical objective that is
    >= the objective with it off (pick_best can only improve when given more candidates),
    and GARNET's own candidate is feasible (the independent re-scorer would raise otherwise)."""
    solver, sg, models = _routing()
    req = _sample_req(models)
    monkeypatch.delenv("GARNET_ENABLED", raising=False)
    sg._load_model.cache_clear()
    off = _score(req, solver.plan(req))

    monkeypatch.setenv("GARNET_ENABLED", "1")
    sg._load_model.cache_clear()
    g = sg.plan(req)
    assert g is not None
    _score(req, g)  # raises on any cold/capacity/precedence/double-serve violation
    on = _score(req, solver.plan(req))

    assert on["clinical_key"] >= off["clinical_key"]
