# RLJ Completeness Audit

Independent completeness audit of the whole repo (orchestrator/, routing/, voice/,
data/, frontend/src/, driver-app/src/, scripts/). Goal: find everything unfinished —
stubs, unwired UI, dead/unimplemented endpoints, silent error-swallowing, dead exports.

- Date: 2026-06-06
- Auditor scope: read-only. No source files were edited.
- Test harness: `tests/completeness/` (new), run with
  `./.venv/bin/python -m pytest tests/completeness -q`.
- Result: **10 passed, 1 failed** — the single failure is the one real gap below
  (HIGH-1). The rest of the tree is clean.

---

## Summary by severity

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH     | 1 |
| MEDIUM   | 0 |
| LOW      | 0 |
| Intentional / allowed (not defects) | 2 |

The codebase is in very good shape: no `TODO`/`FIXME`/`XXX` in source, no
NotImplementedError outside the two documented SEAMs, no placeholder `...` bodies,
every REST endpoint in both contracts is implemented and reachable, every React
button is wired (or is a form submit), no `href="#"` dead links, all components are
imported and rendered, and every `except` block is an intentional fallback (logged
or graceful-degradation) rather than silent swallowing in a non-fallback context.

---

## Findings (punch list)

### HIGH

**HIGH-1 — Contract WebSocket event `courier_moved` is declared but never emitted.**
- Declared in `contracts/api.md` (Orchestrator → WebSocket events table: `courier_moved | {courier_id, location} | frontend`).
- Consumer is fully built: `frontend/src/types.ts:132` (union member) and
  `frontend/src/store.ts:107` (`case "courier_moved"` updates courier location).
- Producer is missing: `orchestrator/app.py` emits `state`, `job_created`,
  `plan_updated`, `notification`, `disruption`, `agent_log`, `driver_joined`,
  `congestion_updated` — but **never** `courier_moved`. There is also no
  server-side courier-movement loop (only `while True` at `orchestrator/app.py:308`
  is the WS receive loop). Couriers therefore never animate from server events; the
  declared real-time courier-movement channel is dead.
- Fix suggestion: add a background task in `orchestrator/app.py` that advances
  courier positions along their planned routes and calls
  `await HUB.emit("courier_moved", {"courier_id": ..., "location": {...}})`, OR remove
  `courier_moved` from `contracts/api.md` and the frontend handler if movement is
  intended to be client-side only.
- Failing test: `tests/completeness/test_endpoints_implemented.py::test_ws_events_declared_are_emitted`
  → `AssertionError: Contract WebSocket events declared but never emitted by orchestrator: ['courier_moved']`.

---

## Intentional / allowed (documented by design — NOT defects)

These are explicitly documented stubs and are excluded from the stub tests via a
minimal allowlist (`routing/traveltime.py` only).

1. **`routing/traveltime.py:171` `gpu_sssp_matrix(...)`** — raises
   `NotImplementedError`. GB10 GPU single-source-shortest-path tier; documented SEAM,
   not implemented on this dev box by design (`routing/traveltime.py:15,148`).
2. **`routing/traveltime.py:193` `osmnx_matrix(...)`** — raises `NotImplementedError`.
   OSMnx road-graph distance tier; documented stub only
   (`routing/traveltime.py:17,189,194`).

---

## Areas checked and found clean (no findings)

- **Python stubs**: no `NotImplementedError`, `TODO`/`FIXME`/`XXX`, `stub`/`not
  implemented`, bare `...`, or placeholder bodies in orchestrator/, routing/, voice/,
  data/, scripts/ (excluding the two SEAMs above). All bare `pass` statements are in
  intentional exception fallback ladders (`routing/solver.py:47,53,60`,
  `voice/intake.py:27`, `voice/outbound.py:26`, `voice/driver_assistant.py:37`).
- **Unwired UI**: every `<button>` in frontend/src and driver-app/src has a real
  `onClick` or is `type="submit"` inside a form (`driver-app/src/components/Signup.tsx:133`).
  No empty `() => {}` handlers, no `console.log`-only handlers, no `href="#"` links.
  Buttons verified: TopBar, MapView, BottomStrip, VerificationPanel, DemoControls (x4),
  FleetRail (x2), driver-app App (x2), AskButton, Signup (x3).
- **REST endpoints**: all 10 orchestrator endpoints (`contracts/api.md`), all 6
  driver/flywheel endpoints (`contracts/driver-api.md`), and both routing-service
  endpoints are implemented and reachable (`orchestrator/app.py`, `routing/app.py`).
  Verified by in-process import of both FastAPI apps.
- **WebSocket route** `/ws` is present on the orchestrator.
- **Error handling**: every `except` block is an intentional fallback — either logged
  (`routing/app.py:51,59,67` `log.exception(...)`), graceful degradation with `# noqa:
  BLE001` rationale comments (voice/*, data/build.py, solvers), offline-network
  fallbacks returning `None` (`data/facilities.py:74`, `data/roadgraph.py:142,178`,
  `data/towerbridge.py:179`), or dropping dead WebSocket clients
  (`orchestrator/app.py:85`). None are silent swallows in a non-fallback context.
- **Dead exports/components**: all 12 frontend components and all 7 driver-app
  components are imported and rendered at least once.

---

## How the tests map to this audit

- `tests/completeness/test_no_stubs.py`
  - `test_no_notimplemented_outside_allowlist` — PASS
  - `test_no_todo_fixme_in_source` — PASS
  - `test_no_stub_prose_outside_allowlist` — PASS (allowlist: `routing/traveltime.py`)
  - `test_no_ellipsis_placeholder_bodies` — PASS
  - `test_no_unwired_buttons` — PASS
  - `test_no_dead_hash_links` — PASS
- `tests/completeness/test_endpoints_implemented.py`
  - `test_apps_import_cleanly` — PASS
  - `test_orchestrator_rest_endpoints_implemented` — PASS
  - `test_orchestrator_websocket_present` — PASS
  - `test_routing_rest_endpoints_implemented` — PASS
  - `test_ws_events_declared_are_emitted` — **FAIL** (HIGH-1, `courier_moved`)

The failing test is left failing on purpose: it documents a real gap rather than
hiding it. Once `courier_moved` is emitted (or removed from the contract + frontend),
the full suite goes green.
