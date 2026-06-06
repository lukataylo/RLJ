"""Fast, deterministic unit test for the NemoClaw local agent.

We force the OFFLINE path by monkeypatching nemo_agent.fetch_tfl to an async fn
returning [] so the agent uses its bundled real-London FALLBACK rotation. This
makes the loop deterministic (no network) and lets us assert the three guarantees
the agent advertises: it announces itself online with its sources, it narrates a
real London disruption, and it injects a road_closure for a SEVERE fallback item.

Runs the async coroutine via asyncio.run (no pytest-asyncio dependency).
"""
from __future__ import annotations
import asyncio

import nemo_agent  # orchestrator/ is on sys.path via tests/conftest.py


def test_nemo_agent_offline_narrates_and_injects(monkeypatch):
    async def _fake_fetch_tfl():
        return []

    monkeypatch.setattr(nemo_agent, "fetch_tfl", _fake_fetch_tfl)

    emitted: list[tuple[str, dict]] = []
    injected: list[dict] = []

    async def emit(type_: str, payload: dict) -> None:
        emitted.append((type_, payload))

    async def inject(d: dict) -> None:
        injected.append(d)

    async def _drive() -> None:
        # bounded: 3 cycles at a 10ms interval — finishes in well under a second.
        await asyncio.wait_for(
            nemo_agent.run(emit, inject, interval_s=0.01, max_cycles=3),
            timeout=5.0,
        )

    asyncio.run(_drive())

    assert emitted, "agent emitted nothing"

    # 1) First emit is the 'online' announcement naming its sources.
    first_type, first_payload = emitted[0]
    assert first_type == "agent_log"
    assert first_payload.get("source") == "nemoclaw"
    msg0 = first_payload.get("message", "")
    assert "online" in msg0.lower()
    assert "sources" in msg0.lower(), f"online line should name its sources: {msg0!r}"

    # 2) At least one later line is a fallback London disruption from the agent.
    descriptions = {it["description"] for it in nemo_agent.FALLBACK}
    later = emitted[1:]
    assert later, "agent never narrated a disruption after coming online"
    narrated_fallback = [
        p for (t, p) in later
        if t == "agent_log"
        and p.get("source") == "nemoclaw"
        and any(d[:100] in p.get("message", "") for d in descriptions)
    ]
    assert narrated_fallback, (
        "no fallback London disruption was narrated; saw "
        f"{[p.get('message') for _, p in later]}"
    )

    # 3) inject called >=1 with kind 'road_closure' for a SEVERE fallback item.
    assert injected, "agent never injected a disruption"
    closures = [d for d in injected if d.get("kind") == "road_closure"]
    assert closures, f"no road_closure injected; injected={injected}"
    c0 = closures[0]
    assert c0.get("source") == "tfl"
    geom = c0.get("geometry")
    assert isinstance(geom, list) and geom, "road_closure carries no geometry"
    pt = geom[0]
    assert "lat" in pt and "lng" in pt
    # the injected point must correspond to a SEVERE fallback item in the bbox
    severe_pts = {
        (it["lat"], it["lng"]) for it in nemo_agent.FALLBACK
        if it.get("severity") in nemo_agent.SEVERE
    }
    assert (pt["lat"], pt["lng"]) in severe_pts, (
        f"injected closure {pt} is not a severe fallback location"
    )
