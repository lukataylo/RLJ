"""Real-browser tests for the PulseGo BRAND surfaces — landing (/) + login (/login).

Locks the brand guideline into the public pages so a regression (wrong font, lost
logo, off-brand CTA colour) fails the gate:
  * Pulse Red  #FF3B30  -> rgb(255, 59, 48)   primary CTA background
  * Cream      #FFF6EE  -> rgb(255, 246, 238) page surface
  * Poppins display face on headings
  * the mascot mark (/pulsego.svg) present in nav + hero
Plus a deterministic auth check: a bad-credential sign-in surfaces the error.

Drives the live dev stack at http://localhost:5173; skips cleanly when it isn't up.
"""
from __future__ import annotations
import urllib.request

import pytest

pytestmark = pytest.mark.e2e

ROOT = "http://localhost:5173"
WAIT = 10_000


def _reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:  # noqa: S310 - localhost only
            return 200 <= r.status < 400
    except Exception:  # noqa: BLE001
        return False


if not _reachable(ROOT):
    pytest.skip("live UI stack not running", allow_module_level=True)

from playwright.sync_api import sync_playwright, expect  # noqa: E402

PULSE_RED = "rgb(255, 59, 48)"
CREAM = "rgb(255, 246, 238)"


def _font(page, selector: str) -> str:
    return page.eval_on_selector(selector, "el => getComputedStyle(el).fontFamily")


def _bg(page, selector: str) -> str:
    return page.eval_on_selector(selector, "el => getComputedStyle(el).backgroundColor")


@pytest.fixture()
def page():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 1000})
        pg = ctx.new_page()
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.app_errors = errs  # type: ignore[attr-defined]
        try:
            yield pg
        finally:
            ctx.close()
            b.close()


def test_landing_is_on_brand(page):
    page.goto(ROOT, wait_until="networkidle")
    expect(page.get_by_test_id("landing")).to_be_visible(timeout=WAIT)

    # Mascot mark present in nav + hero, pointing at the brand SVG.
    marks = page.locator('img[src="/pulsego.svg"]')
    assert marks.count() >= 2, "expected mascot mark in nav and hero"

    # Hero accent line (the "why-local" tagline).
    expect(page.locator(".hero-accent")).to_have_text("delays hit.", timeout=WAIT)

    # Poppins display face on the hero headline + wordmark.
    assert "Poppins" in _font(page, ".hero-title"), "hero title is not Poppins"
    assert "Poppins" in _font(page, ".pg-word"), "wordmark is not Poppins"

    # Cream surface + Pulse Red primary CTA.
    assert _bg(page, ".site") == CREAM, f"site surface not cream: {_bg(page, '.site')}"
    assert _bg(page, ".site-btn.primary") == PULSE_RED, "primary CTA is not Pulse Red"

    # Primary CTA routes to the login (no token in a fresh context).
    href = page.get_by_test_id("landing-cta").get_attribute("href")
    assert href and href.endswith("/login"), f"CTA does not route to /login: {href}"

    assert not page.app_errors, f"page errors on landing: {page.app_errors}"  # type: ignore[attr-defined]


def test_login_is_on_brand_and_rejects_bad_creds(page):
    page.goto(f"{ROOT}/login", wait_until="networkidle")
    expect(page.get_by_test_id("login")).to_be_visible(timeout=WAIT)

    # Branded card: Poppins title, Cream surface, Pulse Red submit.
    assert "Poppins" in _font(page, ".auth-title"), "login title is not Poppins"
    assert _bg(page, ".site") == CREAM, "login surface not cream"
    assert _bg(page, ".site-btn.primary") == PULSE_RED, "login button is not Pulse Red"

    # Deterministic auth behaviour: a wrong credential shows the inline error.
    page.get_by_test_id("login-email").fill("nobody@pulsego.test")
    page.get_by_test_id("login-password").fill("definitely-wrong")
    page.get_by_test_id("login-submit").click()
    expect(page.get_by_test_id("login-error")).to_be_visible(timeout=WAIT)
