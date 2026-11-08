"""V3-SIM: a long-lived harness for the Simulator run (not a pass/fail test).

It starts the local relay + a real Pilatus workspace (via the normal e2e setup), creates a phone invitation and then waits
for host commands in a control folder, so a person (or an XCUITest run next to it) can drive the workspace side:

  ctl/<n>.py  - python code run with `e` (the e2e environment) in scope; set `out` to return a string
  ctl/<n>.out - written when done (the code's `out`, or "ERR ..." on an exception)
  ctl/stop    - ends the harness

Host helpers: mm_on(hours=4), mm_off(), mm_status(), keeper_pid(), ask_question(text), mk_done_topic(title).
Start:  E2E_SIM_CTL=<folder> e2e/run.sh V3-SIM      (the folder must exist; `info.json` appears in it when ready)
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import traceback
from pathlib import Path

from lib import check, scenario, wait_http


def relay_stop(e):
    """Stop the local relay (own pid only)."""
    p = e.rel.proc
    p.terminate()
    p.wait(10)
    e.pids[:] = [x for x in e.pids if x != p.pid]


def relay_start(e):
    """Start the relay again with the same data folder, port and token."""
    if e.rel.proc.poll() is None:
        return  # already running
    env = e.rel.env
    log = open(e.tmp / "relay.log", "a")
    e.rel.proc = subprocess.Popen([e.bins["relay"]], env=env, stdout=log, stderr=log, cwd=e.tmp)
    e.pids.append(e.rel.proc.pid)
    check(wait_http(e.rel.url + "/health"), "relay did not come back")


@scenario("V3-SIM", local_only=True)
def sim(e):
    ctl = Path(os.environ.get("E2E_SIM_CTL") or e.tmp / "ctl")
    ctl.mkdir(parents=True, exist_ok=True)
    e.ensure_addons()
    ids = e.relay_all()
    r = e.rel.admin.call("POST", "/admin/api/phones", {"name": "Simulator phone", "workspaces": [ids["Pilatus"]]})
    check(r.status == 201, f"add phone: {r}")
    info = {"link": r.json()["link"], "relay": e.rel.url, "ws": ids["Pilatus"], "ids": ids,
            "ws_path": str(e.ws("Pilatus")), "tmp": str(e.tmp), "pid": os.getpid()}
    (ctl / "info.json").write_text(json.dumps(info))
    done = set()
    S: dict = {}

    def ph():
        """The id of the paired Simulator phone."""
        return [p["id"] for p in e.rel.admin.call("GET", "/admin/api/phones").json()["items"]
                if p["paired"]][0]  # the Simulator phone pairs first; test phones come later

    def ws_send(text, *flags):
        """Workspace -> phone text (orch relay send); returns what orch printed."""
        return e.orch("Pilatus", "relay", "send", ph(), text, *flags)[1]

    def inbox():
        return e.orch("Pilatus", "relay", "inbox")[1]

    def mobile(*args) -> str:
        return e.sh(["orch", "relay", "mobile", *args, "--json"],
                    cwd=e.ws("Pilatus"), timeout=60, check_rc=True)[1]

    def mm_on(hours=4) -> str:
        return mobile("on", "--hours", str(hours))

    def mm_off() -> str:
        return mobile("off")

    def mm_status() -> str:
        return mobile("status")

    def keeper_pid() -> str:
        """Read this workspace's keeper PID; confirm it still names a keeper."""
        state = e.ws("Pilatus") / ".orch/run/mobile-mode.json"
        if not state.exists():
            return ""
        pid = json.loads(state.read_text()).get("keeper_pid")
        if not isinstance(pid, int) or pid <= 0:
            return ""
        p = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
        return str(pid) if p.returncode == 0 and "relay mobile keeper" in p.stdout else ""

    def ask_question(text) -> str:
        """Return a new ticket ID; ask asynchronously, using Mobile mode's phone routing."""
        tid = json.loads(e.orch("Pilatus", "ticket", "new", text, "--json")[1])["id"]
        p = subprocess.Popen(
            ["orch", "ask", tid, text, "--option", "Yes", "--option", "No", "--recommend", "Yes"],
            cwd=e.ws("Pilatus"), env=e.env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        S.setdefault("ask", []).append(p)
        e.pids.append(p.pid)
        return tid

    def mk_done_topic(title) -> str:
        """Create a Done ticket with a PDF result and send its topic update."""
        tid = json.loads(e.orch("Pilatus", "ticket", "new", title, "--json")[1])["id"]
        c = json.loads(e.orch("Pilatus", "check", "add", tid, "Make the deck", "--json")[1])["id"]
        pdf = "%PDF-1.4|1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj|2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj|3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj|4 0 obj<</Length 44>>stream|BT /F1 24 Tf 40 100 Td (Board deck Q3) Tj ET|endstream endobj|5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj|trailer<</Root 1 0 R/Size 6>>|%%EOF|"
        p = e.ws("Pilatus") / f"{tid}-deck.pdf"
        p.write_bytes(pdf.replace("|", "\n").encode())
        e.orch("Pilatus", "check", "done", tid, c, "--file", str(p), "--title", title, "--role", "result")
        e.orch("Pilatus", "ticket", "status", tid, "done")
        ws_send(f"{title} is done.", "--ticket", tid, "--update", "result")
        return tid

    scope = {"S": S, "ph": ph, "ws_send": ws_send, "inbox": inbox, "e": e,
             "relay_stop": relay_stop, "relay_start": relay_start, "ids": ids, "info": info,
             "mm_on": mm_on, "mm_off": mm_off, "mm_status": mm_status, "keeper_pid": keeper_pid,
             "ask_question": ask_question, "mk_done_topic": mk_done_topic}
    while not (ctl / "stop").exists():
        for f in sorted(ctl.glob("*.py")):
            if f.name in done:
                continue
            done.add(f.name)
            local = dict(scope, out="")
            try:
                exec(compile(f.read_text(), str(f), "exec"), local)  # noqa: S102 - a dev tool, run by the host
                res = str(local.get("out", ""))
            except Exception:  # noqa: BLE001
                res = "ERR " + traceback.format_exc()[-1500:]
            f.with_suffix(".out").write_text(res)
        time.sleep(0.3)
    return "harness stopped"
