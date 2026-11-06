"""Screenshots of every harness scenario: `uv run --with playwright python shoot.py <harness-url> <out-dir> [tag]`.

Per scenario: the Overview page at 1440 and 720 wide (full page), one hover shot at 1440 on the busiest
node, and the 390 px list for S2 and S3.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE, OUT = sys.argv[1].rstrip("/"), Path(sys.argv[2])
TAG = sys.argv[3] if len(sys.argv) > 3 else "after"
OUT.mkdir(parents=True, exist_ok=True)
SCENARIOS = ["empty", "s1", "s2", "s3", "s4", "s5"]


def open_scenario(page, key):
    page.goto(f"{BASE}/s/{key}")
    page.wait_for_url("**/admin#overview")
    page.wait_for_selector("main h1")
    page.wait_for_timeout(400)


with sync_playwright() as p:
    browser = p.chromium.launch()
    for key in SCENARIOS:
        for width in (1440, 720):
            ctx = browser.new_context(viewport={"width": width, "height": 900}, color_scheme="dark",
                                      reduced_motion="reduce")
            page = ctx.new_page()
            open_scenario(page, key)
            page.screenshot(path=OUT / f"{TAG}-{key}-{width}.png", full_page=True)
            if width == 1440 and key != "empty":
                node = page.locator(".network .graph-node").first
                if node.count():
                    node.hover()
                    page.wait_for_timeout(250)
                    page.locator(".network").screenshot(path=OUT / f"{TAG}-{key}-{width}-hover.png")
                    node.focus()
                    page.wait_for_timeout(250)
                    page.locator(".network").screenshot(path=OUT / f"{TAG}-{key}-{width}-focus.png")
            ctx.close()
        if key in ("s2", "s3"):
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark",
                                      reduced_motion="reduce", device_scale_factor=2)
            page = ctx.new_page()
            open_scenario(page, key)
            page.screenshot(path=OUT / f"{TAG}-{key}-390.png", full_page=True)
            ctx.close()
    browser.close()
print("shots in", OUT)
