# RLJ — Time-Critical Medical Logistics for London

> **Hack for Impact London (NVIDIA).** A local-first, **agentic** medical-courier optimiser
> that runs entirely on a **DGX Spark (GB10)** — patient data never leaves the box — and where
> **every claim on screen is backed by an external test that passed.**

**Verification gate: ✅ 15/15 claims verified · 13/13 must-pass green** (run `make verify`; see
[`verification/VERIFICATION.md`](verification/VERIFICATION.md)).

Collect pathology samples and deliver urgent meds across London **within clinical time windows**,
re-planning live when a road closes, a courier drops out, or a STAT request arrives. The agent
*reasons and communicates* (local Nemotron via NemoClaw + ElevenLabs voice); the GPU *computes the
routes* (custom GPU ACO + local search on the GB10).

## Why this wins

1. **Impact is quantified and test-backed.** 41/41 clinical windows met vs 39 for naive dispatch;
   STAT on-time 100%. Not assertions — bound to `tests/backtests/`.
2. **Genuinely local.** GPU solver + model on the GB10. Pull the network cable and it still routes.
   Patient data stays on the box (zero-egress NemoClaw policy).
3. **Looks like a product.** Dark ops command-center: 3D London, live traffic flow, glass KPIs,
   fleet roster — each KPI showing a ✅/❌ badge read live from the test results.
4. **You can't fake a number.** A capability is shown as *Verified* only because its external
   (non-LLM) test passed. The gate (`make verify`) blocks merges otherwise.

## Quickstart

```bash
make install          # python test + service deps
make data             # build + verify datasets -> data/manifest.json + map geojson
make verify           # the gate: 15 claims, 13 must-pass. exits non-zero unless GREEN

# run the stack (3 terminals)
cd routing && uvicorn app:app --port 8100                                  # GPU ACO (+LS) service
cd orchestrator && ROUTING_URL=http://localhost:8100 uvicorn app:app --port 8000
cd frontend && npm install && npm run dev                                  # http://localhost:5173
python scripts/demo_seed.py                                                # now-anchored scenario
```

Demo runbook: [`DEMO.md`](DEMO.md). Architecture + fallback ladder: [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Layout

| Dir | What |
|-----|------|
| [`contracts/`](contracts/) | shared data model + orchestrator/routing API (the integration contract) |
| [`orchestrator/`](orchestrator/) | hub: state, WebSocket, dispatch notifications, greedy safety net |
| [`routing/`](routing/) | **GPU ACO + insertion + local-search** portfolio solver; `/optimize` service |
| [`voice/`](voice/) | ElevenLabs intake (LLM NLU + keyword fallback) + WS outbound caller |
| [`frontend/`](frontend/) | deck.gl/MapLibre command-center; verified badges from `status.json` |
| [`data/`](data/) | facilities + now-anchored demand + road/building geojson; manifest gating |
| [`verification/`](verification/) | **claims ledger + gate** (`run.py` → `STATUS.json`/`VERIFICATION.md`) |
| [`tests/`](tests/) | external suites: data-quality, contracts, backtests, e2e |
| [`nemoclaw/`](nemoclaw/) | local-first sandbox policies (voice=ElevenLabs-only; routing=zero egress) |

## The verification gate (the differentiator)

No human or model marks work done — `verification/run.py` runs the external suites, maps each
result onto [`verification/claims.yaml`](verification/claims.yaml), and writes machine-readable
[`STATUS.json`](verification/STATUS.json) (which the UI reads for its badges) plus
[`VERIFICATION.md`](verification/VERIFICATION.md). A claim is **Verified** only if its bound test
passed in the latest run; `make verify` exits non-zero unless every must-pass claim is green, and
[CI](.github/workflows/verify.yml) enforces it on every push.

**18 external tests gate 15 claims** across impact, performance, contracts, data quality, and e2e.
Run `make verify` to reproduce.
