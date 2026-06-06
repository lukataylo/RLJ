"""End-to-end tests for the orchestrator auth layer (email+password -> JWT).

Each test boots the *real* orchestrator as a subprocess on a fresh port with a throwaway
SQLite DATABASE_URL (a tmp file), so it never touches dev data and each env is isolated.

Two stacks are exercised:
  * auth_on_stack  — AUTH_REQUIRED=true + a seeded admin: proves login/JWT/me work and that
                     write endpoints are protected (401 without token, 200 with token).
  * auth_off_stack — AUTH_REQUIRED unset (default off): proves backward-compat — the existing
                     ~104-test gate POSTs without a token and must still succeed.

Only the orchestrator is started; POST /jobs falls back to the built-in greedy router when
no routing service is present, so the stack is self-sufficient.
"""
from __future__ import annotations
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parent.parent.parent

ADMIN_EMAIL = "admin@pulsego.test"
ADMIN_PASSWORD = "admin-pw-12345"
DISPATCHER_EMAIL = "dispatcher@pulsego.test"
DISPATCHER_PASSWORD = "dispatcher-pw-12345"

# A minimal-but-valid DeliveryJob payload for the protected POST /jobs checks.
JOB_PAYLOAD = {
    "type": "med_delivery",
    "origin": {"lat": 51.5007, "lng": -0.1246, "name": "St Thomas'"},
    "destination": {"lat": 51.5246, "lng": -0.1340, "name": "UCLH"},
    "priority": "urgent",
}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_health(url: str, timeout: float = 30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=1.0).status_code == 200:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)
    raise RuntimeError(f"service at {url} never became healthy")


def _boot_orchestrator(env_extra: dict, db_path: Path):
    port = _free_port()
    venv_python = str(ROOT / ".venv" / "bin" / "python")
    py = venv_python if Path(venv_python).exists() else sys.executable
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "JWT_SECRET": "test-secret-not-for-prod",
        **env_extra,
    }
    proc = subprocess.Popen(
        [py, "-m", "uvicorn", "app:app", "--app-dir", "orchestrator", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_health(f"{base}/healthz")
    except Exception:
        proc.terminate()
        raise
    return proc, base


def _teardown(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        proc.kill()


@pytest.fixture(scope="module")
def auth_on_stack(tmp_path_factory):
    """Orchestrator with AUTH_REQUIRED=true and a seeded admin user."""
    db_path = tmp_path_factory.mktemp("auth_on") / "auth_on.db"
    proc, base = _boot_orchestrator(
        {"AUTH_REQUIRED": "true", "ADMIN_EMAIL": ADMIN_EMAIL, "ADMIN_PASSWORD": ADMIN_PASSWORD},
        db_path,
    )
    try:
        yield base
    finally:
        _teardown(proc)


@pytest.fixture(scope="module")
def auth_off_stack(tmp_path_factory):
    """Orchestrator with AUTH_REQUIRED unset (default off) — backward-compat mode."""
    db_path = tmp_path_factory.mktemp("auth_off") / "auth_off.db"
    proc, base = _boot_orchestrator({}, db_path)
    try:
        yield base
    finally:
        _teardown(proc)


def _admin_token(base: str) -> str:
    r = httpx.post(f"{base}/auth/login",
                   json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def dispatcher_token(auth_on_stack) -> str:
    """Register a dispatcher (admin-only when auth is on), then log in as that dispatcher."""
    base = auth_on_stack
    admin = _admin_token(base)
    httpx.post(f"{base}/auth/register",
               json={"email": DISPATCHER_EMAIL, "password": DISPATCHER_PASSWORD,
                     "role": "dispatcher"},
               headers={"Authorization": f"Bearer {admin}"}, timeout=10)
    r = httpx.post(f"{base}/auth/login",
                   json={"email": DISPATCHER_EMAIL, "password": DISPATCHER_PASSWORD}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# --------------------------------------------------------------------------- auth ON
def test_register_then_login_returns_jwt_and_me_works(auth_on_stack):
    base = auth_on_stack
    admin = _admin_token(base)

    # admin registers a brand-new user
    reg = httpx.post(f"{base}/auth/register",
                     json={"email": "newbie@pulsego.test", "password": "newbie-pw-12345",
                           "role": "dispatcher"},
                     headers={"Authorization": f"Bearer {admin}"}, timeout=10)
    assert reg.status_code == 200, reg.text
    assert reg.json()["email"] == "newbie@pulsego.test"
    assert reg.json()["role"] == "dispatcher"

    # that user can log in and receives a JWT
    login = httpx.post(f"{base}/auth/login",
                       json={"email": "newbie@pulsego.test", "password": "newbie-pw-12345"},
                       timeout=10)
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "dispatcher"
    token = body["access_token"]
    assert isinstance(token, str) and token.count(".") == 2  # looks like a JWT

    # /auth/me with the token returns the current user
    me = httpx.get(f"{base}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "newbie@pulsego.test"


def test_login_with_wrong_password_returns_401(auth_on_stack):
    base = auth_on_stack
    r = httpx.post(f"{base}/auth/login",
                   json={"email": ADMIN_EMAIL, "password": "totally-wrong"}, timeout=10)
    assert r.status_code == 401, r.text


def test_me_without_token_returns_401(auth_on_stack):
    base = auth_on_stack
    r = httpx.get(f"{base}/auth/me", timeout=10)
    assert r.status_code == 401, r.text


def test_protected_write_without_token_returns_401(auth_on_stack):
    base = auth_on_stack
    r = httpx.post(f"{base}/jobs", json=JOB_PAYLOAD, timeout=10)
    assert r.status_code == 401, r.text


def test_protected_write_with_token_succeeds(auth_on_stack, dispatcher_token):
    base = auth_on_stack
    r = httpx.post(f"{base}/jobs", json=JOB_PAYLOAD,
                   headers={"Authorization": f"Bearer {dispatcher_token}"}, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "med_delivery"


def test_register_without_admin_token_forbidden_when_auth_on(auth_on_stack):
    base = auth_on_stack
    r = httpx.post(f"{base}/auth/register",
                   json={"email": "noauth@pulsego.test", "password": "x-pw-12345"}, timeout=10)
    # no Bearer token at all -> 401 from require_user before the admin-role check
    assert r.status_code == 401, r.text


# --------------------------------------------------------------------------- auth OFF
def test_post_jobs_works_without_token_when_auth_off(auth_off_stack):
    """Backward-compat: with AUTH_REQUIRED off (the default), a protected write succeeds
    with NO token — exactly how the existing ~104-test suite calls it."""
    base = auth_off_stack
    r = httpx.post(f"{base}/jobs", json=JOB_PAYLOAD, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "med_delivery"


def test_get_reads_open_when_auth_off(auth_off_stack):
    base = auth_off_stack
    assert httpx.get(f"{base}/jobs", timeout=10).status_code == 200
    assert httpx.get(f"{base}/state", timeout=10).status_code == 200
    assert httpx.get(f"{base}/healthz", timeout=10).status_code == 200
