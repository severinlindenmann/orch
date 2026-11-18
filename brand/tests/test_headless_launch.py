"""Every browser start goes through the keychain-safe helper (ORCH-615): planted samples, the helpers, the real repo."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "e2e"))
import check_headless_launch as chl  # noqa: E402
import headless  # noqa: E402

OPTS = "args: ['--use-mock-keychain', '--password-store=basic']"


@pytest.mark.parametrize("rel, text", [
    ("e2e/a.cjs", "const { chromium } = require('playwright');\nconst b = await chromium.launch();\n"),
    ("e2e/b.mjs", "import { chromium } from 'playwright';\nawait chromium.launch({ headless: true });\n"),
    ("e2e/c.cjs", "require('playwright');\nawait chromium.launchPersistentContext(dir, {});\n"),
    ("e2e/d.cjs", "require('playwright');\nawait pw.chromium .launch ({});\n"),
    ("e2e/e.mjs", "import { firefox } from 'playwright';\nawait firefox.launchServer();\n"),
    ("x/f.py", "from playwright.sync_api import sync_playwright\nb = p.chromium.launch()\n"),
    ("x/g.py", "from playwright.sync_api import sync_playwright\nc = p.chromium.launch_persistent_context(d)\n"),
    ("x/h.js", "const puppeteer = require('puppeteer');\nawait puppeteer.launch();\n"),
    # typing the options by hand is not enough: use the helper
    ("e2e/i.cjs", f"require('playwright');\nawait chromium.launch({{{OPTS}}});\n"),
    # Chrome started by hand with --headless and no options
    ("x/j.py", "CHROME = 'chromium'\nargs = [CHROME, '--headless=new', '--screenshot']\n"),
    # a shipped file without the two options
    ("workspace-addons/dashboard/clickthrough/run.cjs", "require('playwright');\nawait chromium.launch();\n"),
])
def test_launch_without_helper_is_caught(rel, text):
    found = chl.problems(rel, text)
    assert found and found[0].startswith(rel + ":2:")


@pytest.mark.parametrize("rel, text", [
    ("e2e/a.cjs", "const headless = require('./headless.cjs');\nawait headless.launch(chromium);\n"),
    ("e2e/b.mjs", "import headless from './headless.cjs';\nawait headless.launchPersistent(chromium, d, {});\n"),
    ("x/c.py", "import headless\nfrom playwright.sync_api import sync_playwright\nb = headless.launch(p.chromium)\n"),
    ("x/d.py", "res = scripts.launch(root)\n"),  # no browser in the file: not a browser start
    ("e2e/headless.cjs", "browserType.launch(withArgs(opts));\n"),  # the helper itself
    ("x/e.py", "CHROME='chromium'\nA = ['--headless=new', '--use-mock-keychain', '--password-store=basic']\n"),
    ("workspace-addons/dashboard/clickthrough/run.cjs", f"require('playwright');\nawait chromium.launch({{{OPTS}}});\n"),
    ("x/f.yml", "chromium.launch()"),  # not a script
])
def test_fine_files_pass(rel, text):
    assert chl.problems(rel, text) == []


def test_repository_has_no_bare_launch():
    assert chl.check(ROOT) == []


def test_python_helper_adds_both_options_first_once():
    seen = {}

    class Fake:
        def launch(self, **kw):
            seen["launch"] = kw

        def launch_persistent_context(self, d, **kw):
            seen["persistent"] = (d, kw)

    headless.launch(Fake(), headless=True, args=["--password-store=basic", "--x"])
    assert seen["launch"] == {"headless": True, "args": ["--use-mock-keychain", "--password-store=basic", "--x"]}
    headless.launch_persistent(Fake(), "/p")
    assert seen["persistent"] == ("/p", {"args": ["--use-mock-keychain", "--password-store=basic"]})


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_js_helper_adds_both_options_first_once():
    js = (
        "const h = require(process.argv[1]); const seen = {};"
        "const fake = { launch: o => { seen.launch = o; }, launchPersistentContext: (d, o) => { seen.p = [d, o]; } };"
        "h.launch(fake, { channel: 'chromium', args: ['--use-mock-keychain', '--y'] }); h.launchPersistent(fake, '/p');"
        "console.log(JSON.stringify(seen));"
    )
    out = subprocess.run(["node", "-e", js, str(ROOT / "e2e" / "headless.cjs")], capture_output=True, text=True,
                         check=True).stdout
    seen = json.loads(out)
    assert seen["launch"] == {"channel": "chromium", "args": ["--use-mock-keychain", "--password-store=basic", "--y"]}
    assert seen["p"] == ["/p", {"args": ["--use-mock-keychain", "--password-store=basic"]}]
