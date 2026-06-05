"""Pure-function routing test for the driver-assistant keyword router.

No orchestrator, no model, no network: this pins that the zero-credential keyword router
(`driver_assistant.route_question`) maps each FAQ question to the correct tool. It is the
contract the LLM router is allowed to *improve on* but never silently break.
"""
from __future__ import annotations

import driver_assistant as da

# Each FAQ question -> the tool name the keyword router must select.
FAQ_TO_TOOL: list[tuple[str, str]] = [
    ("Where's my next pickup?",                    "next_pickup"),
    ("Why am I being rerouted?",                   "reroute_reason"),
    ("Is Tower Bridge open?",                      "bridge_status"),
    ("Where can I park when I get there?",         "get_guidance"),
    ("Should I catch the next green — what speed?", "get_signal_advice"),
    ("How's traffic right now?",                   "get_congestion"),
]


def test_driver_assistant_answers():
    """The 6 FAQ questions route to the right tool(s) with no network access."""
    valid = set(da.VALID_TOOLS)
    for question, expected_tool in FAQ_TO_TOOL:
        tools = da.route_question(question)
        assert isinstance(tools, list) and tools, f"no tool routed for {question!r}"
        assert set(tools) <= valid, f"unknown tool in {tools} for {question!r}"
        assert expected_tool in tools, (
            f"{question!r} routed to {tools}, expected {expected_tool!r}"
        )
