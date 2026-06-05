# AGENT.md — Voice stream (Agent 1)

Owner of `voice/` only. May read `contracts/`, `orchestrator/`. Never touch `routing/`,
`frontend/`. Integrate strictly through `../contracts/api.md` — do not invent endpoints
and do not call the routing service.

## Build checklist

- [x] `nlu.py` — intake text → `DeliveryJob` dict matching `../contracts/schemas.json`.
      OpenAI-compatible LLM path (strict JSON system prompt + few-shots from sample
      `raw_text`) **and** a regex/keyword fallback. Server fills id/status/created_at.
- [x] `intake.py` — CLI/stdin → `parse_intake` → `POST /jobs`. 3 canned demo requests.
- [x] `outbound.py` — subscribe `WS /ws`; on `notification` with `channel=="voice_call"`
      call `place_call(to, message)`; mirror `agent_log` narration. Auto-reconnect.
- [x] `elevenlabs_client.py` — guarded TTS + outbound-call wrapper; missing key ⇒ no-op.
- [x] `.env.example`, `requirements.txt`, `README.md` (incl. demo paragraph).
- [x] Runs standalone vs. the mock orchestrator with **no** ElevenLabs key and **no**
      model (keyword NLU + console output).

### Definition of done (shared, from AGENTS.md)
1. Runs standalone against the mock orchestrator. ✔
2. Survives its fallback rung (model flaky → keyword NLU; ElevenLabs down → console/TTS). ✔
3. One-paragraph "what to show in the demo" in `README.md`. ✔

## Fallback ladder (this stream)

| If this fails… | Fall back to |
|---|---|
| Local Nemotron NLU | constrained JSON prompt → keyword/regex parser (`nlu.py`) |
| Live telephony | text/stdin intake + 3 canned demo requests (`intake.py --demo`) |
| ElevenLabs voice | local TTS file → plain console "call" print (`outbound.py`) |

## NemoClaw notes

Voice runs as a NemoClaw sandboxed agent. Egress is locked to **ElevenLabs + the
orchestrator only** (everything else returns 403). Policy: `../nemoclaw/policy-voice.yaml`.

- Allowed hosts: `api.elevenlabs.io:443`, the orchestrator at
  `host.openshell.internal:8000` (host-side `localhost:8000`), optional `api.telegram.org:443`.
- The local model is reached at `inference.local` (or Ollama `localhost:11434`) — set
  `LLM_BASE_URL` accordingly. Pure-local inference needs no egress allowance.
- Each endpoint needs an access mode (`access: full` + `tls: skip`) **and** a `binaries`
  allowlist or the proxy 403s even when the host is listed. Names are lowercase RFC-1123.

Apply / verify:
```bash
SANDBOX=rlj-voice
nemoclaw $SANDBOX policy-add --from-file ../nemoclaw/policy-voice.yaml --yes
openshell policy get $SANDBOX --full | grep -E "host:|port:"
```

## Contract touchpoints used

- `POST /jobs` (inbound) — body is a `DeliveryJob`; id/status/created_at omitted.
- `WS /ws` (outbound) — react to `{type:"notification", payload:Notification}` where
  `payload.channel == "voice_call"`. `agent_log` is mirrored for narration.
