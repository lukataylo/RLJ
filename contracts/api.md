# API contract

Two surfaces: the **orchestrator** (the hub everyone talks to) and the **routing service**
(implemented by the routing stream, called by the orchestrator). All bodies use the entities
in [`schemas.json`](schemas.json).

---

## Orchestrator — `http://localhost:8000`

### REST

| Method | Path | Body | Returns | Used by |
|--------|------|------|---------|---------|
| GET  | `/healthz` | — | `{status, routing_service}` | all |
| GET  | `/state` | — | `{jobs[], couriers[], plan, disruptions[]}` snapshot | frontend (initial load) |
| POST | `/jobs` | `DeliveryJob` (id/status/created_at optional — server fills) | `DeliveryJob` | **voice** (inbound), frontend (manual) |
| GET  | `/jobs` | — | `DeliveryJob[]` | any |
| POST | `/couriers` | `Courier` | `Courier` | seed script, frontend |
| GET  | `/couriers` | — | `Courier[]` | any |
| POST | `/disruptions` | `DisruptionEvent` | `DisruptionEvent` (triggers re-optimize) | **frontend** ("close road"), TfL poller |
| POST | `/integrations/tfl/disruptions/sync?limit=25` | — | `{source, seen, ingested}` (fetches TfL road disruptions, ingests new ones, triggers one re-optimize) | demo operator / live-data poller |
| POST | `/optimize` | — | `Plan` | anyone forcing a re-plan |
| GET  | `/plan` | — | `Plan` | any |
| POST | `/notifications` | `Notification` | `Notification` (also broadcast on WS) | orchestrator/internal |

### WebSocket — `ws://localhost:8000/ws`

On connect the server sends one `{type:"state", payload:{...}}`. Thereafter, server→client
events (all shaped `{type, payload, ts}`):

| `type` | `payload` | Consumed by |
|--------|-----------|-------------|
| `state`        | full snapshot | frontend |
| `job_created`  | `DeliveryJob` | frontend |
| `plan_updated` | `Plan` | frontend |
| `courier_moved`| `{courier_id, location}` | frontend |
| `disruption`   | `DisruptionEvent` | frontend |
| `agent_log`    | `{level, message}` plain-English narration | frontend (side panel) |
| `notification` | `Notification` | **voice** (place outbound call), frontend |

> **Voice stream**: subscribe to `/ws`, act on `notification` events where `channel=="voice_call"`.
> Post inbound jobs to `POST /jobs`. You never call the routing service directly.

---

## Routing service — `http://localhost:8100` (implemented by `routing/`)

The orchestrator calls this when it is reachable; otherwise it uses its built-in greedy
router. Implement exactly:

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET  | `/healthz` | — | `{status, solver}` |
| POST | `/optimize` | `OptimizeRequest` | `OptimizeResponse` (`{plan: Plan}`) |

Point the orchestrator at it with `ROUTING_URL=http://localhost:8100` (see `orchestrator/README.md`).
Develop standalone using `contracts/samples/optimize_request.json`:

```bash
curl -s -X POST http://localhost:8100/optimize \
  -H 'content-type: application/json' \
  -d @../contracts/samples/optimize_request.json | jq .plan.objective
```

Your `Plan.objective.solver` string is what the UI shows ("gpu-aco", "cuopt", …) — set it.

---

## Conventions

- Times are ISO-8601 UTC strings. The planning clock is `now` in `OptimizeRequest`.
- IDs are strings; the orchestrator generates them when omitted (`job-<n>`, `crt-<n>`).
- Coordinates are WGS84 `lat`/`lng`. London bbox ≈ lat 51.28–51.69, lng -0.51–0.33.
- Be liberal in what you accept, strict in what you emit — always return the full entity.
