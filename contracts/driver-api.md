# Driver / flywheel API contract

Extends the orchestrator (`http://localhost:8000`) with the crowdsourced-driver data
flywheel and green-wave guidance. Entities are in [`schemas.json`](schemas.json).

## REST

| Method | Path | Body | Returns | Used by |
|--------|------|------|---------|---------|
| POST | `/drivers` | `Driver` (id/joined_at optional) | `Driver` | driver-app signup |
| GET  | `/drivers` | — | `Driver[]` | dashboard |
| POST | `/telemetry` | `TelemetryBatch` `{pings:[DriverPing]}` | `{accepted, rejected, cells_updated}` | driver-app, probe simulator |
| GET  | `/congestion` | — | `CongestionField` | frontend heat layer, routing |
| GET  | `/driver/{id}/guidance` | — | `DriverGuidance` (route + green-wave + contribution) | driver-app, voice agent |
| GET  | `/signals/advice` | query `driver_id,lat,lng,heading` | `SignalAdvice` | driver-app, voice agent |

## The flywheel

`POST /telemetry` → **Data-Curator** validates pings (London bbox, speed sanity, dedupe;
only `consent:true` drivers) → updates the **congestion field** (grid aggregation of probe
speeds) → high-congestion cells are projected to `traffic` `DisruptionEvent`s → the
**Dispatcher** re-optimises medical-courier routes around them and broadcasts `plan_updated`.
More drivers ⇒ denser field ⇒ better routing for everyone. Drivers receive green-wave
guidance in return (`/driver/{id}/guidance`, `/signals/advice`).

## WebSocket additions (`/ws`)

| `type` | `payload` |
|--------|-----------|
| `congestion_updated` | `CongestionField` |
| `driver_joined` | `Driver` |

## Conventions

Only validated telemetry from consenting drivers updates the model (DQ-gated, same manifest
philosophy as the other datasets). Congestion ∈ [0,1]; speed in m/s; coords WGS84 in the
London bbox (lat 51.28–51.69, lng −0.51–0.33).
