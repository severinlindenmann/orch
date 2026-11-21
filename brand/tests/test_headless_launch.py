"""Every browser start goes through the keychain-safe helper (ORCH-615) and never gets a profile folder (ORCH-1101):
planted samples, the helpers, the real repo."""

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
    ("e2e/d.cjs", "require('playwright');\nawait pw.chromium .launch ({});\n"),
    ("e2e/e.mjs", "import { firefox } from 'playwright';\nawait firefox.launchServer();\n"),
    ("x/f.py", "from playwright.sync_api import sync_playwright\nb = p.chromium.launch()\n"),
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
    ("x/c.py", "import headless\nfrom playwright.sync_api import sync_playwright\nb = headless.launch(p.chromium)\n"),
    ("x/d.py", "res = scripts.launch(root)\n"),  # no browser in the file: not a browser start
    ("e2e/headless.cjs", "browserType.launch(withArgs(opts));\n"),  # the helper itself
    ("x/e.py", "CHROME='chromium'\nA = ['--headless=new', '--use-mock-keychain', '--password-store=basic']\n"),
    ("workspace-addons/dashboard/clickthrough/run.cjs", f"require('playwright');\nawait chromium.launch({{{OPTS}}});\n"),
    ("x/f.yml", "chromium.launch()"),  # not a script
])
def test_fine_files_pass(rel, text):
    assert chl.problems(rel, text) == []


# ORCH-1101: a profile folder makes the headless shell ask the macOS keychain, mock keychain option or not
@pytest.mark.parametrize("rel, text", [
    ("e2e/c.cjs", "require('playwright');\nawait chromium.launchPersistentContext(dir, {});\n"),
    ("x/g.py", "from playwright.sync_api import sync_playwright\nc = p.chromium.launch_persistent_context(d)\n"),
    ("e2e/b.mjs", "import headless from './headless.cjs';\nawait headless.launchPersistent(chromium, d, {});\n"),
    ("x/k.py", "import headless  # playwright\nheadless.launch_persistent(p.chromium, d)\n"),
    ("e2e/l.cjs", "const h = require('./headless.cjs'); // chromium\nawait h.launch(chromium, { userDataDir: d });\n"),
    ("x/m.py", "import headless  # chromium\nb = headless.launch(p.chromium, user_data_dir=d)\n"),
    ("x/n.py", "CHROME = 'chromium'\nA = [CHROME, '--use-mock-keychain', '--password-store=basic', f'--user-data-dir={d}']\n"),
    ("scripts/o.sh", "C=chrome-headless-shell  # chromium\n\"$C\" --use-mock-keychain --user-data-dir=\"$P\" --screenshot\n"),
    # the two keychain options do not make a profile folder safe
    ("e2e/p.cjs", f"require('playwright');\nawait chromium.launchPersistentContext(d, {{{OPTS}}});\n"),
])
def test_profile_folder_is_refused(rel, text):
    found = chl.problems(rel, text)
    assert found and found[0].startswith(rel + ":2:") and "profile folder" in found[0]


def test_only_the_full_chrome_screenshot_may_name_a_profile_folder():
    text = "CHROME = 'chromium'\nA = ['--headless=new', '--use-mock-keychain', '--password-store=basic', '--user-data-dir=/p']\n"
    assert chl.problems("workspace/src/orch/cli_shot.py", text) == []
    assert chl.problems("workspace/src/orch/other.py", text)


def test_helpers_offer_no_profile_folder():
    assert not hasattr(headless, "launch_persistent")
    for name in ("headless.cjs", "headless.py"):
        code = (ROOT / "e2e" / name).read_text().split("ARGS = ", 1)[1]  # below the header comment
        assert not chl.PROFILE.search(code), name


def test_repository_has_no_bare_launch():
    assert chl.check(ROOT) == []


def test_python_helper_adds_both_options_first_once():
    seen = {}

    class Fake:
        def launch(self, **kw):
            seen["launch"] = kw

    headless.launch(Fake(), headless=True, args=["--password-store=basic", "--x"])
    assert seen["launch"] == {"headless": True, "args": ["--use-mock-keychain", "--password-store=basic", "--x"]}


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_js_helper_adds_both_options_first_once():
    js = (
        "const h = require(process.argv[1]); const seen = {};"
        "const fake = { launch: o => { seen.launch = o; } };"
        "h.launch(fake, { channel: 'chromium', args: ['--use-mock-keychain', '--y'] });"
        "seen.persistent = typeof h.launchPersistent; console.log(JSON.stringify(seen));"
    )
    out = subprocess.run(["node", "-e", js, str(ROOT / "e2e" / "headless.cjs")], capture_output=True, text=True,
                         check=True).stdout
    seen = json.loads(out)
    assert seen["launch"] == {"channel": "chromium", "args": ["--use-mock-keychain", "--password-store=basic", "--y"]}
    assert seen["persistent"] == "undefined"
