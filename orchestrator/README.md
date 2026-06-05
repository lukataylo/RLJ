# Orchestrator (shared hub)

The integration point for all three streams. Holds state, broadcasts live events on a
WebSocket, and routes optimisation requests to the real routing service — or a built-in
greedy fallback so the system is **always** demoable.

## Run

```bash
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
# optional: point at the real GPU router once routing/ is up
ROUTING_URL=http://localhost:8100 uvicorn app:app --port 8000
```

Seed demo data (in another terminal, orchestrator running):

```bash
python seed.py
```

## Smoke test

```bash
curl -s localhost:8000/healthz | jq        # {status, routing_service}
curl -s localhost:8000/plan | jq .objective
# watch live events:
websocat ws://localhost:8000/ws            # or use the frontend
```

## Notes

- `models.py` mirrors `contracts/schemas.json` — keep them in sync.
- `greedy.py` is the fallback router (nearest-courier + priority order + straight-line ETAs).
  It is intentionally dumb; the routing stream beats it. The orchestrator switches to the
  real service automatically when `ROUTING_URL/healthz` responds.
- Every state change (`/jobs`, `/disruptions`, `/optimize`) triggers a re-plan and emits
  `plan_updated` + `agent_log` on the WS.
