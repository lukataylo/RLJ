"""Fast, deterministic unit tests for the GB10 signal agent's operator-answering and
per-driver assessment helpers (scan11/signal_agent.py).

No network: we monkeypatch signal_agent._get_json (the only inbound HTTP call) and
signal_agent._post_json (the only outbound call). _post_json is dispatched on URL —
the Ollama /api/chat call returns a canned chat reply, while orchestrator posts are
captured so we can assert their shape.
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


def test_answer_pending_tasks_posts_answer(monkeypatch):
    """Each pending operator task is answered: the agent asks the local model (Ollama
    /api/chat) and posts a non-empty answer to the orchestrator's /agent/answer with the
    matching task_id."""
    tasks = [
        {"id": "task-1", "question": "Which junctions are worst?", "status": "pending"},
        {"id": "task-2", "question": "Any drivers at risk?", "status": "pending"},
    ]

    def _fake_get(url, timeout=8.0):
        assert url.endswith("/agent/tasks"), url
        return tasks

    posted: list = []

    def _fake_post(url, payload, timeout=10.0):
        if "/api/chat" in url:
            # canned local-Nemotron reply
            return {"message": {"content": "Bank and Aldgate are the worst right now."}}
        posted.append((url, payload))
        return {"ok": True}

    monkeypatch.setattr(signal_agent, "_get_json", _fake_get)
    monkeypatch.setattr(signal_agent, "_post_json", _fake_post)

    signal_agent.answer_pending_tasks(CELLS)

    answers = [(u, p) for (u, p) in posted if u.endswith("/agent/answer")]
    assert len(answers) == len(tasks), f"expected one answer per task, got {posted}"
    answered_ids = set()
    for url, payload in answers:
        assert set(payload.keys()) >= {"task_id", "answer"}, payload
        assert isinstance(payload["answer"], str) and payload["answer"].strip(), payload
        answered_ids.add(payload["task_id"])
    assert answered_ids == {"task-1", "task-2"}


def test_assess_drivers_parses_and_filters(monkeypatch):
    """A canned JSON assessments reply is parsed; an invalid status is coerced to
    'on_time', an item with no courier_id is dropped, and the cleaned, well-formed
    assessments are POSTed to /fleet/assessments."""
    state = {"couriers": [
        {"id": "c-1", "name": "Ada", "location": {"lat": 51.51, "lng": -0.12}},
        {"id": "c-2", "name": "Bo", "location": {"lat": 51.52, "lng": -0.10}},
        {"id": "c-3", "name": "Cy", "location": {"lat": 51.49, "lng": -0.09}},
    ]}
    reply = {"assessments": [
        {"courier_id": "c-1", "status": "at_risk", "note": "Stuck behind Bank gridlock."},
        {"courier_id": "c-2", "status": "exploded", "note": "bogus status -> on_time"},
        {"status": "on_time", "note": "no courier_id, must be dropped"},
    ]}

    def _fake_post(url, payload, timeout=10.0):
        if "/api/chat" in url:
            return {"message": {"content": json.dumps(reply)}}
        _fake_post.captured = (url, payload)  # type: ignore[attr-defined]
        return {"accepted": len(payload.get("assessments", []))}

    monkeypatch.setattr(signal_agent, "_post_json", _fake_post)

    signal_agent.assess_drivers(state, CELLS)

    url, payload = _fake_post.captured  # type: ignore[attr-defined]
    assert url.endswith("/fleet/assessments"), url
    out = payload["assessments"]
    by_id = {a["courier_id"]: a for a in out}

    # item without courier_id dropped
    assert set(by_id.keys()) == {"c-1", "c-2"}, out
    # valid status preserved
    assert by_id["c-1"]["status"] == "at_risk"
    assert by_id["c-1"]["note"] == "Stuck behind Bank gridlock."
    # invalid status coerced to on_time
    assert by_id["c-2"]["status"] == "on_time"
    # every emitted item is well-formed
    valid = {"on_time", "reroute_suggested", "at_risk"}
    for a in out:
        assert set(a.keys()) >= {"courier_id", "status", "note"}, a
        assert isinstance(a["courier_id"], str) and a["courier_id"]
        assert a["status"] in valid
        assert isinstance(a["note"], str)
