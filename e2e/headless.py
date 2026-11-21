"""The one way a Python script in this repository starts a browser (ORCH-615, AGENTS.md section 4).

Every browser gets '--use-mock-keychain' and '--password-store=basic'. Without them macOS shows the person at the
computer a keychain password window ("headless_shell wants to use ... Chromium Safe Storage"). The CI check
scripts/check_headless_launch.py fails any file that calls launch() itself.

Never a profile folder (launch_persistent_context, user_data_dir, --user-data-dir; ORCH-1101): the headless shell
ignores '--use-mock-keychain' once it keeps a profile on disk, fetches the cookie key from the login keychain and
macOS asks the owner for his password. A context from launch() + new_context() keeps cookies in memory and never
asks. A sign-in that must survive between runs goes in a storage_state file: new_context(storage_state=file).

    sys.path.insert(0, "<repo>/e2e"); import headless
    browser = headless.launch(p.chromium, headless=True)
    ctx = browser.new_context(viewport={...}, accept_downloads=True)

JavaScript twin: e2e/headless.cjs.
"""

ARGS = ("--use-mock-keychain", "--password-store=basic")


def with_args(opts: dict) -> dict:
    """The launch options with the two keychain options first; the caller's own args follow (no duplicates)."""
    own = [a for a in (opts.get("args") or []) if a not in ARGS]
    return {**opts, "args": [*ARGS, *own]}


def launch(browser_type, **opts):
    return browser_type.launch(**with_args(opts))
