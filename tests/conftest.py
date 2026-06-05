"""Shared fixtures for the external verification suites."""
from __future__ import annotations
import json, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# make the stream packages importable
for p in ("orchestrator", "routing"):
    sys.path.insert(0, str(ROOT / p))


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def schemas() -> dict:
    return json.loads((ROOT / "contracts" / "schemas.json").read_text())


@pytest.fixture(scope="session")
def validate_entity(schemas):
    """Return validate(name, instance): raises jsonschema.ValidationError if the
    instance does not conform to $defs/<name> in contracts/schemas.json."""
    from jsonschema import Draft202012Validator

    defs = schemas["$defs"]

    def _validate(name: str, instance) -> None:
        validator = Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": defs})
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.path)
        if errors:
            msg = "\n".join(f"  - {list(e.path)}: {e.message}" for e in errors[:10])
            raise AssertionError(f"{name} failed schema validation:\n{msg}")

    return _validate


@pytest.fixture(scope="session")
def sample_request() -> dict:
    return json.loads((ROOT / "contracts" / "samples" / "optimize_request.json").read_text())


@pytest.fixture()
def routing_client():
    """In-process HTTP client over the routing FastAPI app (no port needed)."""
    from fastapi.testclient import TestClient
    import importlib
    app_mod = importlib.import_module("app")  # routing/app.py (on sys.path)
    return TestClient(app_mod.app)
