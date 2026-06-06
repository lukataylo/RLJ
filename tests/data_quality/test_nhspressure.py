"""NHS hospital A&E pressure DQ tests."""
from __future__ import annotations

import nhspressure as nhspressure_mod
import quality


def test_nhspressure_sane():
    payload = nhspressure_mod.build_nhspressure()
    quality.validate_nhspressure(payload)

    rec = nhspressure_mod.hospital_pressure("gstt", "2026-06-05")
    assert rec["hospital_id"] == "gstt"
    assert rec["load"] in ("normal", "busy", "critical")
    assert rec["wait_time_min"] >= 30
