# 🎙️ Voice — ElevenLabs intake + outbound ETA agent

The voice/dispatch stream for RLJ. It is the **conversational front door** to the
medical-courier optimiser and runs as a NemoClaw sandboxed agent on local Nemotron.

- **Inbound** — a clinic "calls in" a delivery request in natural language. We transcribe
  (telephony) → run a local Nemotron model to extract a structured `DeliveryJob`
  (`nlu.py`) → `POST /jobs` to the orchestrator (`intake.py`).
- **Outbound** — we subscribe to the orchestrator WebSocket and act on `notification`
  events where `channel == "voice_call"`, placing an outbound ElevenLabs call / TTS to
  the courier or clinic with the new ETA, and mirroring plain-English status to console
  (`outbound.py`).

- **Driver-assistant** — a hands-free conversational copilot for delivery drivers. A
  driver asks a free-text question; the agent **tool-calls** the orchestrator
  (`../contracts/driver-api.md`) to answer it and speaks a short reply
  (`driver_assistant.py` + `driver_tools.py`).

We integrate **only** through the orchestrator contracts (`../contracts/api.md`,
`../contracts/driver-api.md`). We never call the routing service.

## Files

| File | What it does |
|------|--------------|
| `nlu.py` | raw intake text → `DeliveryJob` dict. Local-LLM path (OpenAI-compatible) with a strict JSON system prompt + few-shots, and a regex/keyword **fallback** so it works with no model. |
| `intake.py` | CLI/stdin entry: parse text, `POST /jobs`. Ships 3 canned demo requests. |
| `outbound.py` | WS listener; on `voice_call` notifications calls `place_call(to, message)`. |
| `driver_tools.py` | Typed tool functions the driver-assistant calls on the orchestrator (`get_guidance`, `get_signal_advice`, `get_congestion`, `bridge_status`, `next_pickup`, `reroute_reason`). Orchestrator down ⇒ each returns `{"error": ...}`. |
| `driver_assistant.py` | The driver-copilot agent loop: route a question → call tool(s) → short spoken answer (ElevenLabs guarded → console). LLM tool-router if `LLM_BASE_URL` set, else keyword router. `--demo` runs 6 canned questions. |
| `elevenlabs_client.py` | Guarded ElevenLabs wrapper (TTS + outbound agent call); no key ⇒ no-op + log. |
| `.env.example` | All config (everything optional). |

## Run

```bash
pip install -r requirements.txt
cp .env.example .env          # optional — edit if you have keys

# Terminal A — orchestrator (the hub), from repo root:
cd ../orchestrator && uvicorn app:app --reload --port 8000

# Terminal B — outbound dispatch listener:
python outbound.py

# Terminal C — fire inbound requests:
python intake.py --demo                       # all 3 canned clinic calls
python intake.py "STAT bloods from Somers Town to St Thomas by half ten, cold chain"
echo "Insulin to a patient in Bow before midday" | python intake.py
```

Quick NLU smoke test (no orchestrator needed): `python nlu.py "STAT bloods ..."`.

### Driver-assistant (hands-free copilot)

```bash
# 6 canned driver questions, end to end (live tools if the orchestrator is up,
# mocked tool results if it's down — either way the loop completes):
python driver_assistant.py --demo

# one-off question:
python driver_assistant.py "is tower bridge open?"
python driver_assistant.py "what speed should I do to catch the next green?"
```

The agent routes each question to orchestrator tools (`driver_tools.py`) and speaks a
short reply. With **no ElevenLabs key** it prints the reply (`🔊 ...`); with **no local
model** it uses a deterministic keyword router; with the **orchestrator down** the tools
return `{"error": ...}` and the agent says "I can't reach dispatch right now."

FAQ → tool routing (the zero-credential keyword router, pinned by
`tests/voice/test_driver_assistant.py`):

| Driver asks | Tool called | Endpoint |
|-------------|-------------|----------|
| "where's my next pickup" | `next_pickup` | `GET /driver/{id}/guidance` |
| "why am I rerouted" | `reroute_reason` | guidance + `GET /state` disruptions |
| "is tower bridge open" | `bridge_status` | `GET /state` disruptions |
| "where can I park" | `get_guidance` | `GET /driver/{id}/guidance` |
| "should I catch the next green / what speed" | `get_signal_advice` | `GET /signals/advice` |
| "how's traffic" | `get_congestion` | `GET /congestion` |

## Environment variables

All optional — see `.env.example`. The important ones:

| Var | Default | Purpose |
|-----|---------|---------|
| `ORCHESTRATOR_URL` | `http://localhost:8000` | hub REST + (derived) WS base |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible endpoint (Ollama / NemoClaw / `inference.local`). **Unset ⇒ keyword NLU.** |
| `LLM_MODEL` | `nemotron` | model name |
| `ELEVENLABS_API_KEY` | — | unset ⇒ console/TTS fallback (no calls placed) |
| `ELEVENLABS_VOICE_ID` | Rachel | TTS voice |
| `ELEVENLABS_AGENT_ID` | — | required for outbound conversational calls |

## Zero-credential mode (works out of the box)

This stream is built to run **standalone against the mock orchestrator with NO ElevenLabs
key and NO local model**. In that mode it falls back to the keyword NLU parser and
console output, and still completes the whole demo loop:

1. `intake.py` keyword-parses the request and posts a real job.
2. The orchestrator plans (greedy fallback) and broadcasts.
3. `outbound.py` receives any `voice_call` notification and prints the ETA "call".
4. `driver_assistant.py --demo` answers 6 driver questions via keyword routing + console
   "speech" (mocked tool results if the orchestrator isn't running).

No keys, no model, no network beyond localhost.

## What to show in the demo

Start the orchestrator, then `python outbound.py` in one pane and `python intake.py --demo`
in another. Watch a plain-English clinic "phone call" become a structured STAT job, the
hub re-plan, and the voice agent place the outbound ETA "call" to the courier — all locally,
with the local-LLM and ElevenLabs paths lighting up if keys/model are present and gracefully
degrading to keyword NLU + console narration if you pull the network cable.
