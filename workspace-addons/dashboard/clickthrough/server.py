"""Seeded demo workspace + the REAL dashboard server with working actions, for the dashboard click-throughs.

    python workspace-addons/dashboard/clickthrough/server.py <dir> <port>

Run from the workspace environment (`uv run --project workspace`) inside `env -i` with HOME, USERPROFILE and
ORCH_HOME under <dir> and ORCH_HOME_STRICT=1 (clickthrough/run.cjs does that), so the orch of this computer is
never touched. It makes a workspace in <dir>/Pilatus through this checkout's own orch commands (tickets, steps,
evidence, a question, a ticket in Review), then serves it with orch_dashboard.server.make_server and
orch_bin=SELF: every click in the page runs the real `python -I -m orch` and writes the real ticket files, so a
reload shows what really happened.

Prints `ready <base url>` once it listens. Every line `token` on stdin prints `token <one-time sign-in token>`
(a browser context signs in with <base>/#launch=<token>); `forget-update-info` drops the cached newest version. Writes only under <dir>.
"""

import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

D, PORT = Path(sys.argv[1]).resolve(), int(sys.argv[2])
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "workspace-addons" / "dashboard" / "src"))

ACCOUNT = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()  # the real account home, not the temp HOME
if not str(D).startswith(str(ACCOUNT / ".orch-test") + os.sep) or os.environ.get("ORCH_HOME_STRICT") != "1":
    sys.exit("server.py runs only in a throw-away home under ~/.orch-test with ORCH_HOME_STRICT=1")

WS = D / "Pilatus"
WS.mkdir(parents=True, exist_ok=True)


# No real agent tool may ever run here: stand-ins named like the built-in agent programs come first on PATH for
# this server and everything it starts (a helper run, a Test click, a ticket pinned to a built-in tool). Each writes one log
# line, waits a little (so Stop has something to stop) and ends.
def stub(name: str) -> str:
    """The stand-in for one built-in agent program, from its own adapter entry (this file names no tool)."""
    login = adapters.load(name).get("login") or {}
    status, key = " ".join(login.get("status") or []), login.get("logged_in")
    renew, links = " ".join(login.get("renew") or []), login.get("links") or []
    lines = [
        "#!/bin/sh",
        'D="$(dirname "$0")/.."',
        'echo "$(date) $(basename "$0") $*" >> "$D/fake-agent.log"',
        'case " $* " in',
        '  *" --session-id "*|*" -p "*|*" exec "*) sleep 20 ;;',
    ]
    if status and isinstance(
        key, str
    ):  # the login check: signed out until the stand-in sign-in below finished
        lines.append(
            f'  *" {status} "*) if [ -f "$D/standin-logged-in-{name}" ]; then echo \'{{"{key}": true}}\';'
            f" else echo '{{\"{key}\": false}}'; fi ;;"
        )
    if renew and links:  # the sign-in: a link that goes nowhere, then one line (the code) on stdin, signed in
        lines.append(
            f'  *" {renew} "*) echo "Open {links[0]}standin-sign-in to sign in"; read -r code;'
            f' echo "$code" > "$D/standin-logged-in-{name}" ;;'
        )
    lines += ['  *) echo "stand-in 0.0 (not a real agent)" ;;', "esac", ""]
    return "\n".join(lines)  # a version or help question is answered at once; only a session waits


# GitHub is never reached: a stand-in `gh` answers the few questions orch asks about a pull request (open, green,
# not reviewed, one head commit) and "merges" by writing a line. Only pull requests of the made-up repository
# standin/lunch answer; anything else fails like an unknown repository.
HEAD = "c0ffee" + "0" * 34
GH = (
    "#!/bin/sh\n"
    'D="$(dirname "$0")/.."\n'
    'echo "$(date) gh $*" >> "$D/fake-gh.log"\n'
    'case " $* " in *" https://github.com/standin/lunch/pull/"*|*" api user "*) ;;'
    ' *) echo "not found" >&2; exit 1 ;; esac\n'
    'CHECK=\'{"name":"test","status":"COMPLETED","conclusion":"SUCCESS"}\'\n'
    'case " $* " in\n'
    '  *" api user "*) echo standin ;;\n'
    f'  *" pr view "*"reviewDecision"*) printf \'OPEN\\t\\t{HEAD}\\n\' ;;\n'
    f'  *" pr view "*"isDraft"*) echo \'{{"state":"OPEN","isDraft":false,"headRefOid":"{HEAD}",'
    '"statusCheckRollup":[\'"$CHECK"\']}\' ;;\n'
    '  *" pr view "*"statusCheckRollup"*) echo \'{"statusCheckRollup":[\'"$CHECK"\']}\' ;;\n'
    '  *" pr merge "*) echo "$*" >> "$D/standin-merged" ;;\n'
    '  *) echo "stand-in gh: not answered: $*" >&2; exit 1 ;;\n'
    "esac\n"
)
BIN = D / "bin"
BIN.mkdir(exist_ok=True)
from orch import adapters

# the program of every built-in agent, from orch's own adapter list (this file never names a tool)
PROGRAMS = sorted(
    {b for n in adapters.builtin_names() if (b := (adapters.load(n).get("detect") or {}).get("binary"))}
)
if not PROGRAMS:
    sys.exit("no built-in agent programs found in orch's adapter list: refusing to start")
if "gh" in PROGRAMS:
    sys.exit("an agent program is named gh: refusing to start")
BY_PROGRAM = {
    (adapters.load(n).get("detect") or {}).get("binary"): n
    for n in sorted(adapters.builtin_names(), reverse=True)
}
for name, body in [*((p, stub(BY_PROGRAM[p])) for p in PROGRAMS), ("gh", GH)]:
    (BIN / name).write_text(body)
    (BIN / name).chmod(0o755)
# `orch` by name is this checkout's orch (an add-on page such as Factory's calls the public CLI by name)
(BIN / "orch").write_text(f'#!/bin/sh\nexec "{sys.executable}" -I -m orch "$@"\n')
(BIN / "orch").chmod(0o755)
os.environ["PATH"] = f"{BIN}{os.pathsep}{os.environ.get('PATH', '')}"


def orch(*args: str, stdin: str | None = None) -> dict | str:
    """One orch command in the demo workspace (this Python, isolated mode). Returns parsed --json output."""
    r = subprocess.run(
        [sys.executable, "-I", "-m", "orch", *args],
        check=False,  # the return code is read below
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
    fake.write_text('#!/bin/sh\necho "$(date) $*" >> "$(dirname "$0")/fake-agent.log"\nsleep 20\n')
    fake.chmod(0o755)
    cfg = WS / ".orch" / "config.toml"
    text = re.sub(r"(?m)^agent = .*\n", "", cfg.read_text() if cfg.exists() else "")  # init's own pick goes
    text = (
        text.replace("[workspace]\n", '[workspace]\nagent = "standin"\n', 1)
        if "[workspace]\n" in text
        else (text + '\n[workspace]\nagent = "standin"\n')
    )
    cfg.write_text(text + f'\n[agents.standin]\nadapter = "generic"\ncommand = "sh {fake} {{prompt}}"\n')
    # A settings command runs only once this computer allowed it; unallowed, orch would fall back to the first agent
    # tool found on PATH (a real one). Allow the stand-in, and refuse to serve unless it is the helper that runs.
    from orch import config

    key = next(p["key"] for p in config.pending_agents(WS) if p["name"] == "standin")
    config.allow_agent(WS, "standin", key)
    if adapters.chosen(WS) != "standin" or config.pending_agents(WS):
        sys.exit(
            "the stand-in helper is not the one that would run: refusing to start (a real agent could run)"
        )
    for name in PROGRAMS:
        if adapters.find_binary(name) != str(BIN / name):
            sys.exit(f"{name} would not be the stand-in here: refusing to start (a real agent could run)")
    if shutil.which("gh") != str(BIN / "gh"):
        sys.exit("gh would not be the stand-in here: refusing to start (GitHub could be reached)")
    # Add-ons of this checkout (run.cjs layers them into every orch of the run): installed in the demo home and
    # allowed for this workspace, but off; a click-through turns one on itself (`addon add <name> --project-only`)
    # and off again, so the other click-throughs see the workspace as before.
    from orch import addons

    names = ["focus", "lessons", "pull-requests", "factory", "sync"]
    addons.registry_path().write_text(
        json.dumps([{"name": n, "source": "built-in", "version": "0.1.0"} for n in names])
    )
    found = addons.discover()
    for n in names:
        if n not in found:
            sys.exit(f"the {n} add-on of this checkout is not installed in the demo home: refusing to start")
        addons.record_consent(WS, n)
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
    orch(
        "check",
        "done",
        lunch,
        "c1",
        "--summary",
        "Nine of twelve come; two eat vegetarian.",
        "--note",
        "Asked in the team chat.",
    )
    orch(
        "ask",
        lunch,
        "Which restaurant?",
        "--option",
        "Pilatus Stube",
        "--option",
        "Seehaus",
        "--recommend",
        "Seehaus",
    )
    menu = new("menu", "Send the menu to the team", "Write the menu text")
    orch("ticket", "status", menu, "active")
    orch(
        "check",
        "done",
        menu,
        "c1",
        "--summary",
        "Menu written, three dishes.",
        "--note",
        "Short text, plain words.",
    )
    orch("ticket", "summary", menu, "Menu text is written and ready to send.")
    orch("ticket", "status", menu, "done")
    new("table", "Book a table for Friday", "Call the restaurant", "Confirm the time")
    new("budget", "Ask finance for the lunch budget")
    return ids


IDS = seed()
(D / "seed.json").write_text(json.dumps(IDS))

# Stand-ins for what lives outside this computer, on 127.0.0.1 only. They are started here but stay unused until a
# click-through turns the relay or publish on itself (both are off and invisible until a person turns them on).
sys.path.insert(0, str(ROOT / "workspace" / "tests"))
import fakes  # the same fakes the workspace tests use

SOON = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 7 * 86400))
LATER = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 14 * 86400))


def standin_publish() -> fakes.Fake:
    f = fakes.make_publish()
    expires = {}

    def post_file(
        m, q, body
    ):  # the shared file: as the fake does, but it ends in a week (the fake's date is past)
        status, out = first_post(m, q, body)
        expires[out["id"]] = SOON
        return status, {**out, "expires_at": SOON}

    def list_files(m, q, b):
        status, out = first_list(m, q, b)
        return status, {**out, "items": [{**i, "expires_at": expires.get(i["id"])} for i in out["items"]]}

    def extend(m, q, body):
        if m.group(1) not in f.files:
            return 404, {"error": "not_found", "message": "No such file."}
        expires[m.group(1)] = LATER
        return 200, {"id": m.group(1), "expires_at": LATER}

    first_post = next(fn for meth, rx, fn in f.routes if (meth, rx) == ("POST", "/v1/files"))
    first_list = next(fn for meth, rx, fn in f.routes if (meth, rx) == ("GET", "/v1/files"))
    f.routes[:0] = [
        ("POST", "/v1/files", post_file),
        ("GET", "/v1/files", list_files),
        ("PATCH", r"/v1/files/(f_[a-z0-9]+)", extend),
    ]
    return f


def standin_relay() -> fakes.Fake:
    f = fakes.make_relay()
    f.snapshot["workspaces"]["workspaces"] = [
        {
            "id": "ws_kitchen001",
            "name": "Kitchen",
            "description": "Cooks the team lunch.",
            "tags": [],
            "online": True,
            "last_seen": SOON,
            "can_send": {"text": True, "files": True, "delegate": False, "start": False},
            "accepts_from": {"text": True, "files": True, "delegate": False, "start": False},
        }
    ]
    f.snapshot["workspaces"]["phones"] = [{"id": "ph_anna000001", "name": "Anna's phone", "online": True}]
    f.route("POST", "/v1/heartbeat", lambda m, q, b: (200, {}))
    return f


PUBLISH, RELAY = standin_publish(), standin_relay()
(D / "standins.json").write_text(
    json.dumps(
        {
            "publish": {"url": PUBLISH.url, "workspace": fakes.WS, "token": PUBLISH.token},
            "relay": {"url": RELAY.url, "workspace": fakes.WS, "token": RELAY.token},
            "head": HEAD,
        }
    )
)

from orch import pagelaunch
from orch.pagesession import SELF

from orch_dashboard.server import make_server

srv = make_server(WS, PORT, orch_bin=SELF)
print(f"ready http://127.0.0.1:{PORT} {json.dumps(IDS)}", flush=True)


def tokens() -> None:
    for line in sys.stdin:
        if line.strip() == "token":
            print(f"token {pagelaunch.write_launch_token(WS, 'dashboard')}", flush=True)
        elif line.strip() == "forget-update-info":  # the page server keeps "the newest orch" for 10 minutes
            from orch import updateinfo

            updateinfo.forget()
            print("forgot update-info", flush=True)


threading.Thread(target=tokens, daemon=True).start()
srv.serve_forever()
