"""Path setup for the external (judge) benchmark suite.

These benchmarks live in their own folder and only READ the system under test
(routing/, orchestrator/, data/, tests/backtests/). We put those package dirs on
sys.path so the benchmarks can import the production modules directly and exercise
the same code paths the app uses.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# Production code + the existing backtest helpers we deliberately reuse.
for _p in ("routing", "orchestrator", "data", "tests/backtests"):
    _full = str(ROOT / _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)
