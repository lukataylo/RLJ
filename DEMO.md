# Demo script — 4 minutes to the win

> One line: **A local-first, agentic medical-courier optimiser for London that runs entirely
> on a DGX Spark (GB10) — and every number on screen is backed by a test that just passed.**

## Setup (before you present)

```bash
make install                       # python deps
make data                          # build + verify datasets (writes data/manifest.json + map geojson)
make verify                        # GREEN gate: 15/15 claims, 13/13 must-pass  ← show this first
# three terminals:
cd routing && uvicorn app:app --port 8100        # GPU ACO (+ local-search) service
cd orchestrator && ROUTING_URL=http://localhost:8100 uvicorn app:app --port 8000
cd frontend && npm install && npm run dev        # http://localhost:5173
python scripts/demo_seed.py        # now-anchored London scenario
```

## The 4-minute arc

1. **Open on the gate (15s).** Show `make verify` output / `verification/VERIFICATION.md`:
   *"Everything I'm about to claim is bound to an external test. 15/15 verified, must-pass GREEN.
   I'm not asking you to trust the demo — the tests already checked it."*

2. **The map (45s).** Dark London command-center: couriers, jobs colour-coded by clinical
   priority (STAT red), live traffic flow, 3D buildings. KPI cards each carry a ✅ badge read
   live from `status.json`. *"STAT on-time 100% — verified by `test_stat_window_compliance`."*

3. **Intake by voice (30s).** A clinic "calls in" a STAT sample (ElevenLabs / text intake) →
   the local model extracts a structured job → it lands on the map and the agent log narrates
   the dispatch. *Bound by `voice-loop`.*

4. **The money shot — close a road (45s).** Hit **Close road**. The TfL-style closure inflates
   the affected corridor; the GPU solver re-optimises and routes redraw to protect the STAT
   window; the agent calls the courier with the new ETA. *Bound by `reroute-on-closure`.*

5. **The GB10 story (30s).** Scoreboard: solver = `gpu-aco+ls`, re-plan in milliseconds.
   *"This is why it's on the box: re-optimising the whole fleet in real time, on patient data
   that never leaves the premises."* Bound by `realtime-replan`.

6. **Unplug the cable (30s).** Pull the network. ElevenLabs/TfL drop; routing + the local model
   keep running. *"Strike day, outage, dead zone — it still routes. Local-first isn't a slogan."*

7. **Close on impact (15s).** *"41/41 windows met vs 39 for naive dispatch; STAT on-time 100%.
   Verified, local, agentic. That's the system."*

## The numbers (all test-backed)

| Metric | Value | Bound test |
|---|---|---|
| Windows met (backtest) | **41/41** (greedy 39) | `test_beats_greedy` |
| STAT clinical on-time | **100%** (9/9) | `test_stat_window_compliance` |
| Re-plan latency (CPU dev) | **~120 ms** avg (GB10 target <50 ms) | `test_solve_budget` |
| Datasets verified | **3/3** dq_passed | `test_only_verified_data_loadable` |
| Claims verified | **15/15**, must-pass **13/13** | `make verify` |

## Fallbacks (decided, never demo without a path)

GPU ACO → cuOpt → OR-Tools → greedy (orchestrator) · live TfL → manual closure ·
ElevenLabs → on-screen agent log · local model NLU → keyword parser. See `ARCHITECTURE.md`.
