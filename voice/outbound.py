"""Outbound dispatch: listen on the orchestrator WS, place calls on `notification` events.

This is the outbound half of the voice stream. Per contracts/api.md we subscribe to
ws://localhost:8000/ws and act on events of type "notification" where the payload's
channel == "voice_call" — placing an outbound ElevenLabs call/TTS to courier or clinic
with the new ETA. Everything else (other channels, other event types) is just narrated.

Runs with NO credentials: place_call falls back to a console/TTS print so the loop is
fully demoable offline.

Usage:  python outbound.py
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import websockets

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass

from elevenlabs_client import ElevenLabsClient

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000").rstrip("/")
ORCHESTRATOR_WS = os.getenv("ORCHESTRATOR_WS") or (
    ORCHESTRATOR_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
)

_client = ElevenLabsClient()


def place_call(to: str, message: str) -> None:
    """Deliver `message` to `to`. ElevenLabs when configured, else console/TTS fallback.

    Fallback ladder: outbound call -> local TTS file -> plain console print. None of
    these raise, so a failed call never stalls the dispatch loop.
    """
    to = to or "(unknown recipient)"
    if _client.enabled and _client.agent_id and _client.call(to, message):
        return
    # No telephony available — try local TTS (writes an .mp3 if a key exists), then print.
    _client.tts(message)
    print(f"[outbound] 📞 CALL {to}: {message}")


def _handle(event: dict[str, Any]) -> None:
    """Route a single WS event."""
    etype = event.get("type")
    payload = event.get("payload") or {}

    if etype == "notification":
        if payload.get("channel") == "voice_call":
            to = payload.get("to") or ""
            message = payload.get("message") or ""
            job = payload.get("job_id")
            print(f"[outbound] notification for job {job} -> placing voice call")
            place_call(to, message)
        else:
            # telegram / ui notifications aren't ours to dial; surface them plainly.
            print(f"[outbound] notification ({payload.get('channel')}): {payload.get('message')}")
    elif etype == "agent_log":
        # Mirror the orchestrator's plain-English narration to our console.
        print(f"[outbound] agent_log[{payload.get('level')}]: {payload.get('message')}")
    # other event types (state/plan_updated/job_created/...) are for the frontend.


async def listen() -> None:
    """Connect and consume events forever, auto-reconnecting on drop."""
    print(f"[outbound] connecting to {ORCHESTRATOR_WS} ...")
    while True:
        try:
            async with websockets.connect(ORCHESTRATOR_WS) as ws:
                print("[outbound] connected — waiting for notifications (Ctrl-C to stop)")
                async for raw in ws:
                    try:
                        _handle(json.loads(raw))
                    except json.JSONDecodeError:
                        print(f"[outbound] non-JSON frame ignored: {raw!r}")
        except (OSError, websockets.WebSocketException) as e:
            print(f"[outbound] WS dropped ({type(e).__name__}: {e}); retrying in 3s ...")
            await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(listen())
    except KeyboardInterrupt:
        print("\n[outbound] stopped.")
