"""Pure, offline tests for the agent reply structuring (orchestrator/agent_actions.py):
separating a reasoning model's chain-of-thought from its answer, and proposing a single
executable operator action (decision card) grounded in the live fleet.

These are provider-agnostic by construction — agent_actions takes plain strings + a
courier list, so the SAME logic covers a local Nemotron answer (which emits
``<think>…</think>``), an OpenAI answer (no markers), and the deterministic fallback.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _mod():
    sys.path.insert(0, str(ROOT / "orchestrator"))
    return importlib.import_module("agent_actions")


# ---------------------------------------------------------------- split_reasoning
def test_split_reasoning_extracts_think_block():
    a = _mod()
    reasoning, answer = a.split_reasoning(
        "<think>Camden Rd is congested; rerouting saves 6 min.</think>\n"
        "Reroute **Alex** now.")
    assert "congested" in reasoning
    assert answer == "Reroute **Alex** now."
    assert "<think>" not in answer and "</think>" not in answer


def test_split_reasoning_no_markers_passthrough():
    a = _mod()
    reasoning, answer = a.split_reasoning("Two couriers are en route.")
    assert reasoning == ""
    assert answer == "Two couriers are en route."


def test_split_reasoning_handles_unclosed_think():
    # A truncated stream can leave a dangling <think> with no closing tag.
    a = _mod()
    reasoning, answer = a.split_reasoning("Here is the plan. <think>still thinking")
    assert reasoning == "still thinking"
    assert answer == "Here is the plan."


def test_split_reasoning_supports_thinking_alias():
    a = _mod()
    reasoning, answer = a.split_reasoning("<thinking>weigh options</thinking>Go via A40.")
    assert reasoning == "weigh options"
    assert answer == "Go via A40."


# ---------------------------------------------------------------- propose_action
COURIERS = [
    {"id": "crt-1", "name": "Alex", "phone": "+44 700 900001"},
    {"id": "crt-2", "name": "Sam", "phone": "+44 700 900002"},
]


def test_propose_redirect_targets_named_courier():
    a = _mod()
    action = a.propose_action("Should I reroute Alex?", "Yes, reroute Alex now.", COURIERS)
    assert action and action["type"] == "redirect"
    assert action["courier_id"] == "crt-1"
    assert action["endpoint"] == "/couriers/crt-1/redirect"
    assert action["method"] == "POST"


def test_propose_redirect_matches_courier_by_id():
    a = _mod()
    action = a.propose_action("divert crt-2 around the closure", "", COURIERS)
    assert action and action["courier_id"] == "crt-2"


def test_propose_redirect_needs_a_target_when_ambiguous():
    # Reroute intent but no specific courier and >1 in the fleet -> no card (never guess).
    a = _mod()
    action = a.propose_action("can we reroute someone?", "Maybe reroute a courier.", COURIERS)
    assert action is None


def test_propose_redirect_single_courier_is_unambiguous():
    a = _mod()
    action = a.propose_action("reroute around traffic", "", [COURIERS[0]])
    assert action and action["type"] == "redirect" and action["courier_id"] == "crt-1"


def test_propose_optimize_for_replan():
    a = _mod()
    action = a.propose_action("re-plan the fleet", "I'll re-optimise all routes.", COURIERS)
    assert action and action["type"] == "optimize"
    assert action["endpoint"] == "/optimize"


def test_propose_notify_with_message_body():
    a = _mod()
    action = a.propose_action("notify Sam about the delay", "Telling Sam to expect 10 min.",
                              COURIERS)
    assert action and action["type"] == "notify"
    assert action["courier_id"] == "crt-2"
    assert action["endpoint"] == "/notifications"
    assert action["body"]["message"]  # a non-empty heads-up is synthesised


def test_propose_none_for_plain_question():
    a = _mod()
    action = a.propose_action("how many couriers are active?",
                              "Two couriers and three jobs.", COURIERS)
    assert action is None
