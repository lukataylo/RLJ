"""Real-browser tests against the LIVE dev stack (Vite UI + orchestrator).

These are NOT self-booted: they drive whatever is already running at
http://localhost:5173 (frontend) and http://localhost:8000 (orchestrator). In the
hackspace those dev servers are up, so these run; in CI they're not, so the whole
module skips cleanly.

Uses the sync Playwright API directly (own browser/page fixtures) so it doesn't
depend on pytest-playwright's CLI options. All locator/expect waits are bounded to
~10s so nothing hangs.
"""
from __future__ import annotations
import urllib.request

import pytest

pytestmark = pytest.mark.e2e

UI_URL = "http://127.0.0.1:5173/app"  # explicit loopback avoids localhost proxy/IPv6 ambiguity
ORCH_HEALTH = "http://127.0.0.1:8000/state"
WAIT = 10_000  # ms — bounded locator/expect timeout


def _reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:  # noqa: S310 - localhost only
            return 200 <= r.status < 400
    except Exception:  # noqa: BLE001
        return False


if not (_reachable(UI_URL) and _reachable(ORCH_HEALTH)):
    pytest.skip("live UI stack not running", allow_module_level=True)

from playwright.sync_api import sync_playwright, expect  # noqa: E402


# Console messages we treat as benign noise (not app errors).
_BENIGN = ("favicon", "mapbox", "telemetry", "events.mapbox.com", "ERR_BLOCKED")


def _is_app_error(kind: str, text: str) -> bool:
    low = text.lower()
    return not any(b.lower() in low for b in _BENIGN)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            yield b
        finally:
            b.close()


@pytest.fixture()
def page(browser):
    """Fresh context + page, with console/page errors captured into page.app_errors."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    errors: list[tuple[str, str]] = []
    pg.on("console", lambda m: errors.append((m.type, m.text)) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(("pageerror", str(e))))
    pg.app_errors = errors  # type: ignore[attr-defined]
    pg.goto(UI_URL, wait_until="domcontentloaded")
    try:
        yield pg
    finally:
        ctx.close()


def test_delivery_list_and_cards(page):
    """The right delivery list is visible with >=1 card, and every visible card
    carries a vehicle <svg> icon (van/scooter/bike)."""
    expect(page.get_by_test_id("delivery-list")).to_be_visible(timeout=WAIT)

    cards = page.get_by_test_id("delivery-card")
    expect(cards.first).to_be_visible(timeout=WAIT)
    n = cards.count()
    assert n >= 1, "delivery list rendered no cards"

    for i in range(n):
        card = cards.nth(i)
        if not card.is_visible():
            continue
        assert card.locator("svg").count() >= 1, f"card {i} has no vehicle svg icon"


def test_click_delivery_highlights(page):
    """Clicking a delivery card selects it (aria-pressed/selected class) AND opens
    the Inspector on that courier's detail view. The fleet-overview default was
    removed, so the Inspector is absent until a courier is selected."""
    expect(page.get_by_test_id("delivery-list")).to_be_visible(timeout=WAIT)
    inspector = page.get_by_test_id("inspector")
    # No selection yet -> inspector is not rendered (no fleet-overview segment).
    expect(inspector).to_have_count(0)

    cards = page.get_by_test_id("delivery-card")
    expect(cards.first).to_be_visible(timeout=WAIT)
    card = cards.first
    courier_id = card.get_attribute("data-courier")
    assert courier_id, "delivery card missing data-courier"

    card.click()

    # 1) the card gains a selected state
    expect(card).to_have_attribute("aria-pressed", "true", timeout=WAIT)
    klass = card.get_attribute("class") or ""
    assert "selected" in klass, f"clicked card did not get .selected class: {klass!r}"

    # 2) the inspector now appears with that courier's live detail.
    expect(inspector).to_be_visible(timeout=WAIT)
    after = inspector.inner_text()
    assert after.strip(), "inspector did not populate after selection"


def test_nemoclaw_feed_live(page):
    """The NemoClaw feed is visible and shows >=1 live log line."""
    feed = page.get_by_test_id("nemoclaw-feed")
    expect(feed).to_be_visible(timeout=WAIT)
    expect(feed.locator(".nemo-line").first).to_be_visible(timeout=WAIT)
    assert feed.locator(".nemo-line").count() >= 1, "nemoclaw feed has no log lines"


def test_agent_decision_card_reroute(page):
    """Asking NemoClaw to reroute a specific courier renders a styled answer plus a Yes/No
    decision card; clicking Yes executes the redirect against the orchestrator and the
    card resolves to its done state (no console errors)."""
    expect(page.get_by_test_id("delivery-list")).to_be_visible(timeout=WAIT)
    card = page.get_by_test_id("delivery-card").first
    expect(card).to_be_visible(timeout=WAIT)
    courier_id = card.get_attribute("data-courier")
    assert courier_id, "delivery card missing data-courier"

    page.get_by_test_id("ask-input").fill(f"reroute courier {courier_id} around congestion")
    page.get_by_test_id("ask-send").click()

    # The answer renders in its Markdown container, and a decision card is offered.
    expect(page.get_by_test_id("agent-answer").first).to_be_visible(timeout=WAIT)
    decision = page.get_by_test_id("decision-card").first
    expect(decision).to_be_visible(timeout=WAIT)
    expect(page.get_by_test_id("decision-yes").first).to_be_visible(timeout=WAIT)

    page.get_by_test_id("decision-yes").first.click()
    # Yes hit /couriers/{id}/redirect; the card resolves to its done state.
    expect(page.locator(".nemo-decision.done").first).to_be_visible(timeout=WAIT)

    app_errors = [e for e in page.app_errors if _is_app_error(*e)]
    assert not app_errors, f"console errors after decision: {app_errors}"


def test_nemoclaw_inline_microphone_submits_transcript(page):
    """A browser SpeechRecognition final result fills and submits the NemoClaw input."""
    page.add_init_script(
        """
        class MockSpeechRecognition {
          constructor() {
            this.lang = "";
            this.interimResults = false;
            this.continuous = false;
            this.maxAlternatives = 1;
          }
          start() {
            setTimeout(() => {
              const result = [{ transcript: "How many routes are active?" }];
              result.isFinal = true;
              this.onresult?.({ resultIndex: 0, results: [result] });
              this.onend?.();
            }, 20);
          }
          stop() { this.onend?.(); }
          abort() { this.onend?.(); }
        }
        window.SpeechRecognition = MockSpeechRecognition;
        window.webkitSpeechRecognition = MockSpeechRecognition;
        """
    )
    page.route(
        "**/agent/ask",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"id":"task-mic","question":"How many routes are active?",'
                 '"ts":"2026-06-06T12:00:00Z","status":"pending"}',
        ),
    )
    page.route(
        "**/tts",
        lambda route: route.fulfill(
            status=503,
            content_type="application/json",
            body='{"detail":"test fallback"}',
        ),
    )
    page.reload(wait_until="domcontentloaded")

    with page.expect_request("**/agent/ask", timeout=WAIT) as request_info:
        page.get_by_test_id("ask-mic").click()

    assert request_info.value.post_data_json == {
        "question": "How many routes are active?"
    }

    with page.expect_request("**/tts", timeout=WAIT) as tts_request:
        answer = page.request.post(
            "http://127.0.0.1:8000/agent/answer",
            data={"task_id": "task-mic", "answer": "Three routes are active."},
        )
        assert answer.ok, answer.text()

    assert tts_request.value.post_data_json == {"text": "Three routes are active."}


def test_no_console_errors(page):
    """No app-level console/page errors on load or after interacting (benign
    mapbox telemetry + favicon 404 are filtered out)."""
    expect(page.get_by_test_id("delivery-list")).to_be_visible(timeout=WAIT)

    cards = page.get_by_test_id("delivery-card")
    if cards.count():
        cards.first.click()
        page.wait_for_timeout(500)

    bad = [(k, t) for (k, t) in page.app_errors if _is_app_error(k, t)]  # type: ignore[attr-defined]
    assert not bad, "console/page errors detected:\n" + "\n".join(f"  [{k}] {t}" for k, t in bad)
