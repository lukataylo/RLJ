# NemoClaw — running RLJ agents locally on the DGX Spark

Two of our components run as NemoClaw sandboxed agents on local Nemotron inference:

| Agent | Sandbox policy | Egress allowed |
|-------|----------------|----------------|
| **Voice / dispatch** | `policy-voice.yaml` | `api.elevenlabs.io`, the orchestrator (`host.openshell.internal:8000`), optional `api.telegram.org` |
| **Routing reasoning** (optional) | `policy-routing.yaml` | none — `inference.local` only. Pure local compute. |

The frontend and the GPU routing service run as normal local processes (not sandboxed) —
they don't need NemoClaw, just the GB10 and the local model.

## Apply a policy (hot-reload, no rebuild for network changes)

```bash
SANDBOX=rlj-voice
nemoclaw $SANDBOX policy-add --from-file ./policy-voice.yaml --yes
openshell policy get $SANDBOX --full | grep -E "host:|port:"   # confirm egress
```

## Why this split

- **Routing** touches patient-derived job data and must never exfiltrate — zero egress,
  kernel-enforced. This is the local-first story for the judges.
- **Voice** needs exactly one external host (ElevenLabs) plus the local orchestrator. Lock
  the allowlist to those; everything else is denied (`curl example.com` → 403).

> Each endpoint needs an **access mode** (`access: full` + `tls: skip` for a raw tunnel) and
> a **`binaries`** allowlist, or the egress proxy returns 403 even though the host is listed.
> Names must be lowercase RFC-1123 (hyphens, no underscores). See the NemoClaw playbook.
