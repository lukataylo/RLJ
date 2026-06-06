# RLJ — Connect & Run (GB10 NemoClaw agent ↔ map)

How the pieces talk, and how to get connected if the box agent isn't reaching your map.

## Topology
```
  Scan-11 (GB10 box, 10.18.216.46)                 Operator machine (your laptop)
  ┌──────────────────────────────┐                 ┌─────────────────────────────┐
  │ Ollama + Nemotron-70B (GPU)   │   HTTP POST →   │ orchestrator :8000 (0.0.0.0) │→ map :5173
  │ systemd: rlj-signal-agent     │  recs / answers │ routing :8100                │
  │   ORCH=http://<operator-ip>:8000               └─────────────────────────────┘
  └──────────────────────────────┘
```
**Key point:** the box agent *pushes* to the orchestrator at the IP in its `ORCH` env. If the
orchestrator runs on a different laptop than before, you **must** update `ORCH` on the box
(Step 3) and run the orchestrator on `0.0.0.0` (Step 4). This is the #1 "can't connect" cause.

## 1. SSH to the box
```bash
ssh nvidia@Scan-11.local        # or: ssh nvidia@10.18.216.46
# password: ask the team (not stored in this repo)
# recommended — set up key auth so it's passwordless:
ssh-copy-id nvidia@Scan-11.local
```

## 2. Check the agent + model are up (on the box)
```bash
systemctl status rlj-signal-agent          # expect: active (running)
journalctl -u rlj-signal-agent -f          # live: "[ok] posted N signal rec(s)", "answered task-X"
ollama ps                                  # nemotron loaded, "100% GPU"
ollama list                                # nemotron:latest present (42 GB)
nvidia-smi                                 # GPU健康
```

## 3. Point the agent at YOUR orchestrator (the usual fix)
The service ships with `ORCH=http://10.18.216.110:8000` (the original operator). If your
laptop has a different IP, update it:
```bash
# find your laptop's LAN IP:  (macOS) ipconfig getifaddr en0   (linux) hostname -I
sudo sed -i 's#Environment=ORCH=.*#Environment=ORCH=http://<YOUR_LAN_IP>:8000#' \
    /etc/systemd/system/rlj-signal-agent.service
sudo systemctl daemon-reload && sudo systemctl restart rlj-signal-agent
# prove the box can reach you:
curl -m5 http://<YOUR_LAN_IP>:8000/healthz   # -> {"status":"ok","routing_service":...}
```

## 4. Run orchestrator + map (operator machine)
```bash
cd RLJ && make install                      # once
( cd routing && uvicorn app:app --port 8100 & )
( cd orchestrator && ROUTING_URL=http://localhost:8100 uvicorn app:app --host 0.0.0.0 --port 8000 & )
#                                                                        ^^^^^^^^^^^^ REQUIRED so the box can reach you
( cd frontend && npm install && npm run dev )   # http://localhost:5173
python scripts/demo_seed.py
```
`frontend/.env` needs `VITE_MAPBOX_TOKEN=<token>` (ask the team) and optionally
`VITE_ORCHESTRATOR_URL=http://localhost:8000`.

## 5. Verify the link works
- **Box:** `journalctl -u rlj-signal-agent -f` → posting recs / answering asks.
- **Map (`:5173`):** the NemoClaw feed shows `Nemotron@GB10` lines; the **Signals** layer shows markers; the **Ask NemoClaw** box returns answers; driver cards show assessment pills + a **Redirect** button; the **CCTV** layer (toggle on) shows live JamCams.
- **CLI:** `curl http://localhost:8000/signals/recommendations` → recs from `nemotron@scan-11`;
  `curl -X POST http://localhost:8000/agent/ask -H 'content-type: application/json' -d '{"question":"status?"}'` then watch the feed.

## Troubleshooting "can't connect to the agent"
| Symptom | Fix |
|---|---|
| No `Nemotron@GB10` lines on the map | Agent can't reach your orchestrator → Step 3 (set `ORCH` to YOUR IP), and Step 4 (`--host 0.0.0.0`). From the box: `curl http://<YOUR_IP>:8000/healthz`. |
| `curl healthz` from box fails | Different networks, or orchestrator bound to 127.0.0.1, or a firewall. Put both on the same Wi-Fi; rebind `0.0.0.0`; (macOS) System Settings → Network → Firewall off or allow port 8000. |
| `systemctl status` not active | `sudo systemctl restart rlj-signal-agent`; then `journalctl -u rlj-signal-agent -n 50`. |
| `ollama ps` empty / slow first answer | `ollama run nemotron` to warm it, or `sudo systemctl restart ollama`. First 70B answer takes ~30–90 s. |
| Want to call the box's Nemotron **directly** from another machine | Ollama binds localhost by default. Expose on LAN: `sudo systemctl edit ollama` → `[Service]\nEnvironment=OLLAMA_HOST=0.0.0.0:11434`, then `sudo systemctl daemon-reload && sudo systemctl restart ollama`. Then `curl http://10.18.216.46:11434/api/tags`. (Not needed for the normal setup — the agent runs on the box.) |

## Cadence
The agent ticks every ~12 s: it answers any queued operator questions immediately, posts
signal recommendations every ~6 ticks (~72 s), and refreshes per-driver assessments offset
from that. Give it a cycle after (re)starting.
