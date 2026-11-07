"""V3-SIM: a long-lived harness for the Simulator run (not a pass/fail test).

It starts the local relay + a real Pilatus workspace (via the normal e2e setup), creates a phone invitation and then waits
for host commands in a control folder, so a person (or an XCUITest run next to it) can drive the workspace side:

  ctl/<n>.py  - python code run with `e` (the e2e environment) in scope; set `out` to return a string
  ctl/<n>.out - written when done (the code's `out`, or "ERR ..." on an exception)
  ctl/stop    - ends the harness

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
                if p["paired"] and p["name"] == "Simulator phone"][-1]

    def ws_send(text, *flags):
        """Workspace -> phone text (orch relay send); returns what orch printed."""
        return e.orch("Pilatus", "relay", "send", ph(), text, *flags)[1]

    def inbox():
        return e.orch("Pilatus", "relay", "inbox")[1]

    scope = {"S": S, "ph": ph, "ws_send": ws_send, "inbox": inbox, "e": e, "relay_stop": relay_stop, "relay_start": relay_start, "ids": ids, "info": info}
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
