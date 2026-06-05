"""Completeness gate: every endpoint/event declared in the contracts must exist.

Imports the FastAPI apps in-process (handling the ``app``/``models`` module-name
collision between orchestrator/ and routing/ by isolating sys.path + sys.modules
per import) and asserts that every REST path in ``contracts/api.md`` and
``contracts/driver-api.md`` is reachable on the right service.

A separate test asserts every WebSocket event declared in the contracts is actually
emitted by the orchestrator source. This is where a real gap currently lives:
``courier_moved`` is declared (and the frontend handles it) but the orchestrator
never emits it — that assertion is EXPECTED TO FAIL and is documented in
verification/AUDIT.md.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Modules that exist (with the same name) in more than one stream and must be
# evicted from the import cache when switching which app we load.
_COLLIDING = (
    "app", "models", "seed", "greedy", "congestion",
    "solver", "solver_baseline", "solver_ortools", "solver_aco",
    "solver_ls", "traveltime",
)


def _load_app(subdir: str):
    p = str(ROOT / subdir)
    sys.path.insert(0, p)
    try:
        for mod in _COLLIDING:
            sys.modules.pop(mod, None)
        m = importlib.import_module("app")
        return m.app
    finally:
        if p in sys.path:
            sys.path.remove(p)


def _normalize(path: str) -> str:
    """Collapse path params to a placeholder so `{id}` == `{driver_id}`."""
    return re.sub(r"\{[^}]+\}", "{}", path.rstrip("/")) or "/"


def _app_routes(app) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for r in app.routes:
        path = _normalize(getattr(r, "path", ""))
        methods = getattr(r, "methods", None)
        if methods:
            for mth in methods:
                out.add((mth.upper(), path))
        else:  # websocket route
            out.add(("WS", path))
    return out


# --- contract parsing --------------------------------------------------------
_REST_ROW = re.compile(r"^\|\s*(GET|POST|PUT|DELETE|PATCH)\s*\|\s*`([^`]+)`")
_WS_ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|")
# Table-header literals that appear in the first cell but are not events.
_WS_HEADER_LITERALS = {"type", "payload"}


def _contract_rest_endpoints(md: str) -> list[tuple[str, str]]:
    eps = []
    for line in md.splitlines():
        m = _REST_ROW.match(line)
        if m:
            eps.append((m.group(1).upper(), _normalize(m.group(2))))
    return eps


def _contract_ws_events(md: str) -> list[str]:
    return [
        m.group(1)
        for line in md.splitlines()
        if (m := _WS_ROW.match(line)) and m.group(1) not in _WS_HEADER_LITERALS
    ]


def _read(name: str) -> str:
    return (ROOT / "contracts" / name).read_text()


# ----------------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------------
def test_apps_import_cleanly():
    orch = _load_app("orchestrator")
    routing = _load_app("routing")
    assert orch is not None and routing is not None


def test_orchestrator_rest_endpoints_implemented():
    app = _load_app("orchestrator")
    have = _app_routes(app)
    # The orchestrator implements BOTH api.md and driver-api.md surfaces (minus the
    # routing-only table, which lives on the routing service).
    api = _read("api.md")
    driver = _read("driver-api.md")
    # api.md contains a "Routing service" section; those endpoints belong to routing.
    orch_section = api.split("## Routing service")[0]
    declared = set(_contract_rest_endpoints(orch_section)) | set(_contract_rest_endpoints(driver))
    missing = sorted(e for e in declared if e not in have)
    assert not missing, f"Orchestrator missing contract endpoints: {missing}\nhave={sorted(have)}"


def test_orchestrator_websocket_present():
    app = _load_app("orchestrator")
    assert ("WS", "/ws") in _app_routes(app)


def test_routing_rest_endpoints_implemented():
    app = _load_app("routing")
    have = _app_routes(app)
    api = _read("api.md")
    routing_section = "## Routing service" + api.split("## Routing service")[1]
    declared = set(_contract_rest_endpoints(routing_section))
    missing = sorted(e for e in declared if e not in have)
    assert not missing, f"Routing service missing contract endpoints: {missing}\nhave={sorted(have)}"


def test_ws_events_declared_are_emitted():
    """Every WebSocket event declared in the contracts must actually be emitted by
    the orchestrator. NOTE: this currently FAILS for `courier_moved` — a declared
    contract event with a ready frontend handler that the server never sends.
    See verification/AUDIT.md (HIGH-1)."""
    src = (ROOT / "orchestrator" / "app.py").read_text()
    declared = set(_contract_ws_events(_read("api.md"))) | set(_contract_ws_events(_read("driver-api.md")))
    not_emitted = sorted(
        ev for ev in declared
        if f'emit("{ev}"' not in src and f'"type": "{ev}"' not in src
    )
    assert not not_emitted, (
        "Contract WebSocket events declared but never emitted by orchestrator: "
        f"{not_emitted}"
    )
