"""Real-browser test for the LiDAR 3D toggle on the command center.

Drives the live dev stack: switches between the operations Map and the 3D LiDAR
city twin, asserts a WebGL <canvas> renders for the LiDAR view, and that the toggle
is a real round-trip (map -> lidar -> map) with no app-level console/page errors.
Captures screenshots of both views to /tmp for visual confirmation.

Skips cleanly when the live UI stack isn't running (e.g. CI).
"""
from __future__ import annotations
import urllib.request

import pytest

pytestmark = pytest.mark.e2e

APP_URL = "http://localhost:5173/app"
UI_ROOT = "http://localhost:5173"
WAIT = 15_000  # ms — point-cloud fetch (36MB) + GPU upload can be slow


def _reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:  # noqa: S310 - localhost only
            return 200 <= r.status < 400
    except Exception:  # noqa: BLE001
        return False


if not _reachable(UI_ROOT):
    pytest.skip("live UI stack not running", allow_module_level=True)

from playwright.sync_api import sync_playwright, expect  # noqa: E402

_BENIGN = ("favicon", "mapbox", "telemetry", "events.mapbox.com", "ERR_BLOCKED", "websocket")


def _is_app_error(text: str) -> bool:
    low = text.lower()
    return not any(b in low for b in _BENIGN)


def test_lidar_toggle_round_trip():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=1,
        )
        pg = ctx.new_page()
        errors: list[str] = []
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        try:
            pg.goto(APP_URL, wait_until="domcontentloaded")

            # Both toggle buttons present; Map active by default.
            map_btn = pg.get_by_test_id("view-toggle-map")
            lidar_btn = pg.get_by_test_id("view-toggle-lidar")
            expect(map_btn).to_be_visible(timeout=WAIT)
            expect(lidar_btn).to_be_visible(timeout=WAIT)
            pg.wait_for_timeout(1500)
            pg.screenshot(path="/tmp/lidar_view_map.png")

            # Switch to LiDAR -> a WebGL canvas must mount and stay.
            lidar_btn.click()
            canvas = pg.locator("canvas")
            expect(canvas.first).to_be_visible(timeout=WAIT)
            # Give the point cloud time to fetch + render.
            pg.wait_for_timeout(4000)
            box = canvas.first.bounding_box()
            assert box and box["width"] > 200 and box["height"] > 200, "lidar canvas too small / not rendered"
            pg.screenshot(path="/tmp/lidar_view_lidar.png")

            # Round-trip back to the map.
            map_btn.click()
            pg.wait_for_timeout(800)
            expect(pg.get_by_test_id("delivery-list")).to_be_visible(timeout=WAIT)

            app_errors = [e for e in errors if _is_app_error(e)]
            assert not app_errors, f"app console/page errors during toggle: {app_errors}"
        finally:
            ctx.close()
            browser.close()
