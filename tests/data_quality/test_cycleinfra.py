"""Cycle infrastructure DQ tests."""
from __future__ import annotations

import cycleinfra as cycleinfra_mod
import quality


def test_cycleinfra_sane():
    payload = cycleinfra_mod.build_cycleinfra()
    quality.validate_cycleinfra(payload)

    # CS3 centroid coordinate: 51.5110, -0.0750
    mult = cycleinfra_mod.cycle_infrastructure_ratio(51.5110, -0.0750)
    assert mult == 1.3

    # Far away from any CS
    mult_far = cycleinfra_mod.cycle_infrastructure_ratio(51.6000, -0.4000)
    assert mult_far == 1.0
