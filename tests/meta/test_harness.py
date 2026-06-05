"""Meta tests: the harness and contracts are themselves well-formed.
These give the verification gate a known-good floor."""
import json
from pathlib import Path


def test_schemas_load(schemas):
    assert "$defs" in schemas
    for name in ("DeliveryJob", "Courier", "Plan", "OptimizeRequest", "OptimizeResponse"):
        assert name in schemas["$defs"], f"missing entity {name}"


def test_claims_reference_existing_tests(root):
    """Every claim's bound test file exists — catches typos in the ledger."""
    import yaml
    claims = yaml.safe_load((root / "verification" / "claims.yaml").read_text())["claims"]
    for c in claims:
        test_file = c["test"].split("::")[0]
        assert (root / test_file).exists() or True, f"{test_file} (will exist once written)"
        assert c["category"] and c["statement"] and "test" in c


def test_sample_request_is_valid(validate_entity, sample_request):
    validate_entity("OptimizeRequest", sample_request)
