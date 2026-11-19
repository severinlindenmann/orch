"""The one way a Python script in this repository starts a browser (ORCH-615, AGENTS.md section 4).

Every browser gets '--use-mock-keychain' and '--password-store=basic'. Without them macOS shows the person at the
computer a keychain password window ("headless_shell wants to use ... Chromium Safe Storage"). The CI check
scripts/check_headless_launch.py fails any file that calls launch() / launch_persistent_context() itself.

    sys.path.insert(0, "<repo>/e2e"); import headless
    browser = headless.launch(p.chromium, headless=True)
    ctx = headless.launch_persistent(p.chromium, profile_dir, viewport={...})

JavaScript twin: e2e/headless.cjs.
"""

ARGS = ("--use-mock-keychain", "--password-store=basic")


def with_args(opts: dict) -> dict:
    """The launch options with the two keychain options first; the caller's own args follow (no duplicates)."""
    own = [a for a in (opts.get("args") or []) if a not in ARGS]
    return {**opts, "args": [*ARGS, *own]}


def launch(browser_type, **opts):
    return browser_type.launch(**with_args(opts))


def launch_persistent(browser_type, user_data_dir, **opts):
    return browser_type.launch_persistent_context(user_data_dir, **with_args(opts))
