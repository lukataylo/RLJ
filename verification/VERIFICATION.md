# Verification status

_Generated 2026-06-06T16:56:13.592368+00:00 — machine output of `make verify`. Each claim is credited only because its external test passed._

**Must-pass gate: ✅ GREEN** (73/73) · verified 83/83 · failing 0 · unverified 0

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
| ✅ ⭐ | Solver stays feasible and within time budget at fleet scale (40-80 jobs) | `test_scales_to_large_fleets` | verified |

## contract

| | claim | test | status |
|--|--|--|--|
| ✅ ⭐ | Every Plan emitted validates against the shared schema | `test_plan_validates` | verified |
| ✅ ⭐ | Every DeliveryJob accepted validates against the shared schema | `test_job_roundtrip_validates` | verified |
| ✅ ⭐ | Routing /optimize honours the OptimizeRequest/Response contract | `test_optimize_endpoint_contract` | verified |
| ✅ ⭐ | Courier vehicle_type round-trips (van/scooter) and defaults to van | `test_courier_vehicle_type_roundtrips` | verified |

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
| ✅ ⭐ | London Air Quality (LAQN) feed is schema-valid and maps borough centroids | `test_airquality_sane` | verified |
| ✅ ⭐ | TfL Streetworks timed road closure disruptions are schema-valid | `test_streetworks_sane` | verified |
| ✅ ⭐ | NHS Hospital A&E live wait times and patient load feeds are schema-valid | `test_nhspressure_sane` | verified |
| ✅ ⭐ | TfL cycle infrastructure paths and hire capacities are schema-valid | `test_cycleinfra_sane` | verified |
| ✅ ⭐ | Environment Agency flood warning timed disruptions are schema-valid | `test_floodwarnings_sane` | verified |
| ✅ ⭐ | Traffic-signal junctions + green-wave advice are schema-valid within London | `test_junctions_valid` | verified |
| ✅ ⭐ | Crowdsourced driver pings are schema-valid, in-bbox, and deterministic | `test_probe_pings_valid` | verified |
| ✅ | Weather congestion multiplier is sane and deterministic | `test_weather_multiplier_sane` | verified |
| ✅ ⭐ | Live London CCTV (TfL JamCams) endpoint returns curated cameras | `test_cctv_cameras_shape` | verified |

## research

| | claim | test | status |
|--|--|--|--|
| ✅ ⭐ | Schedule-anticipation significantly beats live-only reactive routing (paired Wilcoxon p<0.05) | `test_anticipation_beats_reaction` | verified |
| ✅ ⭐ | Schedule-anticipation significantly beats disruption-blind routing | `test_anticipation_beats_blind` | verified |
| ✅ ⭐ | Anticipatory method significantly beats naive greedy dispatch | `test_beats_greedy_significantly` | verified |
| ✅ ⭐ | Anticipatory method beats Google OR-Tools operating reactively (information advantage) | `test_beats_or_tools_reactive` | verified |
| ✅ | Anticipation also helps OR-Tools (effect is the information, not our solver) | `test_anticipation_generalises_to_ortools` | verified |
| ✅ ⭐ | Zero optimality gap vs Google OR-Tools on the clinical objective (static) | `test_optimality_gap_vs_ortools` | verified |
| ✅ ⭐ | More contributing drivers significantly improve clinical STAT on-time (network effect) | `test_more_drivers_help` | verified |
| ✅ | Flywheel benefit is monotone in driver participation | `test_benefit_is_monotone` | verified |

## benchmark

| | claim | test | status |
|--|--|--|--|
| ✅ ⭐ | Real-time replan p50 < 400ms on CPU (GB10 target <50ms) | `test_routing_latency_p50_fastpath` | verified |
| ✅ ⭐ | Replan p95 < 2000ms on CPU | `test_routing_latency_p95_cpu` | verified |
| ✅ ⭐ | 100-job instance solved < 18s with >=90% served | `test_scale_100_jobs_throughput` | verified |
| ✅ ⭐ | Anticipation lift >= 0.15 STAT on-time and significant (judge benchmark) | `test_anticipation_lift_and_significance` | verified |
| ✅ ⭐ | Flywheel lift >= 0.15 STAT on-time and significant (judge benchmark) | `test_flywheel_lift_and_significance` | verified |
| ✅ ⭐ | Congestion estimation over 10k pings < 2s | `test_telemetry_ingest_10k_under_2s` | verified |
| ✅ ⭐ | Every dataset is dq_passed and loadable; tampered data is refused | `test_every_dataset_dq_passed_and_loadable` | verified |

## autonomy

| | claim | test | status |
|--|--|--|--|
| ✅ ⭐ | Autonomy controller detects crowdsourced congestion, re-plans around it, and dispatches | `test_autonomy_loop_reacts_to_congestion` | verified |
| ✅ ⭐ | NemoClaw agent ingests data, narrates, and injects a closure (offline-deterministic) | `test_nemo_agent_offline_narrates_and_injects` | verified |
| ✅ ⭐ | GB10 signal agent parses Nemotron JSON and keeps only well-formed recs | `test_ask_nemotron_parses_and_filters` | verified |
| ✅ | GB10 signal agent handles non-JSON model output gracefully | `test_ask_nemotron_handles_non_json` | verified |
| ✅ ⭐ | Box agent answers queued operator questions via local Nemotron | `test_answer_pending_tasks_posts_answer` | verified |
| ✅ ⭐ | Box agent assesses each driver and filters invalid statuses | `test_assess_drivers_parses_and_filters` | verified |

## e2e

| | claim | test | status |
|--|--|--|--|
| ✅ ⭐ | Driver voice assistant routes the FAQ questions to the correct tools | `test_driver_assistant_answers` | verified |
| ✅ ⭐ | Voice NLU parses real clinic phrasings into a valid DeliveryJob (priority, cold-chain, places, time) | `test_stat_cold_chain_pickup_from_to` | verified |
| ✅ ⭐ | bridge_status derives open/closed from live /state disruptions matched to bridge geometry | `test_bridge_status_closed_when_disruption_on_bridge` | verified |
| ✅ ⭐ | Outbound WS handler places a voice call only on voice_call notifications | `test_outbound_places_call_on_voice_notification` | verified |
| ✅ ⭐ | Inbound intake parses text and POSTs a DeliveryJob to the orchestrator | `test_intake_submit_happy` | verified |
| ✅ ⭐ | NemoClaw narration is observable by a client connecting after boot (history replay) | `test_nemoclaw_online_narration` | verified |
| ✅ | Right delivery list renders cards with van/scooter icons (browser e2e) | `test_delivery_list_and_cards` | verified |
| ✅ | Clicking a delivery selects it and opens the inspector (browser e2e) | `test_click_delivery_highlights` | verified |
| ✅ | Landing page is on-brand: mascot mark, Poppins display, Cream surface, Pulse Red CTA -> /login (browser e2e) | `test_landing_is_on_brand` | verified |
| ✅ | Login page is on-brand (Cream/Pulse Red/Poppins) and rejects bad credentials with an inline error (browser e2e) | `test_login_is_on_brand_and_rejects_bad_creds` | verified |
| ✅ ⭐ | Signal recommendations POST/GET round-trip and appear in /state | `test_signals_post_get_roundtrip` | verified |
| ✅ ⭐ | Posted signal recommendations broadcast to the map (WS + narration) | `test_signals_broadcast` | verified |
| ✅ ⭐ | Operator can ask the GB10 agent; question queues, is answered, broadcasts | `test_ask_tasks_answer_flow` | verified |
| ✅ ⭐ | Per-driver assessments round-trip and broadcast to the map | `test_fleet_assessments_roundtrip_and_broadcast` | verified |
| ✅ ⭐ | Redirect a courier (200) re-optimises; unknown courier is 404 | `test_redirect_known_and_unknown` | verified |
| ✅ ⭐ | Closing a road triggers a live re-route and scoreboard update | `test_close_road_reroutes` | verified |
| ✅ ⭐ | A new job produces a voice_call dispatch notification | `test_voice_call_emitted` | verified |
| ✅ ⭐ | Telemetry -> congestion -> re-plan loop works end-to-end over the live stack | `test_telemetry_flywheel_loop` | verified |

## unhappy

| | claim | test | status |
|--|--|--|--|
| ✅ ⭐ | Voice NLU degrades safely on garbage/empty input (never emits an invalid job) | `test_garbage_text_degrades_to_valid_job` | verified |
| ✅ ⭐ | Driver-assistant tools return an error dict (never crash) when the orchestrator is down | `test_all_tools_degrade_when_orchestrator_down` | verified |
| ✅ ⭐ | Driver assistant speaks a safe fallback when a tool errors (no crash, no dead air) | `test_ask_unhappy_tool_error_speaks_safe_fallback` | verified |
| ✅ ⭐ | ElevenLabs wrapper is a safe no-op with no API key (offline-demoable) | `test_elevenlabs_disabled_without_key_is_noop` | verified |
| ✅ ⭐ | A malformed signal recommendation is rejected (422), system stays healthy | `test_signals_malformed_422` | verified |
| ✅ ⭐ | A cold-chain job with no fridge-equipped courier is left unassigned, never mis-assigned | `test_infeasible_cold_job_unassigned_no_crash` | verified |
| ✅ ⭐ | If the routing service is down, the orchestrator still returns a plan (greedy fallback) | `test_routing_down_uses_greedy_fallback` | verified |
| ✅ ⭐ | Malformed job input is rejected (422) and the system stays healthy | `test_malformed_job_is_422_and_system_healthy` | verified |
| ✅ ⭐ | Out-of-bounds / over-speed pings are rejected; valid ones still ingested | `test_bad_pings_rejected_good_accepted` | verified |

## security

| | claim | test | status |
|--|--|--|--|
| ✅ ⭐ | Register -> login returns a JWT and /auth/me works with it | `test_register_then_login_returns_jwt_and_me_works` | verified |
| ✅ ⭐ | With auth on, a protected write requires a valid token (401 without, ok with) | `test_protected_write_with_token_succeeds` | verified |
| ✅ ⭐ | With auth on, a protected write without a token is 401 | `test_protected_write_without_token_returns_401` | verified |
| ✅ ⭐ | Login with the wrong password is rejected (401) | `test_login_with_wrong_password_returns_401` | verified |
| ✅ ⭐ | With auth off (dev/test default), writes work without a token | `test_post_jobs_works_without_token_when_auth_off` | verified |

## completeness

| | claim | test | status |
|--|--|--|--|
| ✅ ⭐ | No unimplemented stubs in source outside the documented GB10 seams | `test_no_notimplemented_outside_allowlist` | verified |
| ✅ ⭐ | Every UI button is wired to a real handler (no dead buttons) | `test_no_unwired_buttons` | verified |
| ✅ ⭐ | Every contract REST endpoint is implemented and reachable | `test_orchestrator_rest_endpoints_implemented` | verified |
| ✅ ⭐ | Every declared WebSocket event is actually emitted (no dead channels) | `test_ws_events_declared_are_emitted` | verified |
