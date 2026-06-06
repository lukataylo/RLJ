# RLJ — Time-Critical Medical Logistics for London

> Hack for Impact London (NVIDIA). A local-first, agentic medical courier optimiser
> that runs entirely on a **DGX Spark (GB10)** — patient data never leaves the box.

Collect pathology samples and deliver urgent meds across London **within clinical
time windows**, re-planning live when a road closes, a courier drops out, or a STAT
request arrives. The agent *reasons and communicates* (local Nemotron via NemoClaw +
ElevenLabs voice); the GPU *computes the routes* (custom solver on the GB10).

## The three workstreams (one owner / agent each)

| Stream | Dir | Owner | What it ships |
|--------|-----|-------|---------------|
| 🎙️ **Voice** | [`voice/`](voice/) | Agent 1 | ElevenLabs inbound intake (clinic call → structured job) + outbound courier/clinic ETA calls. Runs as a NemoClaw agent on local Nemotron. |
| 🧭 **Routing** | [`routing/`](routing/) | Agent 2 | GPU-accelerated custom router (CuPy/CUDA ACO) + travel-time engine. Implements the `/optimize` contract. Fully local, no egress. |
| 🗺️ **Frontend** | [`frontend/`](frontend/) | Agent 3 | deck.gl + MapLibre live map: couriers moving, jobs by urgency, live re-route, agent narration panel. |

The **[`orchestrator/`](orchestrator/)** is the shared hub everyone integrates through.
It ships with a **built-in greedy router**, so the whole system runs end-to-end from
hour zero — that is your guaranteed demo while the real solver and voice land.

## How the streams stay unblocked

Everyone codes against **[`contracts/`](contracts/)** (the data model + the orchestrator
REST/WebSocket API). Run the mock orchestrator and each stream develops against it
independently:

```bash
# terminal 1 — the hub (works on its own with the greedy fallback router)
cd orchestrator && pip install -r requirements.txt && uvicorn app:app --reload --port 8000
# terminal 2/3/4 — each stream points at http://localhost:8000
```

- **Frontend** consumes `GET /state` + `WS /ws`, calls `POST /jobs|/disruptions|/optimize`.
- **Routing** implements `POST /optimize`; orchestrator proxies to it when up, falls back to greedy when not.
- **Voice** posts inbound jobs to `POST /jobs` and listens on `WS /ws` for `notification` events to place outbound calls.

See **[AGENTS.md](AGENTS.md)** for the working agreement and **[ARCHITECTURE.md](ARCHITECTURE.md)** for the data flow.

## Local / NemoClaw

Voice and the dispatch reasoning run as **NemoClaw** sandboxed agents on the DGX Spark
with local Nemotron inference. Policies live in **[`nemoclaw/`](nemoclaw/)** (voice gets
egress to ElevenLabs only; routing gets none). See [`nemoclaw/README.md`](nemoclaw/README.md).

## Quality gates

Claims are credited only by external tests in [`verification/run.py`](verification/run.py);
manual review or agent self-assessment does not mark work as verified.

```bash
python3 -m venv .venv
make install
make quality-gate
```

`make quality-gate` runs the Python verification ledger and the frontend TypeScript/Vite
build. The same checks run in GitHub Actions via `.github/workflows/quality-gates.yml`.
