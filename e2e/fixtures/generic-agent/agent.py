#!/usr/bin/env python3
"""A fake agent that is just a command line: the generic adapter's test double.

    agent.py [--silent N | --interactive] [prompt ...]

Default (one-shot): reads the prompt (arguments, or stdin when there are none), finds the ticket id in
$ORCH_TICKET or in the prompt, starts and finishes the first open checklist item with `orch`, then exits.
--interactive: stays up, reads one line of input at a time (a live run in tmux) and calls `orch run done`
at start and after each line, which is how a generic agent says "idle".
--silent N: sleeps N seconds without any orch call (a quiet agent must keep its claim).

$ORCH_CMD names the orch command (default: orch). $GENERIC_AGENT_LOG, when set, gets one line per prompt or
input line ("prompt: ..." / "input: ...") so tests can count what arrived.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import time


def orch(*args: str) -> subprocess.CompletedProcess:
    cmd = shlex.split(os.environ.get("ORCH_CMD", "orch")) + list(args)
    return subprocess.run(cmd, capture_output=True, text=True)


def log(kind: str, text: str) -> None:
    path = os.environ.get("GENERIC_AGENT_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{kind}: {text.strip()}\n")


def ticket_of(text: str) -> str | None:
    if os.environ.get("ORCH_TICKET"):
        return os.environ["ORCH_TICKET"]
    m = re.search(r"\bt_[a-z0-9]{6,16}\b", text)
    return m.group(0) if m else None


def do_work(tid: str) -> None:
    r = orch("ticket", "show", tid, "--json")
    if r.returncode != 0:
        return
    for item in json.loads(r.stdout).get("checklist", []):
        if not item.get("done"):
            orch("check", "start", tid, item["id"])
            orch("check", "done", tid, item["id"], "--note", "done by the generic test agent")
            return


def main(argv: list[str]) -> int:
    interactive = "--interactive" in argv
    silent = None
    rest = []
    it = iter(argv)
    for a in it:
        if a == "--silent":
            silent = float(next(it))
        elif a != "--interactive":
            rest.append(a)
    prompt = " ".join(rest)
    if silent is not None:
        log("prompt", prompt)
        time.sleep(silent)
        return 0
    if interactive:
        tid = ticket_of(prompt)
        print("ready", flush=True)
        if tid:
            orch("run", "done", tid)
        for line in sys.stdin:
            line = line.rstrip("\n")
            if line.strip() == "/exit":
                return 0
            if not line.strip():
                continue
            log("input", line)
            print(f"got: {line}", flush=True)
            tid = tid or ticket_of(line)
            if tid:
                orch("run", "done", tid)
        return 0
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read()
    log("prompt", prompt)
    tid = ticket_of(prompt)
    if tid:
        do_work(tid)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
