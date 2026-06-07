"""Structure the agent's reply: separate reasoning from the answer, and detect an
optional operator action the chat can offer as a Yes/No decision card.

Pure and dependency-free so it is unit-testable offline and behaves identically no
matter where the answer came from:

* local **Nemotron** over Ollama (a reasoning model — wraps its chain-of-thought in
  ``<think>…</think>``),
* **OpenAI** in production (no reasoning markers), or
* the deterministic offline fallback.

``split_reasoning`` lifts the chain-of-thought out so the spoken / markdown answer stays
clean while the UI can still show the reasoning (dimmed) above the answer.
``propose_action`` reads the exchange + the live fleet and returns a *single*
executable action — and only one the orchestrator can actually perform (it never
fabricates a control that has no endpoint).
"""
from __future__ import annotations

import re
from typing import Optional

# Reasoning models fence their chain-of-thought; accept <think> and <thinking>.
_THINK_RE = re.compile(r"<think(?:ing)?>(.*?)</think(?:ing)?>", re.IGNORECASE | re.DOTALL)
# A dangling/unclosed <think> (truncated stream): everything after it is reasoning.
_OPEN_THINK_RE = re.compile(r"<think(?:ing)?>(.*)$", re.IGNORECASE | re.DOTALL)


def split_reasoning(text: str) -> tuple[str, str]:
    """Return ``(reasoning, answer)``.

    Lifts ``<think>…</think>`` chain-of-thought out of the model output. When there are
    no reasoning markers, ``reasoning`` is ``""`` and ``answer`` is the text unchanged.
    """
    if not text:
        return "", ""
    chunks = _THINK_RE.findall(text)
    answer = _THINK_RE.sub("", text)
    reasoning = "\n\n".join(c.strip() for c in chunks if c.strip())
    if not reasoning:  # handle a dangling/unclosed <think>
        m = _OPEN_THINK_RE.search(answer)
        if m:
            reasoning = m.group(1).strip()
            answer = _OPEN_THINK_RE.sub("", answer)
    return reasoning.strip(), answer.strip()


# Intent cues. Ordered by specificity in ``propose_action`` (reroute → re-plan → notify).
_REDIRECT_RE = re.compile(
    r"\b(re-?route|re-?direct|divert|re-?path|send .*? around|go around|avoid)\b", re.I)
_REPLAN_RE = re.compile(
    r"\b(re-?optimi[sz]e|re-?plan|re-?assign|re-?balance|re-?allocate|re-?shuffle)\b", re.I)
_CONTACT_RE = re.compile(
    r"\b(notify|contact|message|call|alert|text|ping|let .*? know|heads[- ]?up)\b", re.I)


def _match_courier(text: str, couriers: list[dict]) -> Optional[dict]:
    """Resolve the first courier referenced by id or name (case-insensitive)."""
    low = (text or "").lower()
    for c in couriers:
        cid = (c.get("id") or "").lower()
        name = (c.get("name") or "").lower()
        if cid and cid in low:
            return c
        if name and name in low:
            return c
    return None


def propose_action(question: str, answer: str, couriers: list[dict]) -> Optional[dict]:
    """Detect an executable operator action implied by the exchange, grounded in the live
    fleet. Returns a decision-card dict, or ``None`` when nothing actionable was proposed.

    The dict is self-describing so the client can execute it generically::

        {"type", "label", "confirm", "endpoint", "method", "body"?, "courier_id"?}

    Only actions with a real orchestrator endpoint are ever proposed (redirect /
    re-optimise / notify) — no fabricated controls.
    """
    couriers = couriers or []
    combined = f"{question or ''}\n{answer or ''}"

    # 1) Reroute a specific courier — needs a real courier to target.
    if _REDIRECT_RE.search(combined):
        c = _match_courier(combined, couriers)
        if c is None and len(couriers) == 1:
            c = couriers[0]
        if c is not None and c.get("id"):
            cid = c["id"]
            who = c.get("name") or cid
            return {
                "type": "redirect",
                "courier_id": cid,
                "label": f"Reroute {who} around live congestion?",
                "confirm": "Reroute",
                "endpoint": f"/couriers/{cid}/redirect",
                "method": "POST",
            }

    # 2) Re-plan / reassign the whole fleet.
    if _REPLAN_RE.search(combined):
        return {
            "type": "optimize",
            "label": "Re-optimise the fleet now?",
            "confirm": "Re-plan",
            "endpoint": "/optimize",
            "method": "POST",
        }

    # 3) Contact a courier (or the whole fleet) with a heads-up.
    if _CONTACT_RE.search(combined):
        c = _match_courier(combined, couriers)
        who = (c.get("name") or c.get("id")) if c else "the fleet"
        return {
            "type": "notify",
            "courier_id": (c.get("id") if c else None),
            "label": f"Send a heads-up to {who}?",
            "confirm": "Send",
            "endpoint": "/notifications",
            "method": "POST",
            "body": {
                "channel": "sms",
                "to": ((c.get("phone") or c.get("id")) if c else "fleet"),
                "message": (answer or "").strip()[:240] or "Dispatch update from PulseGo.",
            },
        }

    return None
