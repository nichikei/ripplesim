"""Capture the README screenshots from a running server.

    python -m uvicorn backend.app:app --port 8123     # in one terminal
    python scripts/screenshots.py                     # in another

Writes PNGs into docs/. Regenerate them whenever the UI changes so the
README never shows a version of the app that no longer exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8123"
OUT_DIR = Path(__file__).resolve().parent.parent / "docs"
VIEWPORT = {"width": 1440, "height": 900}

TOPIC = "City announces free public transport for students"
EVENT = "Auditors reveal a $40M funding gap in the scheme"


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
        page.goto(BASE_URL, wait_until="networkidle")

        # 1. The landing state: hero + composer, before anything has run.
        page.screenshot(path=OUT_DIR / "01-hero.png")
        print("wrote 01-hero.png")

        # 2. A finished run: live feed, charts and metrics side by side.
        page.fill("#topic", TOPIC)
        page.eval_on_selector("#rounds", "el => { el.value = 6; el.dispatchEvent(new Event('input')); }")
        page.eval_on_selector("#n-agents", "el => { el.value = 80; el.dispatchEvent(new Event('input')); }")
        page.click("#run-btn")

        page.wait_for_selector(".post", timeout=60_000)
        page.fill("#event-headline", EVENT)
        page.select_option("#event-impact", "-0.9")
        page.click("#inject-btn")

        page.wait_for_selector("#status-pill.pill-done", timeout=300_000)
        page.wait_for_selector("#report-card:not(.hidden)", timeout=300_000)
        # Scroll past the hero so the feed and the charts fill the frame —
        # that is the part of the app worth showing.
        page.evaluate("document.querySelector('main').scrollIntoView()")
        page.wait_for_timeout(500)
        page.screenshot(path=OUT_DIR / "02-dashboard.png")
        print("wrote 02-dashboard.png")

        # 3. The report the agent produced, full screen.
        page.click("#open-report")
        page.wait_for_selector("#report-modal:not(.hidden)")
        page.wait_for_timeout(400)
        page.screenshot(path=OUT_DIR / "03-report.png")
        print("wrote 03-report.png")
        page.keyboard.press("Escape")  # the panel sits over the backdrop, so don't click it
        # The modal is now hidden, so wait on attachment rather than visibility.
        page.wait_for_selector("#report-modal.hidden", state="attached")

        # 4. Interviewing one of the agents.
        page.evaluate("openChat(state.agents.find(a => Math.abs(a.opinion) > 0.4) || state.agents[0])")
        page.wait_for_selector("#chat-drawer:not(.hidden)")
        page.fill("#chat-input", "Why do you feel that way about this?")
        page.click("#chat-form button")
        try:
            page.wait_for_selector(".chat-msg.agent:not(.typing)", timeout=120_000)
        except Exception:
            print("interview did not answer (no API key?) — capturing anyway")
        page.wait_for_timeout(400)
        page.screenshot(path=OUT_DIR / "04-interview.png")
        print("wrote 04-interview.png")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
