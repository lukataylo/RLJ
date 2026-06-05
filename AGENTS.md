# Working agreement — 3 parallel agents

This repo is built by three agents working **concurrently** on disjoint folders. The rule
that keeps you unblocked: **integrate through `contracts/`, never reach into another stream's
internals.**

## Ownership (do not edit outside your folder)

| Agent | Owns | May read | Never touches |
|-------|------|----------|---------------|
| **1 — Voice** | `voice/` | `contracts/`, `orchestrator/` | `routing/`, `frontend/` |
| **2 — Routing** | `routing/` | `contracts/`, `orchestrator/` | `voice/`, `frontend/` |
| **3 — Frontend** | `frontend/` | `contracts/`, `orchestrator/` | `voice/`, `routing/` |

The **orchestrator** + **contracts** are shared. If you need a contract change, edit
`contracts/` and announce it — do not fork the schema inside your stream.

## The contract is the API

- Data model: [`contracts/schemas.json`](contracts/schemas.json)
- Endpoints + WebSocket events: [`contracts/api.md`](contracts/api.md)
- Sample payloads to test against: [`contracts/samples/`](contracts/samples/)

Code against the **mock orchestrator** (`orchestrator/`, `uvicorn app:app --port 8000`)
from minute one. It works standalone via the built-in greedy router, so you never wait
for another stream to come online.

## Parallel git (recommended)

Use a worktree per stream so three agents commit without colliding:

```bash
git worktree add ../RLJ-voice    -b stream/voice
git worktree add ../RLJ-routing  -b stream/routing
git worktree add ../RLJ-frontend -b stream/frontend
```

Or just branch per stream and merge often. Folders are disjoint, so conflicts are limited
to `contracts/` — change it deliberately.

## Definition of done (per stream)

Each stream's `AGENT.md` has its own checklist, but all three must:
1. Run standalone against the mock orchestrator.
2. Survive its fallback (see `ARCHITECTURE.md` fallback ladder).
3. Have a 1-paragraph "what to show in the demo" note in its README.
