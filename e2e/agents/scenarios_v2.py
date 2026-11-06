"""v2 scenarios with REAL agent CLIs (opt-in: `e2e/run.sh V2-R3,V2-R4,V2-R5,V2-R7`). Each one skips cleanly when the
CLI or its login is missing. Prompts are tiny on purpose. Judged by end state (ticket sessions, claim files), not prose."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

from agentlib import codex_home, run_agent
from lib import Skip, check, scenario

# the core v2 scenarios have the same module name (e2e/scenarios_v2.py): load that file under another name
_spec = importlib.util.spec_from_file_location("v2core", Path(__file__).resolve().parent.parent / "scenarios_v2.py")
_v2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v2)
W, attach_watch, wait_for = _v2.W, _v2.attach_watch, _v2.wait_for

WORD = "MANGO"
ASK = "What was the secret word? Reply with that single word spelled backwards in lowercase. Do not run commands."


def real_w(e, sid: str, tool: str, tmux: bool = False) -> W:
    """A workspace whose agent is the real CLI (linked into its own bin folder), with only that agent's login."""
    exe = shutil.which(tool, path=e.path)
    if not exe:
        raise Skip(f"{tool} is not installed")
    env: dict = {}
    if tool == "claude":
        if not os.environ.get("E2E_CLAUDE_TOKEN"):
            raise Skip("no Claude setup-token available")
        env["CLAUDE_CODE_OAUTH_TOKEN"] = os.environ["E2E_CLAUDE_TOKEN"]
    else:
        if not (Path(codex_home(e)) / "auth.json").is_file():
            raise Skip("no Codex login (auth.json) available")
        env["CODEX_HOME"] = codex_home(e)
    d = e.tmp / "realbin" / sid.lower()
    d.mkdir(parents=True)
    (d / tool).symlink_to(exe)
    w = W(e, sid, tmux=tmux, extra_bin=d, env=env)
    w.init()
    w.o("config", "set", "workspace.agent", tool, by=None)
    return w


def _resume_twice(e, sid: str, tool: str) -> str:
    w = real_w(e, sid, tool)
    tid = w.ticket(f"Remember a word ({tool})")
    w.o("ticket", "summary", tid, f"The secret word is {WORD}. Reply OK. Do not run commands.")
    r1 = w.j("run", "start", tid)
    check(r1["resumed"] is False and r1["agent"] == tool, f"first run: {r1}")
    w.wait_done(tid, 240)
    ses = w.load(tid).get("sessions") or []
    check(len(ses) == 1 and ses[0]["agent"] == tool and ses[0]["id"],
          f"no session recorded after run 1: {ses}; log tail: {(w.root / r1['log']).read_text(errors='replace')[-500:]!r}")
    sid1 = ses[0]["id"]
    w.o("run", "send", tid, ASK, "--by", "human:anna")
    r2 = w.j("run", "start", tid)
    check(r2["resumed"] is True and r2["session"] == sid1, f"second run must continue {sid1}: {r2}")
    w.wait_done(tid, 240)
    log = (w.root / r2["log"]).read_text(errors="replace").lower()
    check(WORD[::-1].lower() in log, f"the resumed conversation did not know the word (log tail): {log[-400:]!r}")
    check(w.load(tid)["sessions"][0]["id"] == sid1, "session id changed on resume")
    return sid1


@scenario("V2-R3", slow=True)
def r3(e):
    """Claude one-shot resumes by id across two runs (--session-id, then --resume)."""
    return f"session {_resume_twice(e, 'V2-R3', 'claude')[:8]} continued"


@scenario("V2-R4", slow=True)
def r4(e):
    """Codex exec resume: the id comes from the first run's output, the second run continues it."""
    return f"thread {_resume_twice(e, 'V2-R4', 'codex')[:8]} continued"


def _pane(w: W, sock: str, tid: str) -> str:
    p = subprocess.run(["tmux", "-L", sock, "capture-pane", "-p", "-t", f"={tid}:"], capture_output=True, text=True, env=w.env)
    return p.stdout


def _live_state(w: W, tid: str) -> str | None:
    return ((w.claim(tid) or {}).get("live") or {}).get("state")


def _settled(w: W, tid: str) -> bool:
    """Idle with nothing left to paste (the SessionStart hook says idle before the first prompt went in)."""
    pend = w.root / ".orch/run/pending" / f"{tid}.jsonl"
    items = [json.loads(x) for x in pend.read_text().splitlines()] if pend.exists() else []
    return _live_state(w, tid) == "idle" and all(i.get("delivered_at") for i in items) and bool(items)


@scenario("V2-R5", slow=True)
def r5(e):
    """Live Claude in tmux: answer pasted on idle, attach --watch, kill the pane -> continue by id, idle close keeps the id."""
    w = real_w(e, "V2-R5", "claude", tmux=True)
    if not shutil.which("tmux", path=w.env["PATH"]):
        raise Skip("tmux is not installed")
    # a fresh HOME: skip the first-run screens of the interactive CLI (onboarding, folder trust)
    home = Path(e.env["HOME"])
    (home / ".claude.json").write_text(json.dumps({
        "hasCompletedOnboarding": True, "theme": "dark",
        "projects": {str(w.root.resolve()): {"hasTrustDialogAccepted": True, "allowedTools": []}}}))
    tid = w.ticket("Remember a word (live)")
    w.o("ticket", "summary", tid, f"The secret word is {WORD}. Reply OK. Do not run commands.")
    r = w.j("run", "start", tid, "--mode", "live")
    sock = r["tmux"]["socket"]
    check(r["mode"] == "live", f"live start: {r}")
    sid = wait_for(lambda: (w.load(tid).get("sessions") or [{}])[0].get("id"), 120)
    check(sid, f"the SessionStart hook never recorded the session id; pane: {_pane(w, sock, tid)[-400:]!r}")
    check(wait_for(lambda: _settled(w, tid), 240), f"live Claude never settled (Stop hook); pane: {_pane(w, sock, tid)[-400:]!r}")
    # the answer is pasted when idle, once
    w.o("run", "send", tid, ASK, "--by", "human:anna")
    pend = w.root / ".orch/run/pending" / f"{tid}.jsonl"
    check(wait_for(lambda: all(json.loads(x).get("delivered_at") for x in pend.read_text().splitlines()), 120), "the sent text was never pasted")
    check(wait_for(lambda: WORD[::-1].lower() in _pane(w, sock, tid).lower(), 180), f"Claude did not answer in the pane: {_pane(w, sock, tid)[-500:]!r}")
    seen = attach_watch(w, tid, WORD[::-1].lower().encode())
    check(len(seen) > 20, "attach --watch showed nothing")
    # kill the pane: the claim is dead and the next start continues by id
    subprocess.run(["tmux", "-L", sock, "kill-session", "-t", f"={tid}:"], capture_output=True, env=w.env)
    check(wait_for(lambda: w.j("run", "status", tid).get("state") in ("dead", None) or w.claim(tid) is None, 30), "claim of a killed pane is not dead")
    r2 = w.j("run", "start", tid, "--mode", "live")
    check(r2["resumed"] is True and r2["session"] == sid, f"must continue {sid} after the pane was killed: {r2}")
    check(wait_for(lambda: _settled(w, tid), 240), "resumed live Claude never settled")
    # a forced idle close ends the session but keeps the id
    w.o("run", "status", tid, env={"ORCH_RUN_IDLE_SECONDS": "0.01"}, by=None)
    check(w.claim(tid) is None, f"idle close did not end the live run: claim {w.claim(tid)}; pending {pend.read_text()[-400:]!r}")
    check(w.load(tid)["sessions"][0]["id"] == sid, "idle close lost the session id")
    return f"session {sid[:8]}"


@scenario("V2-R7", slow=True)
def r7(e):
    """A hand-started Claude claims with and without a session id; a claim without a process is never auto-taken."""
    w = real_w(e, "V2-R7", "claude")
    uuid = "5f0e8a52-77f4-4c1d-9a0b-2d6f1c3b9e11"
    ta = w.ticket("Hand started with a session id")
    tb = w.ticket("Hand started without a session id")
    run_agent(e, "V2-R7-a", "claude", w.root,
              f"Run exactly these two shell commands and nothing else: `orch run claim {ta} --session {uuid}` and then `orch run release {ta}`.",
              timeout=240)
    ses = w.load(ta).get("sessions") or []
    check(len(ses) == 1 and ses[0]["id"] == uuid and ses[0]["agent"] == "claude", f"claim --session did not record the id: {ses}")
    check(w.claim(ta) is None, "the hand-started claim was not released")
    run_agent(e, "V2-R7-b", "claude", w.root, f"Run exactly this one shell command and nothing else: `orch run claim {tb}`. Do not release it.", timeout=240)
    c = w.claim(tb)
    check(c and c["agent"] == "claude" and c["by"] == "agent:claude" and c["pid"] is None, f"claim without session id: {c}")
    check(not w.load(tb).get("sessions"), "a session was invented for a claim without an id")
    rc, out, err = w.o("run", "start", tb, "--json", ok=False)
    check(rc == 2 and (w.claim(tb) or {}).get("run") == c["run"], f"start must not take over a hand-started claim: rc={rc}")
