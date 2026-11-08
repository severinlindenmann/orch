#!/usr/bin/env python3
"""A fake generic agent for the Focus scenarios.

    agent.py [--ask TEXT] [--hold SECONDS] [prompt ...]

Works the checklist of $ORCH_TICKET with `orch check start|done`. With --ask it asks TEXT (options Yes / No) when it
reaches the last task and waits (up to 40 s) for the answer before finishing that task. --hold keeps it running
that many seconds at the end (so a page can look at a live run).
"""
import json
import os
import shlex
import subprocess
import sys
import time


def orch(*args):
    return subprocess.run(shlex.split(os.environ.get("ORCH_CMD", "orch")) + list(args), capture_output=True, text=True)


def main(argv):
    ask, hold, it = None, 0.0, iter(argv)
    for a in it:
        if a == "--ask":
            ask = next(it)
        elif a == "--hold":
            hold = float(next(it))
    tid = os.environ["ORCH_TICKET"]
    items = json.loads(orch("ticket", "show", tid, "--json").stdout).get("checklist", [])
    todo = [c for c in items if not c.get("done")]
    for n, c in enumerate(todo):
        orch("check", "start", tid, c["id"])
        if ask and n == len(todo) - 1:
            q = json.loads(orch("ask", tid, ask, "--option", "Yes", "--option", "No", "--check", c["id"], "--json").stdout)
            end = time.time() + 40
            while time.time() < end:
                t = json.loads(orch("ticket", "show", tid, "--json").stdout)
                if any(x["id"] == q["id"] and x.get("answer") is not None for x in t.get("questions", [])):
                    break
                time.sleep(0.5)
        orch("check", "done", tid, c["id"], "--note", "done by the focus test agent")
    time.sleep(hold)
    print("done")


if __name__ == "__main__":
    main(sys.argv[1:])
