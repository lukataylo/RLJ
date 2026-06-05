"""Contract conformance: everything the routing service accepts/emits must validate
against contracts/schemas.json. These bind the cross-stream integration claims."""
from __future__ import annotations


def test_plan_validates(validate_entity, sample_request, routing_client):
    """The Plan returned by /optimize conforms to the shared schema."""
    r = routing_client.post("/optimize", json=sample_request)
    assert r.status_code == 200, r.text
    body = r.json()
    validate_entity("OptimizeResponse", body)
    validate_entity("Plan", body["plan"])
    # objective is fully populated
    obj = body["plan"]["objective"]
    assert obj["solver"]
    assert obj["windows_total"] >= obj["windows_met"] >= 0


def test_job_roundtrip_validates(validate_entity, sample_request, routing_client):
    """Each accepted DeliveryJob is schema-valid, and every Stop the plan emits both
    validates and references a real job id (no fabricated stops)."""
    for job in sample_request["jobs"]:
        validate_entity("DeliveryJob", job)

    plan = routing_client.post("/optimize", json=sample_request).json()["plan"]
    job_ids = {j["id"] for j in sample_request["jobs"]}
    seen_dropoffs = set()
    for route in plan["routes"]:
        validate_entity("Route", route)
        for stop in route["stops"]:
            validate_entity("Stop", stop)
            assert stop["job_id"] in job_ids, f"stop references unknown job {stop['job_id']}"
            if stop["kind"] == "dropoff":
                seen_dropoffs.add(stop["job_id"])
    # every served job has both a pickup and a dropoff (PDPTW integrity)
    for route in plan["routes"]:
        kinds = {}
        for s in route["stops"]:
            kinds.setdefault(s["job_id"], set()).add(s["kind"])
        for jid, ks in kinds.items():
            assert ks == {"pickup", "dropoff"}, f"job {jid} has unbalanced stops {ks}"


def test_optimize_endpoint_contract(routing_client, sample_request, validate_entity):
    """/healthz advertises a solver; /optimize honours the request/response contract;
    malformed requests are rejected rather than silently mis-served."""
    h = routing_client.get("/healthz")
    assert h.status_code == 200
    assert "solver" in h.json()

    # missing required `couriers` -> 422 (FastAPI validation), never a 200 with garbage
    bad = routing_client.post("/optimize", json={"jobs": []})
    assert bad.status_code == 422

    # empty-but-valid request -> valid (empty) plan, not a crash
    empty = routing_client.post("/optimize", json={"jobs": [], "couriers": []})
    assert empty.status_code == 200
    validate_entity("OptimizeResponse", empty.json())

    ok = routing_client.post("/optimize", json=sample_request)
    assert ok.status_code == 200
    validate_entity("OptimizeResponse", ok.json())
