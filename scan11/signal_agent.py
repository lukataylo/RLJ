"""RLJ traffic-signal analysis agent — runs ON the DGX Spark (Scan-11, GB10).

A local-first NemoClaw-style agent: it reasons with a LOCAL Nemotron model (Ollama on the
GB10 — zero egress for inference) about how London's signalised junctions should adapt to
live congestion, and posts structured recommendations to the RLJ orchestrator on the Mac,
which renders them on the map + narrates them in the NemoClaw feed.

Loop:  GET orchestrator /congestion  ->  prompt local Nemotron (JSON)  ->  POST /signals/recommendations

Run on the box:
    ORCH=http://10.18.216.110:8000 OLLAMA=http://localhost:11434 MODEL=nemotron \
        python3 scan11/signal_agent.py
"""
from __future__ import annotations
import json
import os
import time
import urllib.request

ORCH = os.environ.get("ORCH", "http://10.18.216.110:8000").rstrip("/")
OLLAMA = os.environ.get("OLLAMA", "http://localhost:11434").rstrip("/")
MODEL = os.environ.get("MODEL", "nemotron")
INTERVAL_S = float(os.environ.get("INTERVAL_S", "60"))

# Central-London signalised junctions the agent reasons over (name, lat, lng, cycle_s).
JUNCTIONS = [
    {"name": "Aldgate gyratory", "lat": 51.5142, "lng": -0.0755, "cycle_s": 96},
    {"name": "Bank junction", "lat": 51.5134, "lng": -0.0886, "cycle_s": 110},
    {"name": "Elephant & Castle", "lat": 51.4946, "lng": -0.0997, "cycle_s": 104},
    {"name": "Euston Rd / Tottenham Ct Rd", "lat": 51.5256, "lng": -0.1340, "cycle_s": 90},
    {"name": "Tower Bridge approach", "lat": 51.5055, "lng": -0.0754, "cycle_s": 80},
    {"name": "Shoreditch High St", "lat": 51.5246, "lng": -0.0779, "cycle_s": 88},
]

SYSTEM = (
    "You are a London traffic-signal control analyst. Given signalised junctions and the "
    "current congestion field, recommend signal actions to keep time-critical medical "
    "couriers moving. Reply ONLY with JSON of the form "
    '{"recommendations":[{"name":str,"lat":num,"lng":num,'
    '"action":"retime|green_wave|hold|clear","detail":str,"confidence":0..1}]}. '
    "Pick at most 3 junctions, the most congested first. Keep each detail under 18 words."
)


def _get_json(url: str, timeout: float = 8.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post_json(url: str, payload: dict, timeout: float = 10.0):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_congestion() -> list[dict]:
    try:
        field = _get_json(f"{ORCH}/congestion")
        return field.get("cells", [])
    except Exception as e:  # noqa: BLE001
        print(f"[warn] congestion fetch failed: {e}", flush=True)
        return []


def ask_nemotron(cells: list[dict]) -> list[dict]:
    hot = sorted(cells, key=lambda c: c.get("congestion", 0), reverse=True)[:8]
    hot_txt = "; ".join(f"({c['lat']:.4f},{c['lng']:.4f}) cong={c['congestion']:.2f}" for c in hot) or "none reported"
    prompt = (
        f"Junctions: {json.dumps(JUNCTIONS)}\n"
        f"Congestion hotspots (lat,lng,level): {hot_txt}\n"
        "Recommend signal actions now."
    )
    body = {
        "model": MODEL,
        "format": "json",
        "stream": False,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
        "options": {"temperature": 0.2},
    }
    t0 = time.time()
    resp = _post_json(f"{OLLAMA}/api/chat", body, timeout=120.0)
    dt = time.time() - t0
    content = resp.get("message", {}).get("content", "{}")
    try:
        recs = json.loads(content).get("recommendations", [])
    except json.JSONDecodeError:
        print(f"[warn] model returned non-JSON ({dt:.1f}s): {content[:120]}", flush=True)
        return []
    # keep only well-formed recs
    out = []
    for r in recs[:3]:
        try:
            out.append({"name": str(r["name"]), "lat": float(r["lat"]), "lng": float(r["lng"]),
                        "action": r.get("action", "retime"), "detail": str(r.get("detail", ""))[:120],
                        "confidence": float(r.get("confidence", 0.5)), "source": "nemotron@scan-11"})
        except (KeyError, TypeError, ValueError):
            continue
    print(f"[ok] Nemotron produced {len(out)} recommendation(s) in {dt:.1f}s", flush=True)
    return out


def main():
    print(f"signal_agent: orch={ORCH} ollama={OLLAMA} model={MODEL} interval={INTERVAL_S}s", flush=True)
    while True:
        cells = fetch_congestion()
        recs = ask_nemotron(cells)
        if recs:
            try:
                res = _post_json(f"{ORCH}/signals/recommendations", {"recommendations": recs})
                print(f"[ok] posted {res.get('accepted')} recommendation(s) to orchestrator", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[warn] post failed: {e}", flush=True)
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
