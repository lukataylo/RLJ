"""TfL roadside Variable Message Sign DQ tests."""
from __future__ import annotations

import roadsigns as roadsigns_mod
import quality


def test_roadsigns_sane():
    payload = roadsigns_mod.build_roadsigns(allow_network=False)
    quality.validate_roadsigns(payload)

    signs = payload["signs"]
    assert any("DELAYS" in s["message"] for s in signs)
    assert any(s["severity"] == "severe" for s in signs)


def test_tfl_vms_normalizer_handles_place_payload():
    raw = [
        {
            "id": "vms-live-1",
            "commonName": "A201 VMS",
            "lat": 51.51,
            "lon": -0.1,
            "active": True,
            "additionalProperties": [{"key": "message", "value": "LONG DELAYS USE ALT ROUTE"}],
        }
    ]

    signs = roadsigns_mod.normalize_tfl_vms(raw)
    assert signs[0]["id"] == "vms-live-1"
    assert signs[0]["message"] == "LONG DELAYS USE ALT ROUTE"
    quality.validate_roadsigns(
        {
            "source": "live",
            "fetched_at": signs[0]["updated_at"],
            "provider": "test",
            "signs": signs,
        }
    )
