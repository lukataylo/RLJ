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

ORCH = os.environ.get("ORCH", "http://localhost:8000").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", os.environ.get("MODEL", "nemotron"))
INTERVAL_S = float(os.environ.get("INTERVAL_S", "60"))

# LLM backend — env-driven so the SAME agent runs against local Ollama on the GB10 OR a
# hosted OpenAI-compatible endpoint (e.g. Nebius Nemotron) with zero code change.
#   LLM_BASE_URL : ollama base (…:11434) or OpenAI-style base (…/v1)
#   LLM_API_KEY  : bearer token for hosted endpoints (empty for local Ollama)
#   LLM_STYLE    : "ollama" | "openai"  (auto: openai if an API key is set)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", os.environ.get("OLLAMA", "http://localhost:11434")).rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_STYLE = os.environ.get("LLM_STYLE", "openai" if LLM_API_KEY else "ollama")
# Back-compat alias used in log lines.
OLLAMA = LLM_BASE_URL

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


def _match_model(desired: str, available: list[str]) -> str:
    """Pick the served Ollama tag that best matches ``desired`` so the operator can use
    ``nemotron``, ``nemotron:latest`` and ``nemotron3:33b`` interchangeably. Order: exact
    -> ``<base>:latest`` -> same base any tag -> base-token overlap -> unchanged. (Mirrors
    orchestrator/llm.py; duplicated rather than cross-imported to keep the agent standalone.)"""
    if not available or desired in available:
        return desired
    base = desired.split(":", 1)[0].lower()
    for n in available:
        if n.lower() == f"{base}:latest":
            return n
    for n in available:
        if n.split(":", 1)[0].lower() == base:
            return n
    for n in available:
        nb = n.split(":", 1)[0].lower()
        if base and (base in nb or nb in base):
            return n
    return desired


def _resolve_ollama_model() -> str:
    """Resolve ``MODEL`` against Ollama's live ``/api/tags`` (local backend only). Falls
    back to the configured name on any failure, so a missing tag list never blocks start."""
    if LLM_STYLE != "ollama":
        return MODEL
    try:
        tags = _get_json(f"{LLM_BASE_URL}/api/tags", timeout=5.0)
        names = [m.get("name", "") for m in tags.get("models", [])]
        return _match_model(MODEL, [n for n in names if n])
    except Exception as e:  # noqa: BLE001 - tags unreachable -> use configured name as-is
        print(f"[warn] could not list Ollama models ({e}); using model={MODEL}", flush=True)
        return MODEL


def _post_json(url: str, payload: dict, timeout: float = 10.0, headers: dict | None = None):
    data = json.dumps(payload).encode()
    h = {"content-type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _chat(messages: list[dict], *, json_format: bool = False,
          temperature: float = 0.3, timeout: float = 150.0) -> str:
    """One chat call against the configured backend (Ollama or OpenAI-compatible/Nebius)."""
    if LLM_STYLE == "openai":
        body = {"model": MODEL, "messages": messages, "temperature": temperature}
        if json_format:
            body["response_format"] = {"type": "json_object"}
        headers = {"authorization": f"Bearer {LLM_API_KEY}"} if LLM_API_KEY else None
        resp = _post_json(f"{LLM_BASE_URL}/chat/completions", body, timeout=timeout, headers=headers)
        choices = resp.get("choices") or [{}]
        return (choices[0].get("message", {}).get("content") or "")
    # ollama
    body = {"model": MODEL, "stream": False, "messages": messages, "options": {"temperature": temperature}}
    if json_format:
        body["format"] = "json"
    resp = _post_json(f"{LLM_BASE_URL}/api/chat", body, timeout=timeout)
    return (resp.get("message", {}).get("content") or "")


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
    t0 = time.time()
    content = _chat([{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
                    json_format=True, temperature=0.2, timeout=120.0) or "{}"
    dt = time.time() - t0
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


def _hotspot_summary(cells: list[dict]) -> str:
    hot = sorted(cells, key=lambda c: c.get("congestion", 0), reverse=True)[:6]
    return "; ".join(f"({c['lat']:.4f},{c['lng']:.4f}) {c['congestion']:.2f}" for c in hot) or "none reported"


def fetch_state() -> dict:
    try:
        return _get_json(f"{ORCH}/state")
    except Exception:  # noqa: BLE001
        return {}


def answer_pending_tasks(cells: list[dict]) -> None:
    """Operator asked NemoClaw something -> reason with local Nemotron, post the answer."""
    try:
        tasks = _get_json(f"{ORCH}/agent/tasks")
    except Exception:  # noqa: BLE001
        return
    for t in tasks[:2]:
        ctx = f"Live congestion hotspots (lat,lng,level): {_hotspot_summary(cells)}. Junctions monitored: {len(JUNCTIONS)}."
        try:
            ans = (_chat([
                {"role": "system", "content": "You are NemoClaw, a London medical-courier traffic operations agent. Answer the operator concisely (max 3 sentences), grounded in the live data."},
                {"role": "user", "content": f"{ctx}\nOperator question: {t['question']}"}],
                temperature=0.3, timeout=150.0) or "").strip()[:400] or "(no answer)"
        except Exception as e:  # noqa: BLE001
            ans = f"(agent error: {e})"
        try:
            _post_json(f"{ORCH}/agent/answer", {"task_id": t["id"], "answer": ans})
            print(f"[ok] answered {t['id']}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] answer post failed: {e}", flush=True)


def assess_drivers(state: dict, cells: list[dict]) -> None:
    """Per-driver: on_time | reroute_suggested | at_risk vs live congestion."""
    couriers = state.get("couriers", [])
    if not couriers:
        return
    drv = [{"id": c["id"], "name": c.get("name"),
            "loc": [c["location"]["lat"], c["location"]["lng"]]} for c in couriers]
    prompt = (f"Drivers: {json.dumps(drv)}\nCongestion hotspots (lat,lng,level): {_hotspot_summary(cells)}\n"
              "For each driver id, classify status as on_time|reroute_suggested|at_risk with a short note "
              '(<14 words). Reply ONLY JSON {"assessments":[{"courier_id":str,"status":str,"note":str}]}.')
    try:
        content = _chat([{"role": "system", "content": "You assess delivery drivers against live congestion. Reply only JSON."},
                         {"role": "user", "content": prompt}],
                        json_format=True, temperature=0.2, timeout=150.0) or "{}"
        items = json.loads(content).get("assessments", [])
    except Exception as e:  # noqa: BLE001
        print(f"[warn] assess failed: {e}", flush=True)
        return
    valid = {"on_time", "reroute_suggested", "at_risk"}
    out = [{"courier_id": str(x["courier_id"]),
            "status": x.get("status") if x.get("status") in valid else "on_time",
            "note": str(x.get("note", ""))[:120]}
           for x in items if x.get("courier_id")]
    if out:
        try:
            _post_json(f"{ORCH}/fleet/assessments", {"assessments": out})
            print(f"[ok] posted {len(out)} driver assessment(s)", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] assessment post failed: {e}", flush=True)


def main():
    tick_s = float(os.environ.get("TICK_S", str(INTERVAL_S if INTERVAL_S <= 20 else 12)))
    # Resolve the configured model to whatever nemotron tag Ollama actually serves, once at
    # startup, so MODEL=nemotron reaches nemotron:latest OR nemotron3:33b transparently.
    global MODEL
    MODEL = _resolve_ollama_model()
    print(f"signal_agent: orch={ORCH} ollama={OLLAMA} model={MODEL} tick={tick_s}s", flush=True)
    tick = 0
    while True:
        tick += 1
        cells = fetch_congestion()
        answer_pending_tasks(cells)             # responsive to operator asks every tick
        if tick % 6 == 1:                       # signal recs ~every 6 ticks
            recs = ask_nemotron(cells)
            if recs:
                try:
                    res = _post_json(f"{ORCH}/signals/recommendations", {"recommendations": recs})
                    print(f"[ok] posted {res.get('accepted')} signal rec(s)", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"[warn] rec post failed: {e}", flush=True)
        if tick % 6 == 3:                       # per-driver assessment offset from recs
            assess_drivers(fetch_state(), cells)
        time.sleep(tick_s)


if __name__ == "__main__":
    main()
