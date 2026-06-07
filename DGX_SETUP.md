# Reproducing the full PulseGo stack on a DGX Spark (GB10)

How to stand up **everything that currently runs on `scan-11`** on a fresh DGX Spark, so you can
move the whole on-box PulseGo backend to another box. This is the box-side companion to
`CONNECT.md` (how the box talks to the operator map), `DEPLOY.md` (the Railway/cloud side),
`valhalla/README.md` (routing engine), and `scan11/` (the signal agent).

> **Two modes exist.** `LOCAL=true` = DGX mode: route over the on-box **Valhalla** road graph and
> run the LLM on the box's **Ollama/Nemotron** (zero egress — the local-first story). `LOCAL=false`
> = cloud mode: haversine travel times + Mapbox route drawing + OpenAI LLM, no DGX needed. This
> doc reproduces **DGX mode**.

> **Where things run.** In this canonical setup **the orchestrator runs ON the DGX** (alongside
> routing, Valhalla, Ollama and the signal agent) — `start-dgx.sh` brings it up on the box, and the
> live box has it running there. Consequences:
> - The signal agent talks to the orchestrator over **`localhost`** → `ORCH=http://localhost:8000`.
> - The orchestrator binds **`0.0.0.0`** so the **operator laptop's frontend/map** can reach the box
>   over the LAN — *not* for the agent (the agent is local).
> - **#1 break-on-move:** the orchestrator must bind `0.0.0.0`, **and** the frontend's
>   `VITE_ORCHESTRATOR_URL` must point at the new box's host/IP. (`CONNECT.md` documents the
>   alternate layout where the orchestrator runs on a laptop instead — there, you'd set the agent's
>   `ORCH` to the laptop IP. This doc assumes the all-on-DGX layout.)

---

## 1. What's actually on the box (verified snapshot of `scan-11`)

The running backend is **five processes**. Only Ollama and the signal agent are systemd units; the
rest are launched by hand (see `start-dgx.sh` / `valhalla/serve.sh`), typically inside `tmux`.

| Process | Port | How it runs today | Provided by |
|---|---|---|---|
| **Ollama** (serves `nemotron:latest`, 42 GB) | `11434` | systemd `ollama.service` | Ollama installer |
| **Valhalla** routing engine (London tiles) | `8002` | bare process via `valhalla/serve.sh` (pyvalhalla) | `pyvalhalla==3.7.0` in `.venv` |
| **Routing** service (`/optimize`) | `8100` | `uvicorn` from repo `.venv` | `routing/` |
| **Orchestrator** hub (`/state`, `/ws`, …) | `8000` | `uvicorn` from repo `.venv` | `orchestrator/` |
| **rlj-signal-agent** (Nemotron signal agent) | — | systemd `rlj-signal-agent.service` | `scan11/signal_agent.py` |

Platform / toolchain captured from the live box:

| Thing | Value |
|---|---|
| Hardware / arch | NVIDIA **GB10** (DGX Spark), `aarch64` |
| OS | **Ubuntu 24.04.4 LTS** (Noble), kernel `6.17.0-nvidia` |
| User / home | `nvidia` / `/home/nvidia` |
| LAN IP (DHCP, yours differs) | `10.18.216.46/21`, hostname `scan-11` (mDNS `scan-11.local`) |
| System Python | `/usr/bin/python3` = **3.12.3** |
| Env manager | **`uv`** (Makefile creates `.venv` with `uv venv --python 3.12`) |
| Ollama | **v0.30.6**, `/usr/local/bin/ollama`, runs as user `ollama` |
| Model | `nemotron:latest` (~42 GB) in `~/.ollama/models` |
| Valhalla | `pyvalhalla==3.7.0`; tiles in `valhalla/tiles/` (+ `tiles.tar`) from the Greater-London OSM PBF (~120 MB) |
| Docker | installed (v29.2.1) but **no containers/images** — Valhalla runs via pyvalhalla, not Docker |
| Optional solver deps in `.venv` | `ortools` ✅ present · `torch` ❌ · `cupy` ❌ · `osmnx` ❌ |

**What the missing deps mean** (all import-guarded — the stack runs fine without them):
- no `cupy` → the GPU ACO solver falls back to numpy (`gpu-aco` → `aco-numpy`);
- no `torch` → the GARNET neural optimiser stays off (it's off by default anyway, `$GARNET_ENABLED` unset);
- no `osmnx` → the OSMnx travel-time tier is unavailable, but **Valhalla covers road-graph times**, so this doesn't matter in DGX mode.

---

## 2. Prereqs on the new box

```bash
# operator machine: add an SSH alias so all the repo tooling + this doc's commands work unchanged
cat >> ~/.ssh/config <<'EOF'
Host dgxspark
    HostName scan-11.local        # or the new box's LAN IP
    User nvidia
    IdentityFile ~/.ssh/id_ed25519
EOF
ssh-copy-id nvidia@scan-11.local  # passwordless, key-only
ssh dgxspark 'nvidia-smi -L'      # expect "GPU 0: NVIDIA GB10 ..."
```

The box must be **on the same LAN as the operator laptop** if the laptop runs the map (the box
pushes HTTP to it). If you run the whole demo *on the box*, that's not required.

Install the base toolchain on the box:

```bash
ssh dgxspark
sudo apt-get update && sudo apt-get install -y git curl build-essential tmux jq
# uv (creates/manages the repo .venv):
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.bashrc
```

---

## 3. Get the repo + Python env

```bash
ssh dgxspark
cd ~ && git clone https://github.com/lukataylo/RLJ.git
cd RLJ
git checkout main          # or the branch you're deploying (the live box was on `multihop`)

make install               # uv venv .venv --python 3.12 + installs orchestrator/routing/test deps
.venv/bin/pip install "ortools>=9.8"   # CPU PDPTW solver (present on the live box; not in base reqs)
```

`make install` is defined in the `Makefile` as:
```
uv venv .venv --python 3.12
uv pip install --python ./.venv/bin/python -r requirements-test.txt \
    -r orchestrator/requirements.txt -r routing/requirements.txt
```

> Optional GPU/accelerator tiers (NOT on the live box — install only if you want them, picking
> wheels that match the GB10's CUDA): `cupy-cuda12x` (→ `gpu-aco`), `torch` (→ GARNET),
> `osmnx`+`networkx` (extra travel-time tier), `cuopt` (NGC/conda). All are import-guarded.

---

## 4. Build the datasets

```bash
ssh dgxspark
cd RLJ
make data        # .venv/bin/python data/build.py → data/manifest.json (+ dq_passed flags, map geojson)
```

---

## 5. Stand up Valhalla (offline London routing) — the pyvalhalla path

This is **how the live box does it** (no Docker, no sudo). Valhalla is served in-process by
`pyvalhalla`'s bundled `valhalla_service`.

```bash
ssh dgxspark
cd RLJ
.venv/bin/pip install pyvalhalla        # the live box has pyvalhalla==3.7.0

# 1. Fetch the Greater-London OSM extract (~120 MB, idempotent, Geofabrik; the only network step)
.venv/bin/python data/osm_fetch.py      # → data/cache/osm/greater-london-latest.osm.pbf

# 2. Build the routing tiles (minutes). Writes valhalla/valhalla.json + valhalla/tiles/ + tiles.tar
valhalla/build_tiles.sh

# 3. Serve on :8002 (foreground; run under tmux/systemd to keep it up)
valhalla/serve.sh 2                     # 2 = worker threads

# 4. Confirm it's serving
curl -s http://localhost:8002/status | jq .   # → {"version":"3.7.0", "available_actions":[...]}
```

The tiles (`valhalla/tiles/`, `tiles.tar`, the `.osm.pbf`) are git-ignored, Spark-resident
artifacts. To **migrate without re-downloading/rebuilding**, copy them straight across:
```bash
# from the OLD box (or wherever you have them) to the new box:
rsync -avz oldbox:/home/nvidia/RLJ/valhalla/{valhalla.json,tiles,tiles.tar} dgxspark:/home/nvidia/RLJ/valhalla/
rsync -avz oldbox:/home/nvidia/RLJ/data/cache/osm/ dgxspark:/home/nvidia/RLJ/data/cache/osm/
```
> `valhalla.json` has absolute paths (`/home/nvidia/RLJ/valhalla/tiles`) — keep the same checkout
> path, or re-run `valhalla/build_tiles.sh` to regenerate it.

> **Alternative (documented in `valhalla/README.md`): Docker.** `cd valhalla && docker compose up -d`
> uses `ghcr.io/nilsnolde/docker-valhalla` (multi-arch/ARM64), auto-downloads the extract, builds
> tiles, serves `:8002`. The live box uses pyvalhalla instead, but Docker is a valid equivalent.

---

## 6. Install Ollama + pull Nemotron

```bash
ssh dgxspark
curl -fsSL https://ollama.com/install.sh | sh    # installs /usr/local/bin/ollama + ollama.service
ollama pull nemotron                              # ~42 GB — the long pole; do this early
ollama run nemotron "ok"                          # warm it once (first 70B load ~30–90 s)
ollama list                                       # expect: nemotron:latest ... 42 GB
```

The installer's stock `ollama.service` binds `127.0.0.1:11434` (fine — the signal agent runs on
the box). If a laptop must call Nemotron directly, expose it on the LAN:
```bash
sudo systemctl edit ollama   # add: [Service]\nEnvironment=OLLAMA_HOST=0.0.0.0:11434
sudo systemctl daemon-reload && sudo systemctl restart ollama
```
(`start-dgx.sh` also launches `OLLAMA_HOST=0.0.0.0 ollama serve` for the same reason.)

To copy the model instead of re-pulling: `rsync -avz oldbox:~/.ollama/models dgxspark:~/.ollama/`.

---

## 7. Configure environment

```bash
ssh dgxspark
cd RLJ
cp .env.example .env       # then edit; the DGX-mode values:
```
Key `.env` settings for DGX mode (full template in `.env.example`):
```
LOCAL=true
DGX_HOST=scan-11.local                       # this box's mDNS host or LAN IP
VALHALLA_URL=http://scan-11.local:8002       # routing service reads this (defaults to :8002)
OLLAMA=http://scan-11.local:11434
MODEL=nemotron
ROUTING_URL=http://localhost:8100            # orchestrator → routing service
CORS_ORIGINS=http://localhost:5173,http://localhost:5174,https://pulsego.org,https://app.pulsego.org
AUTH_REQUIRED=false                          # keep false unless seeding admin/JWT in prod
```
Frontend (`frontend/.env.local`, see `frontend/.env.example`) for local mode:
```
VITE_ORCHESTRATOR_URL=http://scan-11.local:8000
VITE_LOCAL=true            # default route source = valhalla; Mapbox token optional locally
```

---

## 8. Start the backend services

The repo's `start-dgx.sh` brings up Ollama (0.0.0.0) + the orchestrator, but **not** routing or
Valhalla — start those too or the orchestrator falls back to the greedy router (0 real routes).
Run everything under `tmux` so it survives SSH drops:

```bash
ssh dgxspark
tmux new -s rlj
cd RLJ

# (Valhalla should already be running from step 5; if not: valhalla/serve.sh 2 & )

# routing service :8100
( cd routing && VALHALLA_URL=http://localhost:8002 ../.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8100 & )

# orchestrator :8000 — bind 0.0.0.0 so the operator laptop's frontend/map can reach the box
( cd orchestrator && ROUTING_URL=http://localhost:8100 ../.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 & )

# seed a now-anchored demo scenario
.venv/bin/python scripts/demo_seed.py
# detach: Ctrl-b d
```

Full `start-dgx.sh` content is in **Appendix A**. Note: the committed `start-dgx.sh` invokes
`${HOME}/.local/bin/uvicorn` (an old pip `--user` install path); the live box actually runs
`uvicorn` from the repo `.venv` (as in the commands above). If you use `start-dgx.sh` verbatim,
either install uvicorn with `pip install --user uvicorn` or edit its `UVICORN=` line to
`${REPO_ROOT}/.venv/bin/uvicorn`. It also doesn't start routing or Valhalla — start those first.

---

## 9. Deploy the on-box Nemotron signal agent (systemd)

Deploy **the repo copy** of `scan11/signal_agent.py` — it's the env-flexible version (supports both
local Ollama and a hosted OpenAI-style endpoint via `LLM_*`), unlike the slightly older file
currently sitting at `/home/nvidia/signal_agent.py` on the live box. It is **pure Python stdlib**
(no pip deps). Full content in **Appendix B**. Install it + its unit:

```bash
# from the repo root on the box (or scp scan11/signal_agent.py from the operator):
cp scan11/signal_agent.py /home/nvidia/signal_agent.py
sudo cp scan11/rlj-signal-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rlj-signal-agent
```

Because the orchestrator runs **on this same box** (see "Where things run" above), the agent's
`ORCH` is **`localhost`**. Set it in `scan11/rlj-signal-agent.service` before installing (the file
committed in the repo still carries a legacy laptop IP, `http://10.18.216.110:8000`, from the
alternate layout):
```ini
ExecStart=/usr/bin/python3 /home/nvidia/signal_agent.py
Environment=ORCH=http://localhost:8000        # orchestrator runs ON this box → localhost
Environment=OLLAMA=http://localhost:11434
Environment=MODEL=nemotron
Environment=INTERVAL_S=90
Environment=TICK_S=12
```
Agent env vars: `ORCH`, `OLLAMA`/`LLM_BASE_URL`, `MODEL`/`LLM_MODEL`, `TICK_S` (loop tick; recs
every ~6 ticks), and `LLM_API_KEY`+`LLM_STYLE=openai` to point at a hosted Nemotron (e.g. Nebius)
instead of local Ollama — see Appendix B and `DEPLOY.md`.

```bash
# set ORCH to localhost (all-on-DGX layout); use the laptop's LAN IP only if the
# orchestrator runs off-box (the CONNECT.md layout):
sudo sed -i 's#Environment=ORCH=.*#Environment=ORCH=http://localhost:8000#' \
    /etc/systemd/system/rlj-signal-agent.service
sudo systemctl daemon-reload && sudo systemctl restart rlj-signal-agent
```

---

## 10. (Optional) NemoClaw sandbox egress policies

If you run the voice/routing agents under NemoClaw on the box, apply the allowlists in `nemoclaw/`:
```bash
nemoclaw rlj-voice   policy-add --from-file nemoclaw/policy-voice.yaml --yes   # ElevenLabs + orchestrator only
nemoclaw rlj-routing policy-add --from-file nemoclaw/policy-routing.yaml --yes # zero egress
nemoclaw rlj-routing exec -- bash -c 'curl -sS --max-time 5 https://example.com'  # expect 403
```
The signal agent itself runs as a plain systemd service (not sandboxed); skip this unless you also
run the NemoClaw-wrapped voice/routing agents.

---

## 11. Verify the whole stack

```bash
ssh dgxspark
cd RLJ
make verify-core      # the gate (skips browser e2e). Should end GREEN. `make verify` adds e2e.

# health checks
curl -s http://localhost:8002/status | jq .available_actions     # Valhalla up
curl -s http://localhost:8100/healthz                            # routing up
curl -s http://localhost:8000/healthz                            # orchestrator → {"status":"ok","routing_service":...}
systemctl status rlj-signal-agent --no-pager                     # active (running)
journalctl -u rlj-signal-agent -f                                # "[ok] Nemotron produced N recommendation(s)" / "posted N signal rec(s)"
ollama ps                                                        # nemotron loaded, 100% GPU
```
Then point the frontend/map at this box (`VITE_ORCHESTRATOR_URL=http://<box>:8000`) per
`CONNECT.md` step 5, and confirm `Nemotron@GB10` lines + Signals layer appear.

---

## 12. Reboot persistence & migration shortcuts

- **Survives reboot:** `ollama.service` + `rlj-signal-agent.service` (both `enabled`). Valhalla,
  routing, and the orchestrator are launched by hand today — to make them reboot-safe, write
  systemd units modeled on `rlj-signal-agent.service` (`ExecStart` = `valhalla/serve.sh` /
  `.venv/bin/uvicorn …`), or run `start-dgx.sh` from a `@reboot` cron / tmux on login.
- **Fastest migration** (skip the long downloads/builds): `rsync` these from the old box —
  `~/.ollama/models` (42 GB model), `RLJ/valhalla/{valhalla.json,tiles,tiles.tar}` (built tiles),
  `RLJ/data/cache/osm/` (OSM extract). Then steps 3, 7, 8, 9 are all you need.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Orchestrator returns 0 real routes / greedy fallback | Routing service or Valhalla down. Check `:8100/healthz` and `:8002/status`; confirm `VALHALLA_URL`. |
| `[warn] congestion fetch failed: No route to host` / `Connection refused` (agent log, repeating) | Agent can't reach the orchestrator. In the all-on-DGX layout `ORCH` should be `http://localhost:8000` and the orchestrator must be running (step 8). The live box's "No route to host" was a stale laptop IP in `ORCH` — Step 9 fixes it. |
| Frontend/map can't reach the box | Orchestrator not bound `0.0.0.0`, or `VITE_ORCHESTRATOR_URL` points at the wrong host. See "#1 break-on-move" at the top + `CONNECT.md`. |
| `valhalla/serve.sh` errors "valhalla.json missing" | Run `valhalla/build_tiles.sh` first (after `data/osm_fetch.py`). |
| First Nemotron answer hangs ~30–90 s | Normal cold 70B load. `ollama run nemotron "ok"` to pre-warm. |
| `make verify` red | Read `verification/VERIFICATION.md` / `STATUS.json` for the failing claim → its bound test. |

---

## Appendix A — full script contents

These are the repo copies (verbatim), embedded so the box can be reproduced without the checkout
in front of you. Paths are relative to the repo root.

### `start-dgx.sh`
```bash
#!/bin/bash
# start-dgx.sh — bring up the RLJ backend services on the DGX Spark.
#
# Run this ON the DGX (over SSH). It starts the two services that have to be
# running for the full (non-fallback) demo:
#   1. Ollama serving the local model, reachable from other machines
#   2. The FastAPI orchestrator (the hub every stream integrates through)
#
# Both bind to 0.0.0.0 so laptops on the same network can connect. If you only
# ever run the demo ON the DGX itself, localhost would also work — but 0.0.0.0
# is harmless and saves re-debugging "connection refused" if the demo machine
# changes at the last minute.
#
# Tip: run this inside tmux or screen so the services survive if your SSH
# session drops:  tmux new -s rlj  ->  ./start-dgx.sh  ->  detach with Ctrl-b d

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UVICORN="${HOME}/.local/bin/uvicorn"   # pip --user installs land here, not on PATH

echo "[start-dgx] Starting Ollama on all interfaces (0.0.0.0:11434)..."
OLLAMA_HOST=0.0.0.0 ollama serve &
sleep 2

# Warm the model so the first real request doesn't time out on a cold load.
# The 42GB model can take a while to load into memory the first time.
echo "[start-dgx] Warming the model (this can take a minute on first load)..."
curl -s http://localhost:11434/api/generate \
  -d '{"model": "nemotron", "prompt": "ok", "stream": false}' > /dev/null || \
  echo "[start-dgx] (warm-up call failed — check 'ollama list' has the model)"

echo "[start-dgx] Starting orchestrator on 0.0.0.0:8000..."
cd "${REPO_ROOT}/orchestrator"
"${UVICORN}" app:app --host 0.0.0.0 --port 8000 &

echo "[start-dgx] Services starting:"
echo "            orchestrator -> http://0.0.0.0:8000"
echo "            ollama       -> http://0.0.0.0:11434"
echo "[start-dgx] Note: the routing service (routing/app.py) is separate — start it"
echo "            too, or the orchestrator falls back to the greedy router (0 routes)."

wait
```
> ⚠️ See §8: this file's `UVICORN=${HOME}/.local/bin/uvicorn` is stale — the live box runs uvicorn
> from the repo `.venv`. Edit that line to `${REPO_ROOT}/.venv/bin/uvicorn`, or `pip install --user
> uvicorn`. It also starts neither routing nor Valhalla.

### `valhalla/build_tiles.sh`
```bash
#!/usr/bin/env bash
# Build Greater-London Valhalla tiles in-process via pyvalhalla (no Docker/sudo).
# Idempotent-ish: regenerates config + tiles from the local OSM extract.
#
# Usage:  valhalla/build_tiles.sh [path/to/greater-london-latest.osm.pbf]
# Tiles land in valhalla/tiles/ (+ valhalla/tiles.tar for mmap serving). Both are
# git-ignored Spark-resident artifacts. Run on the GB10 box inside the uv venv.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/../.venv/bin"
PBF="${1:-$HERE/../data/cache/osm/greater-london-latest.osm.pbf}"
# pyvalhalla's CLI wrappers resolve their bundled binary via `which <name>`, so the
# venv bin dir must be on PATH and we must invoke by bare name (not absolute path).
export PATH="$VENV:$PATH"

if [[ ! -f "$PBF" ]]; then
  echo "OSM extract not found: $PBF — run: .venv/bin/python data/osm_fetch.py" >&2
  exit 1
fi

echo "[valhalla] generating config -> $HERE/valhalla.json"
valhalla_build_config \
  --mjolnir-tile-dir "$HERE/tiles" \
  --mjolnir-tile-extract "$HERE/tiles.tar" \
  > "$HERE/valhalla.json"

mkdir -p "$HERE/tiles"
echo "[valhalla] building tiles from $PBF (minutes)…"
valhalla_build_tiles -c "$HERE/valhalla.json" "$PBF"

echo "[valhalla] packing mmap extract (tiles.tar)…"
valhalla_build_extract -c "$HERE/valhalla.json" -v || true

echo "[valhalla] done. tiles at $HERE/tiles"
```

### `valhalla/serve.sh`
```bash
#!/usr/bin/env bash
# Serve the built Greater-London tiles over HTTP via pyvalhalla's valhalla_service
# (no Docker/sudo). Listens on the httpd.service.listen address in valhalla.json
# (default tcp://*:8002). Point the router at it with VALHALLA_URL=http://localhost:8002.
#
# Usage:  valhalla/serve.sh [num_threads]   (foreground; use nohup/systemd to daemonize)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/../.venv/bin"
THREADS="${1:-2}"
# pyvalhalla CLI wrappers need the venv bin on PATH and invocation by bare name.
export PATH="$VENV:$PATH"

if [[ ! -f "$HERE/valhalla.json" ]]; then
  echo "valhalla.json missing — run valhalla/build_tiles.sh first" >&2
  exit 1
fi

echo "[valhalla] serving on :8002 (threads=$THREADS) — Ctrl-C to stop"
exec valhalla_service "$HERE/valhalla.json" "$THREADS"
```

### `scan11/rlj-signal-agent.service` (the systemd unit — set `ORCH=http://localhost:8000`, see §9)
```ini
[Unit]
Description=RLJ traffic-signal Nemotron agent (GB10)
After=network-online.target ollama.service
Wants=ollama.service

[Service]
Type=simple
User=nvidia
WorkingDirectory=/home/nvidia
ExecStart=/usr/bin/python3 /home/nvidia/signal_agent.py
Environment=ORCH=http://10.18.216.110:8000
Environment=OLLAMA=http://localhost:11434
Environment=MODEL=nemotron
Environment=INTERVAL_S=90
Environment=TICK_S=12
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### `ollama.service` (stock, written by the Ollama installer — for reference)
```ini
[Unit]
Description=Ollama Service
After=network-online.target

[Service]
ExecStart=/usr/local/bin/ollama serve
User=ollama
Group=ollama
Restart=always
RestartSec=3
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin"

[Install]
WantedBy=default.target
```

---

## Appendix B — `scan11/signal_agent.py` (the env-flexible repo copy, verbatim)

This is what to deploy to `/home/nvidia/signal_agent.py` (§9). Pure stdlib; `LLM_*` lets the same
file drive local Ollama **or** a hosted OpenAI-style endpoint (Nebius) with no code change.

```python
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
```

---

## Appendix C — make routing, Valhalla & the orchestrator reboot-safe (the fix for §12)

Today only Ollama and the signal agent are systemd units; the other three are hand-started and die
on reboot. To make the whole stack come up automatically, install these three units (adjust
`User`/paths if your checkout isn't `/home/nvidia/RLJ`). After writing them:
`sudo systemctl daemon-reload && sudo systemctl enable --now pulsego-valhalla pulsego-routing pulsego-orchestrator`.

### `/etc/systemd/system/pulsego-valhalla.service`
```ini
[Unit]
Description=PulseGo Valhalla routing engine (:8002)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nvidia
WorkingDirectory=/home/nvidia/RLJ
ExecStart=/home/nvidia/RLJ/valhalla/serve.sh 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### `/etc/systemd/system/pulsego-routing.service`
```ini
[Unit]
Description=PulseGo routing service (:8100)
After=network-online.target pulsego-valhalla.service
Wants=pulsego-valhalla.service

[Service]
Type=simple
User=nvidia
WorkingDirectory=/home/nvidia/RLJ/routing
Environment=VALHALLA_URL=http://localhost:8002
ExecStart=/home/nvidia/RLJ/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8100
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### `/etc/systemd/system/pulsego-orchestrator.service`
```ini
[Unit]
Description=PulseGo orchestrator hub (:8000)
After=network-online.target pulsego-routing.service ollama.service
Wants=pulsego-routing.service

[Service]
Type=simple
User=nvidia
WorkingDirectory=/home/nvidia/RLJ/orchestrator
EnvironmentFile=/home/nvidia/RLJ/.env
Environment=ROUTING_URL=http://localhost:8100
ExecStart=/home/nvidia/RLJ/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
> With these enabled you no longer need `start-dgx.sh` — the box self-heals on reboot, and the
> signal agent (which `Wants=ollama.service`) reconnects to the orchestrator on `localhost:8000`.
