"""Thin, fully-guarded wrapper around ElevenLabs (TTS + conversational agents).

Design rule for the demo: *every* network call is guarded by the presence of an API
key. With no ELEVENLABS_API_KEY the wrapper becomes a logging no-op so the whole voice
stream runs offline (the "pull the network cable" money shot in ARCHITECTURE.md).

Egress is restricted to api.elevenlabs.io by the NemoClaw policy (../nemoclaw/policy-voice.yaml).
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

ELEVENLABS_BASE = "https://api.elevenlabs.io"


class ElevenLabsClient:
    """Speak text or trigger an outbound conversational-agent call.

    All methods are safe to call with no credentials: they detect the missing key,
    log, and return without touching the network.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY", "")
        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        self.agent_id = agent_id or os.getenv("ELEVENLABS_AGENT_ID", "")

    @property
    def enabled(self) -> bool:
        """True only when we actually have a key to talk to ElevenLabs."""
        return bool(self.api_key)

    # ------------------------------------------------------------------ TTS
    def tts(self, message: str, out_path: str = "out.mp3") -> Optional[str]:
        """Synthesise `message` to an MP3 file. Returns the path, or None if disabled."""
        if not self.enabled:
            print(f"[elevenlabs] (no key) would synthesise: {message!r}")
            return None
        url = f"{ELEVENLABS_BASE}/v1/text-to-speech/{self.voice_id}"
        body = {
            "text": message,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        try:
            with httpx.Client(timeout=30) as client:
                r = client.post(url, headers=self._headers("audio/mpeg"), json=body)
                r.raise_for_status()
                with open(out_path, "wb") as f:
                    f.write(r.content)
            print(f"[elevenlabs] wrote TTS audio -> {out_path}")
            return out_path
        except Exception as e:  # noqa: BLE001 — never let voice break the demo
            print(f"[elevenlabs] TTS failed ({type(e).__name__}: {e})")
            return None

    # ------------------------------------------------------------------ outbound call
    def call(self, to: str, message: str) -> bool:
        """Place an outbound call via the ElevenLabs conversational-agent API.

        Returns True if a request was made successfully. With no key/agent it logs and
        returns False so callers can fall back to console/TTS.
        """
        if not self.enabled or not self.agent_id:
            why = "no API key" if not self.enabled else "no ELEVENLABS_AGENT_ID"
            print(f"[elevenlabs] ({why}) would call {to}: {message!r}")
            return False
        # Outbound calling requires a configured agent + phone number on the ElevenLabs
        # side; we issue the documented trigger and let it dial. Failures degrade to log.
        url = f"{ELEVENLABS_BASE}/v1/convai/twilio/outbound-call"
        body = {
            "agent_id": self.agent_id,
            "to_number": to,
            "conversation_initiation_client_data": {
                "dynamic_variables": {"eta_message": message},
            },
        }
        try:
            with httpx.Client(timeout=30) as client:
                r = client.post(url, headers=self._headers(), json=body)
                r.raise_for_status()
            print(f"[elevenlabs] placed outbound call to {to}")
            return True
        except Exception as e:  # noqa: BLE001
            print(f"[elevenlabs] outbound call failed ({type(e).__name__}: {e})")
            return False

    # ------------------------------------------------------------------ helpers
    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        return {"xi-api-key": self.api_key, "accept": accept, "content-type": "application/json"}
