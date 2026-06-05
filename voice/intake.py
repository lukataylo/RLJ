"""Inbound intake: raw text/transcript -> NLU -> POST /jobs on the orchestrator.

This is the inbound half of the voice stream. A clinic "calls in" a request in natural
language; we extract a structured DeliveryJob (nlu.py) and post it to the orchestrator,
which plans + broadcasts. The orchestrator fills id/status/created_at.

Usage:
  python intake.py "STAT bloods from Somers Town to St Thomas by half ten, cold chain"
  python intake.py --demo          # post all 3 canned demo requests
  python intake.py --demo 2        # post just demo #2
  echo "transcript..." | python intake.py        # read text from stdin

Telephony flaky? The canned demos guarantee a live demo still works end to end.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Optional

import httpx

try:  # load .env if python-dotenv is installed; harmless if not.
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass

from nlu import parse_intake

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000").rstrip("/")

# Canned demo requests — phrased like real clinic calls, mapped to the sample gazetteer
# so they plan cleanly against the mock orchestrator even with the keyword fallback.
DEMO_REQUESTS: list[str] = [
    "Hi, this is the Somers Town surgery — we've got STAT INR bloods that need to go "
    "to St Thomas lab by half ten, and it's cold chain please.",
    "Royal London pharmacy here, need an insulin delivery to a housebound patient in "
    "Bow before midday, fairly urgent.",
    "Camden clinic — just some routine histology samples for St Thomas, sometime this "
    "afternoon is fine.",
]


def submit(text: str) -> Optional[dict[str, Any]]:
    """Parse `text` and POST the resulting job. Returns the created job, or None on error."""
    job = parse_intake(text)
    print(f"[intake] parsed {job['priority'].upper()} {job['type']}: "
          f"{job['origin'].get('name', '?')} -> {job['destination'].get('name', '?')}")
    try:
        with httpx.Client(timeout=15) as client:
            r = client.post(f"{ORCHESTRATOR_URL}/jobs", json=job)
            r.raise_for_status()
            created = r.json()
        print(f"[intake] posted job {created.get('id')} (status={created.get('status')})")
        return created
    except Exception as e:  # noqa: BLE001
        print(f"[intake] POST /jobs failed ({type(e).__name__}: {e}) — is the orchestrator up?")
        return None


def _read_text_arg(args: list[str]) -> str:
    if args:
        return " ".join(args)
    if not sys.stdin.isatty():  # piped transcript
        return sys.stdin.read()
    return ""


def main(argv: list[str]) -> int:
    args = argv[1:]
    if args and args[0] == "--demo":
        which = args[1] if len(args) > 1 else None
        if which is not None:
            idx = int(which) - 1
            if not (0 <= idx < len(DEMO_REQUESTS)):
                print(f"[intake] demo index must be 1..{len(DEMO_REQUESTS)}")
                return 2
            submit(DEMO_REQUESTS[idx])
        else:
            for req in DEMO_REQUESTS:
                submit(req)
        return 0

    text = _read_text_arg(args)
    if not text.strip():
        print(__doc__)
        return 2
    return 0 if submit(text) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
