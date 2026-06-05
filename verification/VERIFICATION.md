# Verification status

_Generated 2026-06-05T22:39:50.641552+00:00 — machine output of `make verify`. Each claim is credited only because its external test passed._

**Must-pass gate: ✅ GREEN** (19/19) · verified 22/22 · failing 0 · unverified 0

## impact

| | claim | test | status |
|--|--|--|--|
| ✅ ⭐ | STAT samples meet their clinical window ≥95% of the time | `test_stat_window_compliance` | verified |
| ✅ ⭐ | Solver beats naive greedy dispatch on windows met | `test_beats_greedy` | verified |
| ✅ ⭐ | Reported ETAs and total time are physically plausible (no scaling bug) | `test_eta_plausibility` | verified |

## performance

| | claim | test | status |
|--|--|--|--|
| ✅ ⭐ | Re-optimises within the real-time budget | `test_solve_budget` | verified |
| ✅ | Solver objective does not regress vs the golden baseline | `test_golden_no_regression` | verified |

## contract

| | claim | test | status |
|--|--|--|--|
| ✅ ⭐ | Every Plan emitted validates against the shared schema | `test_plan_validates` | verified |
| ✅ ⭐ | Every DeliveryJob accepted validates against the shared schema | `test_job_roundtrip_validates` | verified |
| ✅ ⭐ | Routing /optimize honours the OptimizeRequest/Response contract | `test_optimize_endpoint_contract` | verified |

## data

| | claim | test | status |
|--|--|--|--|
| ✅ ⭐ | All NHS facility coordinates lie within Greater London | `test_within_london_bbox` | verified |
| ✅ ⭐ | Facility dataset has no missing required fields or duplicate ids | `test_required_fields_and_unique` | verified |
| ✅ ⭐ | Synthetic demand is schema-valid with sane time windows | `test_demand_schema_and_windows` | verified |
| ✅ ⭐ | App only loads datasets whose data-quality suite passed (dq_passed=true) | `test_only_verified_data_loadable` | verified |
| ✅ | Road graph is connected and covers the London bbox | `test_graph_connected_and_bbox` | verified |
| ✅ ⭐ | Tower Bridge + event timed-disruption feeds are schema-valid within London | `test_timed_events_valid` | verified |
| ✅ ⭐ | Horizon disruptions are a superset of active (schedule sees imminent closures reaction can't) | `test_active_and_horizon_consistency` | verified |

## research

| | claim | test | status |
|--|--|--|--|
| ✅ ⭐ | Schedule-anticipation significantly beats live-only reactive routing (paired Wilcoxon p<0.05) | `test_anticipation_beats_reaction` | verified |
| ✅ ⭐ | Schedule-anticipation significantly beats disruption-blind routing | `test_anticipation_beats_blind` | verified |
| ✅ ⭐ | Anticipatory method significantly beats naive greedy dispatch | `test_beats_greedy_significantly` | verified |
| ✅ ⭐ | Anticipatory method beats Google OR-Tools operating reactively (information advantage) | `test_beats_or_tools_reactive` | verified |
| ✅ | Anticipation also helps OR-Tools (effect is the information, not our solver) | `test_anticipation_generalises_to_ortools` | verified |

## e2e

| | claim | test | status |
|--|--|--|--|
| ✅ ⭐ | Closing a road triggers a live re-route and scoreboard update | `test_close_road_reroutes` | verified |
| ✅ ⭐ | A new job produces a voice_call dispatch notification | `test_voice_call_emitted` | verified |
