"""Make ``voice/`` importable for the driver-assistant tests (it isn't a package)."""
from __future__ import annotations

import sys
from pathlib import Path

VOICE_DIR = Path(__file__).resolve().parent.parent.parent / "voice"
if str(VOICE_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_DIR))
