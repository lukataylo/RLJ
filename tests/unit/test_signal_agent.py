"""Fast, deterministic unit tests for the GB10 signal agent (scan11/signal_agent.py).

No network: we monkeypatch signal_agent._post_json (the only outbound call inside
ask_nemotron) to return a canned Ollama /api/chat response, then assert that the
parsing/filtering logic keeps ONLY well-formed recommendations and stamps each with
source 'nemotron@scan-11' and float lat/lng. A second case proves a non-JSON model
reply degrades gracefully to [].
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

# scan11/ is not on sys.path by default (tests/conftest.py only adds orchestrator+routing).
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scan11"))

import signal_agent  # noqa: E402


CELLS = [
    {"lat": 51.5134, "lng": -0.0886, "congestion": 0.91},
    {"lat": 51.4946, "lng": -0.0997, "congestion": 0.77},
]


def test_ask_nemotron_parses_and_filters(monkeypatch):
    """One valid rec + one malformed (no lat) -> only the valid rec is returned, with
    lat/lng coerced to float and source stamped to 'nemotron@scan-11'."""
    valid = {"name": "Bank junction", "lat": "51.5134", "lng": "-0.0886",
             "action": "green_wave", "detail": "Extend N-S green for couriers.",
             "confidence": 0.8}
    malformed = {"name": "Broken junction", "lng": -0.0997,  # missing lat
                 "action": "hold", "detail": "should be dropped"}
    model_content = json.dumps({"recommendations": [valid, malformed]})

    def _fake_post(url, payload, timeout=10.0):
        assert "/api/chat" in url
        return {"message": {"content": model_content}}

    monkeypatch.setattr(signal_agent, "_post_json", _fake_post)

    out = signal_agent.ask_nemotron(CELLS)

    assert isinstance(out, list)
    assert len(out) == 1, f"malformed rec should have been filtered out: {out}"
    rec = out[0]
    assert rec["name"] == "Bank junction"
    assert rec["source"] == "nemotron@scan-11"
    assert isinstance(rec["lat"], float) and rec["lat"] == 51.5134
    assert isinstance(rec["lng"], float) and rec["lng"] == -0.0886
    assert isinstance(rec["confidence"], float) and rec["confidence"] == 0.8
    assert rec["action"] == "green_wave"
    assert rec["detail"] == "Extend N-S green for couriers."


def test_ask_nemotron_handles_non_json(monkeypatch):
    """A model reply whose content is not valid JSON degrades to an empty list."""
    def _fake_post(url, payload, timeout=10.0):
        return {"message": {"content": "Sorry, I can't help with that."}}

    monkeypatch.setattr(signal_agent, "_post_json", _fake_post)

    out = signal_agent.ask_nemotron(CELLS)
    assert out == []
