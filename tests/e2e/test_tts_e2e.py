"""Cross-process checks for the NemoClaw TTS proxy without calling ElevenLabs."""
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


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_ready(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
    raise RuntimeError(f"orchestrator at {url} never became ready")


@pytest.fixture(scope="module")
def orchestrator_url():
    port = _free_port()
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = ROOT / ".venv" / "bin" / "python"
    executable = str(py) if py.exists() else sys.executable
    env = {
        **os.environ,
        "ELEVENLABS_API_KEY": "",
        "ROUTING_URL": "http://127.0.0.1:1",
    }
    proc = subprocess.Popen(
        [
            executable,
            "-m",
            "uvicorn",
            "app:app",
            "--app-dir",
            "orchestrator",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_ready(f"{base}/state")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_tts_requires_configuration(orchestrator_url):
    response = httpx.post(
        f"{orchestrator_url}/tts",
        json={"text": "NemoClaw voice check"},
        timeout=5,
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


@pytest.mark.parametrize("text", ["", " ", "x" * 501])
def test_tts_rejects_invalid_text(orchestrator_url, text):
    response = httpx.post(
        f"{orchestrator_url}/tts",
        json={"text": text},
        timeout=5,
    )
    assert response.status_code == 422
