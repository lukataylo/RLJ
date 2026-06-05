# Verification status

_Generated 2026-06-05T21:39:30.933968+00:00 — machine output of `make verify`. Each claim is credited only because its external test passed._

**Must-pass gate: ❌ NOT GREEN** (0/13) · verified 0/15 · failing 0 · unverified 15

## impact

| | claim | test | status |
|--|--|--|--|
| ⏳ ⭐ | STAT samples meet their clinical window ≥95% of the time | `test_stat_window_compliance` | unverified |
| ⏳ ⭐ | Solver beats naive greedy dispatch on windows met | `test_beats_greedy` | unverified |
| ⏳ ⭐ | Reported ETAs and total time are physically plausible (no scaling bug) | `test_eta_plausibility` | unverified |

## performance

| | claim | test | status |
|--|--|--|--|
| ⏳ ⭐ | Re-optimises within the real-time budget | `test_solve_budget` | unverified |
| ⏳ | Solver objective does not regress vs the golden baseline | `test_golden_no_regression` | unverified |

## contract

| | claim | test | status |
|--|--|--|--|
| ⏳ ⭐ | Every Plan emitted validates against the shared schema | `test_plan_validates` | unverified |
| ⏳ ⭐ | Every DeliveryJob accepted validates against the shared schema | `test_job_roundtrip_validates` | unverified |
| ⏳ ⭐ | Routing /optimize honours the OptimizeRequest/Response contract | `test_optimize_endpoint_contract` | unverified |

## data

| | claim | test | status |
|--|--|--|--|
| ⏳ ⭐ | All NHS facility coordinates lie within Greater London | `test_within_london_bbox` | unverified |
| ⏳ ⭐ | Facility dataset has no missing required fields or duplicate ids | `test_required_fields_and_unique` | unverified |
| ⏳ ⭐ | Synthetic demand is schema-valid with sane time windows | `test_demand_schema_and_windows` | unverified |
| ⏳ ⭐ | App only loads datasets whose data-quality suite passed (dq_passed=true) | `test_only_verified_data_loadable` | unverified |
| ⏳ | Road graph is connected and covers the London bbox | `test_graph_connected_and_bbox` | unverified |

## e2e

| | claim | test | status |
|--|--|--|--|
| ⏳ ⭐ | Closing a road triggers a live re-route and scoreboard update | `test_close_road_reroutes` | unverified |
| ⏳ ⭐ | A new job produces a voice_call dispatch notification | `test_voice_call_emitted` | unverified |
