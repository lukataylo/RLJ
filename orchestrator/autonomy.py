"""Autonomy controller — the multi-agent sense -> decide -> act loop, made explicit.

The system runs three cooperating agents:
  * Data-Curator  — validates crowdsourced driver pings and maintains the congestion field.
  * Dispatcher    — re-optimises medical-courier routes around manual/scheduled disruptions
                    AND congestion derived from the live field.
  * Driver/Voice  — communicates dispatch + green-wave guidance (handled by the voice stack).

This module encapsulates the closed loop deterministically so it can be unit-tested without
a running server (the FastAPI app drives the same logic event-by-event). `solve` is injected
(dependency inversion) so the controller has no heavy routing import and stays testable.
"""
from __future__ import annotations
from datetime import datetime, timezone

import congestion as congestion_mod


class AutonomyController:
    def __init__(self, solve):
        # solve(jobs, couriers, disruptions, now) -> Plan-like object with .routes/.unassigned
        self.solve = solve
        self.metrics = {"cycles": 0, "replans": 0, "dispatches": 0,
                        "congestion_cells": 0, "pings_ingested": 0, "pings_rejected": 0}

    def cycle(self, *, jobs, couriers, pings, manual_disruptions=None, now=None):
        """One sense->decide->act cycle. Returns the actions taken + metrics."""
        now = now or datetime.now(timezone.utc)
        manual_disruptions = list(manual_disruptions or [])
        self.metrics["cycles"] += 1

        # SENSE — curator validates pings and updates the congestion field
        accepted, rejected = congestion_mod.validate_pings(pings)
        self.metrics["pings_ingested"] += len(accepted)
        self.metrics["pings_rejected"] += len(rejected)
        field = congestion_mod.estimate_field(accepted, now)
        self.metrics["congestion_cells"] = len(field["cells"])

        # DECIDE — merge manual/scheduled disruptions with congestion-derived ones, re-plan
        derived = congestion_mod.field_to_disruptions(field)
        disruptions = manual_disruptions + derived
        plan = self.solve(jobs, couriers, disruptions, now)
        self.metrics["replans"] += 1

        # ACT — emit a dispatch notification per served job
        notifications = []
        for route in getattr(plan, "routes", []):
            cid = getattr(route, "courier_id", None)
            for stop in getattr(route, "stops", []):
                if getattr(stop, "kind", None) == "dropoff":
                    notifications.append({"channel": "voice_call", "courier_id": cid,
                                          "job_id": stop.job_id,
                                          "message": f"Dispatch {stop.job_id} (ETA-aware route)."})
        self.metrics["dispatches"] += len(notifications)

        return {"plan": plan, "congestion": field, "disruptions": disruptions,
                "notifications": notifications, "metrics": dict(self.metrics)}
