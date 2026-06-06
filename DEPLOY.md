# PulseGo — Railway deployment

Monorepo → **5 Railway services** from this one repo, each with its own *Root Directory*
and the Dockerfile already in that folder. Plus a Postgres plugin.

| Service | Root dir | Builds from | Public? | Domain |
|---|---|---|---|---|
| `api` (orchestrator) | `orchestrator/` | `orchestrator/Dockerfile` | yes | `api.pulsego.org` |
| `routing` | `routing/` | `routing/Dockerfile` | private | (internal only) |
| `web` (command-center) | `frontend/` | `frontend/Dockerfile` | yes | `app.pulsego.org` |
| `driver` (PWA) | `driver-app/` | `driver-app/Dockerfile` | yes | `drive.pulsego.org` |
| `Postgres` | — | Railway plugin | — | (internal) |

> Landing page (`pulsego.org`) is served by the `web` service's `/` route (or a small
> separate static service if you prefer to keep marketing separate).

## One-time setup
```bash
railway login                      # (done)
railway init                       # create the PulseGo project, or: railway link
railway add --plugin postgresql    # provisions DATABASE_URL
```
Create the four app services in the Railway dashboard (or `railway up` per service),
each with **Root Directory** set per the table. Railway auto-detects each Dockerfile.

## Env vars per service
**api (orchestrator)**
- `DATABASE_URL` → reference the Postgres plugin var.
- `JWT_SECRET` → a long random string.
- `AUTH_REQUIRED=true` → enforce login on writes (prod).
- `ADMIN_EMAIL`, `ADMIN_PASSWORD` → seeds the first dispatcher.
- `ROUTING_URL=http://routing.railway.internal:8100` → Railway private networking.
- `CORS_ORIGINS=https://app.pulsego.org,https://drive.pulsego.org,https://pulsego.org`
- `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_STYLE=openai` → **Nebius Nemotron** (drop-in for the agent/answers when ready).

**routing** — none required (CPU portfolio: OR-Tools + HGS/LS; `gpu-aco`→numpy fallback).

**web** and **driver** (build-time args)
- `VITE_ORCHESTRATOR_URL=https://api.pulsego.org`
- `VITE_MAPBOX_TOKEN=<public mapbox token>` (restrict it to the pulsego.org referrer in the Mapbox dashboard).

## Domains / DNS
1. In Railway, add custom domains to `api`, `web`, `driver` (it issues TLS automatically).
2. At your DNS registrar for `pulsego.org`, add the CNAME records Railway shows
   (`api`, `app`, `drive`, and apex `@`/`www` → `web`).
3. Force HTTPS (Caddy + Railway already serve TLS; WebSocket uses `wss://api…`).

## On-prem GB10 agent (optional, hybrid)
The Scan-11 box agent can point at the cloud API instead of a laptop:
```bash
# on the box: /etc/systemd/system/rlj-signal-agent.service
Environment=ORCH=https://api.pulsego.org
# and, to use the box's local Nemotron, leave LLM_* unset (defaults to local Ollama);
# to use Nebius from the box too, set the same LLM_* as the api service.
```
With Nebius set on `api`, the agent loop can also run **in the cloud** (no box needed) —
it's the same `signal_agent.py` with `LLM_*` pointed at Nebius.

## CI → deploy
CI runs `make verify` on every push (the gate). Wire Railway to **auto-deploy `main`**
only after the gate is green (Railway: "Wait for CI" / deploy on check success), or
deploy on tags. Never deploy a red `main`.

## Smoke test after deploy
```bash
curl https://api.pulsego.org/healthz                 # {"status":"ok",...}
curl https://api.pulsego.org/cctv/cameras | head     # live JamCams
open https://app.pulsego.org                          # command-center loads, logs in
```
