# Architecture

> **PulseGo — live medical logistics for London.** · [pulsego.org](https://pulsego.org)

Everything runs on **one DGX Spark (GB10)**. Local Nemotron for reasoning, local GPU
for routing, local web stack. The only outbound network is ElevenLabs (voice) and the
TfL feed (disruptions) — both behind NemoClaw egress allowlists.

```
                         ┌─────────────────────────────────────────────┐
                         │                DGX Spark (GB10)              │
                         │                                              │
  clinic phone call ───► │  🎙️ VOICE (voice/)                          │
                         │   ElevenLabs agent + local Nemotron (NLU)    │
                         │     │  POST /jobs (structured)               │
                         │     ▼                                        │
                         │  ⭐ ORCHESTRATOR (orchestrator/)  :8000      │
                         │     - in-memory state (jobs/couriers/plan)   │
                         │     - WS /ws broadcast                        │
                         │     - greedy fallback router (built in)       │
                         │     │  POST /optimize                         │
                         │     ▼                                        │
                         │  🧭 ROUTING (routing/)  :8100                 │
                         │     travel-time kernel + GPU ACO solver       │
                         │     ▲  returns Plan                           │
                         │     │                                        │
                         │  🗺️ FRONTEND (frontend/)  :5173              │
                         │     deck.gl map  ◄── WS /ws (live events)     │
                         │     "close road" / "add STAT job" ──► REST    │
                         └─────────────────────────────────────────────┘
                                   ▲                         │
                            TfL disruption feed       outbound ETA call (ElevenLabs)
```

## Control flow (the demo loop)

1. **Intake** — a clinic calls; the **voice** agent transcribes, the local model extracts a
   structured `DeliveryJob` (origin, dest, priority, time window, cold-chain), `POST /jobs`.
2. **Plan** — orchestrator triggers `/optimize`. Routing returns a `Plan` (routes + ETAs +
   which time windows are met). Orchestrator broadcasts `plan_updated` on the WS.
3. **Visualise** — frontend animates couriers and routes; urgency colour-coded.
4. **Disrupt** — a road closes (TfL feed or the demo "close road" button) → `POST /disruptions`
   → re-optimize → routes redraw to protect the at-risk windows.
5. **Communicate** — orchestrator emits `notification` events; the **voice** agent places an
   outbound call / TTS to the courier and clinic with the new ETA, and narrates *why* on the
   `agent_log` stream shown in the UI.
6. **Resilience** — pull the network cable: ElevenLabs/TfL drop, but routing + the local model
   keep the core loop alive. This is the local-first money shot.

## Why local (have these ready for judges)

- **PII/PHI** in requests — NHS data governance keeps it on the box.
- **Latency** — continuous re-optimization needs the GPU local.
- **Resilience** — keeps working during network/road disruption (the strike theme).
- **Cost** — re-optimize every few seconds, no per-call cloud bill.

## Fallback ladder (decide now, never demo without a working path)

| If this fails… | Fall back to |
|---|---|
| Custom GPU solver | NVIDIA cuOpt, then OR-tools, then orchestrator's greedy router |
| Custom travel-time kernel | local Valhalla matrix (real London streets), then OSMnx/networkx, then haversine |
| Live TfL feed | pre-recorded / manual disruption injection |
| ElevenLabs voice | text intake + on-screen `agent_log` narration |
| Local model NLU flaky | constrained JSON-output prompt + canned demo requests |
