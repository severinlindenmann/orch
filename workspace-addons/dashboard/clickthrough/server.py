"""Seeded demo workspace + the REAL dashboard server with working actions, for the dashboard click-throughs.

    python workspace-addons/dashboard/clickthrough/server.py <dir> <port>

Run from the workspace environment (`uv run --project workspace`) inside `env -i` with HOME, USERPROFILE and
ORCH_HOME under <dir> and ORCH_HOME_STRICT=1 (clickthrough/run.cjs does that), so the orch of this computer is
never touched. It makes a workspace in <dir>/Pilatus through this checkout's own orch commands (tickets, steps,
evidence, a question, a ticket in Review), then serves it with orch_dashboard.server.make_server and
orch_bin=SELF: every click in the page runs the real `python -I -m orch` and writes the real ticket files, so a
reload shows what really happened.

Prints `ready <base url>` once it listens. Every line `token` on stdin prints `token <one-time sign-in token>`
(a browser context signs in with <base>/#launch=<token>). Writes only under <dir>.
"""

import json
import os
import pwd
import re
import subprocess
import sys
import threading
from pathlib import Path

D, PORT = Path(sys.argv[1]).resolve(), int(sys.argv[2])
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "workspace-addons" / "dashboard" / "src"))

ACCOUNT = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()  # the real account home, not the temp HOME
if not str(D).startswith(str(ACCOUNT / ".orch-test") + os.sep) or os.environ.get("ORCH_HOME_STRICT") != "1":
    sys.exit("server.py runs only in a throw-away home under ~/.orch-test with ORCH_HOME_STRICT=1")

WS = D / "Pilatus"
WS.mkdir(parents=True, exist_ok=True)


def orch(*args: str, stdin: str | None = None) -> dict | str:
    """One orch command in the demo workspace (this Python, isolated mode). Returns parsed --json output."""
    r = subprocess.run(
        [sys.executable, "-I", "-m", "orch", *args],
        cwd=WS,
        input=stdin if stdin is not None else "",
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0:
        sys.exit(f"seed failed: orch {' '.join(args[:3])}: {r.stdout[-400:]} {r.stderr[-400:]}")
    try:
        return json.loads(r.stdout)
    except ValueError:
        return r.stdout


def seed() -> dict:
    """A small, realistic workspace: one ticket per state a person meets on the dashboard."""
    orch("init")
    # The helper is a stand-in script, never a real agent tool: a click on Start runs it, it writes one log line
    # and ends. Nothing here may start a model, spend money or reach outside this computer.
    fake = D / "fake-agent.sh"
    fake.write_text('#!/bin/sh\necho "$(date) $*" >> "$(dirname "$0")/fake-agent.log"\nsleep 2\n')
    fake.chmod(0o755)
    cfg = WS / ".orch" / "config.toml"
    text = re.sub(r"(?m)^agent = .*\n", "", cfg.read_text() if cfg.exists() else "")  # init's own pick goes
    text = text.replace("[workspace]\n", '[workspace]\nagent = "standin"\n', 1) if "[workspace]\n" in text else (
        text + '\n[workspace]\nagent = "standin"\n'
    )
    cfg.write_text(text + f'\n[agents.standin]\nadapter = "generic"\ncommand = "sh {fake} {{prompt}}"\n')
    ids = {}

    def new(key: str, title: str, *steps: str) -> str:
        t = orch("ticket", "new", title, "--json")
        tid = t["id"] if isinstance(t, dict) else str(t).split()[-1]
        ids[key] = tid
        for s in steps:
            orch("check", "add", tid, s)
        return tid

    lunch = new("lunch", "Plan the team lunch", "Collect who comes", "Pick the restaurant", "Send the invite")
    orch("ticket", "status", lunch, "active")
    orch("check", "done", lunch, "c1", "--summary", "Nine of twelve come; two eat vegetarian.", "--note", "Asked in the team chat.")
    orch("ask", lunch, "Which restaurant?", "--option", "Pilatus Stube", "--option", "Seehaus", "--recommend", "Seehaus")
    menu = new("menu", "Send the menu to the team", "Write the menu text")
    orch("ticket", "status", menu, "active")
    orch("check", "done", menu, "c1", "--summary", "Menu written, three dishes.", "--note", "Short text, plain words.")
    orch("ticket", "summary", menu, "Menu text is written and ready to send.")
    orch("ticket", "status", menu, "done")
    new("table", "Book a table for Friday", "Call the restaurant", "Confirm the time")
    new("budget", "Ask finance for the lunch budget")
    return ids


IDS = seed()
(D / "seed.json").write_text(json.dumps(IDS))

from orch import pagelaunch  # noqa: E402
from orch.pagesession import SELF  # noqa: E402
from orch_dashboard.server import make_server  # noqa: E402

srv = make_server(WS, PORT, orch_bin=SELF)
print(f"ready http://127.0.0.1:{PORT} {json.dumps(IDS)}", flush=True)


def tokens() -> None:
    for line in sys.stdin:
        if line.strip() == "token":
            print(f"token {pagelaunch.write_launch_token(WS, 'dashboard')}", flush=True)


threading.Thread(target=tokens, daemon=True).start()
srv.serve_forever()
