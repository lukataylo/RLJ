#!/usr/bin/env python3
"""Judge smoketest — a fast READY/NOT-READY check of the live demo, not the full gate.

The full gate (`make verify`) runs 272 tests including the slow browser e2e. In the last
hours before a demo you want a ~10s answer to one question: *does the thing the judges
will see actually work right now?* This hits the live stack's demo-critical happy paths
and prints a single verdict.

Run:  make smoke   (or  ./.venv/bin/python verification/smoke.py)

Assumes the dev stack is up (orchestrator :8000, routing :8100, frontend :5173). Exits 0
iff every CRITICAL check passes; optional checks (e.g. ElevenLabs TTS, which needs a key)
only warn.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

ORCH = "http://127.0.0.1:8000"
ROUTING = "http://127.0.0.1:8100"
FRONTEND = "http://127.0.0.1:5173"

# ANSI (degrade to plain if not a tty)
_TTY = sys.stdout.isatty()
G = "\033[32m" if _TTY else ""
R = "\033[31m" if _TTY else ""
Y = "\033[33m" if _TTY else ""
DIM = "\033[2m" if _TTY else ""
B = "\033[1m" if _TTY else ""
X = "\033[0m" if _TTY else ""

results: list[tuple[str, bool, bool, str]] = []  # (name, ok, critical, detail)


def _req(method: str, url: str, body: dict | None = None, timeout: float = 8.0):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"content-type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - localhost only
        ct = r.headers.get("content-type", "")
        raw = r.read()
        return r.status, (json.loads(raw) if "json" in ct else raw)


def check(name: str, critical: bool = True):
    def deco(fn):
        try:
            ok, detail = fn()
        except urllib.error.HTTPError as e:
            ok, detail = False, f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append((name, ok, critical, detail))
        tag = f"{G}PASS{X}" if ok else (f"{R}FAIL{X}" if critical else f"{Y}WARN{X}")
        print(f"  [{tag}] {name:32s} {DIM}{detail}{X}")
        return fn
    return deco


# Shared state captured across checks (first courier id, etc.)
state: dict = {}


def main() -> int:
    print(f"\n{B}PulseGo judge smoketest{X} {DIM}— live demo-critical paths{X}\n")
    t0 = time.time()

    @check("stack: orchestrator up")
    def _():
        s, b = _req("GET", f"{ORCH}/healthz")
        state["health"] = b
        return s == 200 and b.get("status") == "ok", f"routing_service={b.get('routing_service')} · llm={b.get('llm_provider')}"

    @check("stack: routing service up")
    def _():
        s, _b = _req("GET", f"{ROUTING}/healthz")
        return s == 200, f"{ROUTING}"

    @check("stack: frontend served", critical=False)
    def _():
        s, _b = _req("GET", FRONTEND)
        return s == 200, FRONTEND

    @check("demo seed → live fleet")
    def _():
        s, b = _req("POST", f"{ORCH}/demo/seed")
        return s == 200 and b.get("couriers", 0) > 0, f"{b.get('couriers')} couriers · {b.get('jobs')} jobs · {b.get('routes')} routes"

    @check("plan → real routing solver")
    def _():
        s, b = _req("GET", f"{ORCH}/plan")
        obj = b.get("objective", {}) or {}
        routes = b.get("routes", [])
        state["solver"] = obj.get("solver")
        return s == 200 and len(routes) > 0, f"solver={obj.get('solver')} · windows {obj.get('windows_met')}/{obj.get('windows_total')}"

    @check("state → couriers + jobs")
    def _():
        s, b = _req("GET", f"{ORCH}/state")
        couriers = b.get("couriers", [])
        if couriers:
            state["courier_id"] = couriers[0].get("id")
        return s == 200 and len(couriers) > 0, f"{len(couriers)} couriers · {len(b.get('jobs', []))} jobs"

    @check("ask NemoClaw → answers")
    def _():
        s, b = _req("POST", f"{ORCH}/agent/ask", {"question": "how many couriers are active?"})
        return s == 200 and bool(b.get("answer")), f"\"{(b.get('answer') or '')[:46]}…\""

    @check("ask NemoClaw → decision card")
    def _():
        cid = state.get("courier_id", "crt-1")
        s, b = _req("POST", f"{ORCH}/agent/ask", {"question": f"reroute courier {cid} around congestion"})
        act = b.get("action") or {}
        return s == 200 and act.get("type") == "redirect", f"action={act.get('type')} → {act.get('endpoint')}"

    @check("driver ask → route-grounded")
    def _():
        cid = state.get("courier_id", "crt-1")
        s, b = _req("POST", f"{ORCH}/driver/ask", {"question": "where is my next stop?", "courier_id": cid})
        return s == 200 and bool(b.get("answer")), f"\"{(b.get('answer') or '')[:46]}…\""

    @check("Tower Bridge closure → reroute card")
    def _():
        s, b = _req("POST", f"{ORCH}/scenario/bridge-closure")
        state["bridge_courier"] = b.get("courier_id")
        return s == 200 and b.get("ok") and b.get("courier_id"), f"targets {b.get('courier_id')} · disr {b.get('disruption_id')}"

    @check("confirm reroute → re-plans")
    def _():
        cid = state.get("bridge_courier") or state.get("courier_id", "crt-1")
        s, b = _req("POST", f"{ORCH}/couriers/{cid}/redirect")
        return s == 200 and b.get("ok"), f"solver={b.get('solver')} · windows_met={b.get('windows_met')}"

    @check("upcoming conditions feed")
    def _():
        s, b = _req("GET", f"{ORCH}/conditions/upcoming?within_hours=24")
        return s == 200 and b.get("count", 0) > 0, f"{b.get('count')} conditions"

    @check("live CCTV cameras", critical=False)
    def _():
        s, b = _req("GET", f"{ORCH}/cctv/cameras")
        n = len(b) if isinstance(b, list) else 0
        return s == 200 and n > 0, f"{n} cameras"

    @check("ElevenLabs TTS (needs key)", critical=False)
    def _():
        s, b = _req("POST", f"{ORCH}/tts", {"text": "PulseGo is ready."})
        n = len(b) if isinstance(b, (bytes, bytearray)) else 0
        return s == 200 and n > 0, f"{n} bytes audio" if n else "no audio (set ELEVENLABS_API_KEY)"

    dt = time.time() - t0
    crit_fail = [n for n, ok, c, _ in results if c and not ok]
    warns = [n for n, ok, c, _ in results if not c and not ok]
    passed = sum(1 for _, ok, _, _ in results if ok)

    print()
    if not crit_fail:
        print(f"{G}{B}  ✓ READY TO DEMO{X}  {passed}/{len(results)} checks passed in {dt:.1f}s"
              + (f" {Y}({len(warns)} optional warn: {', '.join(warns)}){X}" if warns else ""))
        return 0
    print(f"{R}{B}  ✗ NOT READY{X}  {len(crit_fail)} critical failure(s): {R}{', '.join(crit_fail)}{X}")
    print(f"{DIM}  Is the stack up? orchestrator :8000 · routing :8100 · frontend :5173{X}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
