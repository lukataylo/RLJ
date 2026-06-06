# PulseGo — Demo script — 4 minutes to the win

> **PulseGo — live medical logistics for London.** · [pulsego.org](https://pulsego.org)

> One line: **A local-first, agentic medical-courier optimiser for London that runs entirely
> on a DGX Spark (GB10) — and every number on screen is backed by a test that just passed.**

## Setup (before you present)

```bash
make install                       # python deps
make data                          # build + verify datasets (writes data/manifest.json + map geojson)
make verify                        # GREEN gate; show verification/VERIFICATION.md first
# three terminals:
cd routing && uvicorn app:app --port 8100        # GPU ACO (+ local-search) service
cd orchestrator && ROUTING_URL=http://localhost:8100 uvicorn app:app --port 8000
cd frontend && npm install && npm run dev        # http://localhost:5173
```

## The 4-minute arc

1. **Open on the gate (15s).** Show `make verify` output / `verification/VERIFICATION.md`:
   *"Everything I'm about to claim is bound to an external test. Must-pass is GREEN.
   I'm not asking you to trust the demo — the tests already checked it."*

2. **First screen (20s).** Open the command center and hit **Start demo** in the top bar.
   The map should already show routes plus three operational overlays: planned works,
   kerbside handoff/loading points, and TfL roadside message signs. *"Fastest route is
   not enough; PulseGo knows where disruption is coming from and where a medical courier
   can actually stop."*

3. **Intake by voice (30s).** A clinic "calls in" a STAT sample (ElevenLabs / text intake) →
   the local model extracts a structured job → it lands on the map and the agent log narrates
   the dispatch. *Bound by `voice-loop`.*

4. **The money shot — close a road (45s).** Use the scenario controls to close a road.
   The planned-works/roadside-sign context explains the disruption; the solver re-optimises,
   routes redraw, and the kerbside layer shows the handoff is still operationally feasible.
   The agent calls the courier with the new ETA. *Bound by `reroute-on-closure`.*

5. **The GB10 story (30s).** Scoreboard: solver = `gpu-aco+ls`, re-plan in milliseconds.
   *"This is why it's on the box: re-optimising the whole fleet in real time, on patient data
   that never leaves the premises."* Bound by `realtime-replan`.

6. **Expo/local box (30s).** In the driver Expo app, use Settings → **Use local Nemotron box**.
   The phone points at the local orchestrator/NemoClaw stack instead of production.

7. **Close on impact (15s).** *"41/41 windows met vs 39 for naive dispatch; STAT on-time 100%.
   Verified, local, agentic. That's the system."*

## The numbers (all test-backed)

| Metric | Value | Bound test |
|---|---|---|
| Windows met (backtest) | **41/41** (greedy 39) | `test_beats_greedy` |
| STAT clinical on-time | **100%** (9/9) | `test_stat_window_compliance` |
| Re-plan latency (CPU dev) | **~120 ms** avg (GB10 target <50 ms) | `test_solve_budget` |
| Datasets verified | all manifest datasets dq_passed/loadable | `test_every_dataset_dq_passed_and_loadable` |
| Claims verified | generated live by the gate | `make verify` |

## Fallbacks (decided, never demo without a path)

GPU ACO → cuOpt → OR-Tools → greedy (orchestrator) · live TfL → manual closure ·
ElevenLabs → on-screen agent log · local model NLU → keyword parser. See `ARCHITECTURE.md`.
