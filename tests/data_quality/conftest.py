"""Make the data/ pipeline modules importable from the DQ tests.

The build pipeline runs as ``python data/build.py`` (so data/ is on sys.path[0]
and modules import each other as plain ``import quality``). We mirror that here
so the tests exercise the exact same single-source-of-truth modules.
"""
from __future__ import annotations

import sys
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
if str(_DATA_DIR) not in sys.path:
    sys.path.insert(0, str(_DATA_DIR))
