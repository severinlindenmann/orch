"""Workspace (W) and add-on (A) scenarios: CLI only, fake agent for the scheduler."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lib import Fail, Skip, check, scenario


def snapshot(d: Path) -> dict:
    out = {}
    for p in sorted(d.rglob("*")):
        if ".git" in p.parts:
            continue
        if p.is_symlink():
            out[str(p.relative_to(d))] = "link:" + os.readlink(p)
        elif p.is_file():
            out[str(p.relative_to(d))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def tload(ws: Path, tid: str) -> dict:
    return json.loads((ws / ".orch" / "tickets" / f"{tid}.json").read_text())


EVID = '{"type":"commit","ref":"abc1234"}'


@scenario("W0")
def w0(e):
    """The REAL one-liner from GitHub raw (ref from E2E_INSTALL_REF, default develop) in a bare HOME without uv."""
    ref = os.environ.get("E2E_INSTALL_REF", "develop")
    home = e.tmp / "w0home"
    (home / "proj").mkdir(parents=True)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "USER": "e2e", "LANG": "C.UTF-8", "TERM": "dumb",
           "GIT_TERMINAL_PROMPT": "0", "ORCH_REF": ref}
    url = f"https://raw.githubusercontent.com/severinlindenmann/orch/{ref}/install.sh"

    def run(cmd, cwd=None, timeout=600):
        p = subprocess.run(cmd, cwd=cwd or home, env=env, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr

    check(shutil.which("uv", path=env["PATH"]) is None, "uv must not be on the bare PATH")
    rc, out, err = run(["sh", "-c", f"curl -fsSL {url} | sh"])
    check(rc == 0, f"installer failed rc={rc}: {(err or out)[-300:]}")
    check((home / ".local/bin/uv").exists() or (home / ".cargo/bin/uv").exists(), "installer did not fetch uv")
    env["PATH"] = f"{home}/.local/bin:{env['PATH']}"
    rc, out, err = run(["orch", "--version"])
    check(rc == 0 and "orch" in out.lower(), f"orch --version: {out!r} {err[-200:]}")
    proj = home / "proj"
    rc, out, err = run(["orch", "init"], cwd=proj)
    check(rc == 0 and (proj / ".orch/tickets").is_dir(), f"orch init: {err[-200:]}")
    skill = proj / ".agents/skills/orch/SKILL.md"
    skill.write_text("tampered\n")
    rc, out, err = run(["orch", "update"], cwd=proj)
    check(rc == 0 and skill.read_text() != "tampered\n", f"orch update did not refresh the skill: rc={rc} {err[-200:]}")
    return f"one-liner ({ref}) -> uv fetched, version, init, update ok"


@scenario("W1")
def w1(e):
    """orch init on an empty folder; second run changes nothing."""
    d = e.tmp / "w1-empty"
    d.mkdir()
    rc, out, err = e.sh(["orch", "init"], cwd=d)
    check(rc == 0, f"init failed: {err}")
    check((d / ".orch/tickets").is_dir(), ".orch/tickets missing")
    check((d / ".agents/skills/orch/SKILL.md").is_file(), "orch skill missing")
    agents = (d / "AGENTS.md").read_text()
    check("<!-- orch:begin orch" in agents and "<!-- orch:end orch" in agents, "AGENTS.md block missing")
    check((d / ".claude/skills").is_symlink(), ".claude/skills is not a link")
    check(os.readlink(d / ".claude/skills") == "../.agents/skills", f"link target {os.readlink(d / '.claude/skills')}")
    check("@AGENTS.md" in (d / "CLAUDE.md").read_text(), "CLAUDE.md lacks @AGENTS.md")
    gi = (d / ".gitignore").read_text()
    for line in (".orch/.local-id", ".orch/secrets/", ".orch/inbox/", ".orch/inbox-seen.json", ".orch/addons/"):
        check(line in gi.splitlines(), f".gitignore lacks {line}")
    before = snapshot(d)
    rc, _, err = e.sh(["orch", "init"], cwd=d)
    check(rc == 0, f"second init failed: {err}")
    after = snapshot(d)
    check(before == after, f"second init changed: {[k for k in after if after.get(k) != before.get(k)]}")
    return "Windows junction part not run (macOS host)"


@scenario("W2")
def w2(e):
    """Agent (claude -p) makes a ticket, adds checks, does the work."""
    raise Skip("agent scenario (another lane)")


@scenario("W3")
def w3(e):
    """check done without evidence is refused (exit 2); with evidence it is done."""
    ws = e.ws("Pilatus")
    t = e.orchj(ws, "ticket", "new", "W3 evidence")["id"]
    e.orch(ws, "check", "add", t, "Do the thing")
    rc, out, err = e.orch(ws, "check", "done", t, "c1", ok=False)
    check(rc == 2, f"expected exit 2, got {rc}")
    check(err.startswith("Refused:") and ("proof" in err.lower() or "evidence" in err.lower()), f"reason not plain: {err!r}")
    check(not tload(ws, t)["checklist"][0]["done"], "check was marked done anyway")
    e.orch(ws, "check", "done", t, "c1", "--evidence", EVID)
    c = tload(ws, t)["checklist"][0]
    check(c["done"] and c["evidence"][0]["ref"] == "abc1234", f"not done with evidence: {c}")


@scenario("W4")
def w4(e):
    """ticket status done is refused while a checked item lacks evidence."""
    ws = e.ws("Pilatus")
    t = e.orchj(ws, "ticket", "new", "W4 status")["id"]
    e.orch(ws, "check", "add", t, "Item A")
    p = ws / ".orch/tickets" / f"{t}.json"
    d = json.loads(p.read_text())
    d["checklist"][0]["done"] = True  # hand-edited: checked, no evidence
    p.write_text(json.dumps(d))
    rc, _, err = e.orch(ws, "ticket", "status", t, "done", ok=False)
    check(rc == 2 and "evidence" in err.lower(), f"expected refusal, got rc={rc} {err!r}")
    d["checklist"][0]["evidence"] = [{"type": "note", "ref": "checked by hand"}]
    p.write_text(json.dumps(d))
    e.orch(ws, "ticket", "status", t, "done")
    # an UNCHECKED item blocks done too; a dropped ticket is not affected
    t2 = e.orchj(ws, "ticket", "new", "W4 unchecked")["id"]
    e.orch(ws, "check", "add", t2, "never done")
    rc, _, err = e.orch(ws, "ticket", "status", t2, "done", ok=False)
    check(rc == 2 and "not checked" in err.lower(), f"unchecked item must refuse done, got rc={rc} {err!r}")
    e.orch(ws, "ticket", "status", t2, "dropped")
    return "refusal ok (checked without evidence, and unchecked)"


@scenario("W5")
def w5(e):
    """Question with options + recommendation, status waiting; human answers via CLI."""
    ws = e.ws("Pilatus")
    t = e.orchj(ws, "ticket", "new", "W5 question")["id"]
    e.orch(ws, "ask", t, "Which colour?", "--option", "red", "--option", "blue", "--recommend", "blue", by="agent:claude-code")
    d = tload(ws, t)
    check(d["status"] == "waiting" and d["waiting_on"] == {"kind": "question", "ref": "q1"}, f"not waiting: {d['status']}")
    # an option matches case-insensitively and is stored in its own spelling; other text is a free answer (#21)
    e.orch(ws, "answer", t, "q1", "BLUE", by="human:sev")
    q = tload(ws, t)["questions"][0]
    check(q["answer"] == "blue" and q["answered_by"] == "human:sev" and q["via"] == "cli", f"answer fields {q}")
    check(tload(ws, t)["status"] == "active", "ticket did not resume")


@scenario("W6")
def w6(e):
    """3 link types + orch ext set kept; an unknown hand-added field survives the next CLI write."""
    ws = e.ws("Pilatus")
    t = e.orchj(ws, "ticket", "new", "W6 links")["id"]
    for ty, url in (("jira", "https://acme.atlassian.net/browse/X-1"), ("teams", "https://teams.microsoft.com/l/x"), ("file", "file:///tmp/a.txt")):
        e.orch(ws, "link", "add", t, "--type", ty, "--url", url)
    e.orch(ws, "ext", "set", t, "demo", '{"k": 1}')
    p = ws / ".orch/tickets" / f"{t}.json"
    d = json.loads(p.read_text())
    d["x_hand"] = {"note": "keep me"}
    d["ext"]["unknown_addon"] = {"a": [1, 2]}
    p.write_text(json.dumps(d))
    e.orch(ws, "log", t, "another write")
    e.orch(ws, "check", "add", t, "again")
    d = tload(ws, t)
    check([l["type"] for l in d["links"]] == ["jira", "teams", "file"], f"links {d['links']}")
    check(d["ext"]["demo"] == {"k": 1} and d["ext"]["unknown_addon"] == {"a": [1, 2]}, f"ext lost: {d['ext']}")
    check(d.get("x_hand") == {"note": "keep me"}, "unknown top-level field lost")


@scenario("W7")
def w7(e):
    """Same flow in Home (no git) and Reports (git + remote): ticket file works in local and remote git."""
    home = e.ws("Home")
    check(not (home / ".git").exists(), "Home must not be a git repo")
    t = e.orchj(home, "ticket", "new", "W7 home")["id"]
    e.orch(home, "check", "add", t, "x")
    e.orch(home, "check", "done", t, "c1", "--evidence", EVID)
    e.orch(home, "ticket", "status", t, "done")
    check(tload(home, t)["status"] == "done", "Home flow failed")
    rep = e.ws("Reports")
    t2 = e.orchj(rep, "ticket", "new", "W7 reports")["id"]
    e.sh(["git", "add", "-A"], cwd=rep, check_rc=True)
    e.sh(["git", "commit", "-qm", "ticket"], cwd=rep, check_rc=True)
    e.sh(["git", "push", "-q", "origin", "main"], cwd=rep, check_rc=True)
    clone = e.tmp / "reports-clone"
    e.sh(["git", "clone", "-q", str(e.tmp / "reports-remote.git"), str(clone)], check_rc=True)
    got = json.loads((clone / ".orch/tickets" / f"{t2}.json").read_text())
    check(got["title"] == "W7 reports", "ticket not in the remote")
    st = e.sh(["git", "status", "--porcelain"], cwd=rep)[1]
    check(".orch/secrets" not in st, "secrets would be committed")
    return "codex exec part not run (agent)"


# ---- add-ons ---------------------------------------------------------------------------------------


@scenario("A0")
def a0(e):
    """addon add dashboard + scheduler (--yes), list --json shape, skills + AGENTS blocks, remove scheduler, add again."""
    ws = e.ws("Pilatus")
    for a in ("dashboard", "scheduler"):
        rc, out, err = e.addon_add(ws, a)
        check(rc == 0, f"addon add {a}: {(err or out)[-200:]}")
    lst = {x["name"]: x for x in e.orchj(ws, "addon", "list")}
    check(set(lst) >= {"dashboard", "scheduler"}, f"list: {list(lst)}")
    for a in ("dashboard", "scheduler"):
        x = lst[a]
        check(x["active"] is True and x["source"] == "built-in", f"{a}: {x}")
        check(set(x) >= {"name", "version", "description", "source", "active", "dashboard", "ticket_view", "background"}, f"keys {sorted(x)}")
        check((ws / f".agents/skills/orch-{a}/SKILL.md").is_file(), f"skill orch-{a} missing")
        check(f"<!-- orch:addon:{a} -->" in (ws / "AGENTS.md").read_text(), f"AGENTS.md block {a} missing")
    check(lst["scheduler"]["background"] is True and lst["scheduler"]["dashboard"]["label"], f"scheduler entry {lst['scheduler']}")
    act = json.loads((ws / ".orch/addons.json").read_text())["active"]
    check({"dashboard", "scheduler"} <= set(act) and act["scheduler"]["version"], f"addons.json {act}")
    check((ws / ".orch/.local-id").is_file(), ".orch/.local-id missing")
    reg = {x["name"] for x in json.loads((e.orch_home / "addons.json").read_text())}
    check({"dashboard", "scheduler"} <= reg, f"install registry {reg}")
    check((e.orch_home / "consent.json").is_file(), "consent record missing under ORCH_HOME")
    e.orch(ws, "addon", "remove", "scheduler")
    check(not (ws / ".agents/skills/orch-scheduler").exists(), "scheduler skill still there")
    check("orch:addon:scheduler" not in (ws / "AGENTS.md").read_text(), "scheduler block still there")
    check("<!-- orch:addon:dashboard -->" in (ws / "AGENTS.md").read_text(), "dashboard block was removed too")
    rc, out, err = e.addon_add(ws, "scheduler")  # back for A4/A5
    check(rc == 0, f"addon add scheduler again: {(err or out)[-200:]}")
    e._addons = True


@scenario("A1")
def a1(e):
    raise Skip("dashboard browser scenario (another lane)")


@scenario("A2")
def a2(e):
    raise Skip("dashboard browser scenario (another lane)")


@scenario("A3")
def a3(e):
    raise Skip("dashboard snapshot publish needs browser check (another lane)")


def _fake_agent(e, ws: Path, interval: int = 2) -> Path:
    """Fake agent: records start/end with the ticket id from the prompt, takes 3 s."""
    log = e.tmp / f"fake-agent-{ws.name}.log"
    script = e.tmp / f"fake-agent-{ws.name}.sh"
    script.write_text(f'#!/bin/sh\necho "start $(date +%s) $*" >> "{log}"\nsleep 3\necho "end $(date +%s)" >> "{log}"\n')
    script.chmod(0o755)
    e.sched_config(ws, f'agent = "sh {script} {{prompt}}"', interval)
    log.write_text("")
    return log


def _sched(e, ws: Path, *args):
    return e.sh(["orch", "scheduler", *args], cwd=ws)


def _wait(fn, secs: float, step: float = 1.0):
    end = time.time() + secs
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


@scenario("A4")
def a4(e):
    """orch wait --until: the scheduler starts the (fake) agent at that time; history entry; waiting_on cleared."""
    e.ensure_addons()
    ws = e.ws("Pilatus")
    log = _fake_agent(e, ws)
    t = e.orchj(ws, "ticket", "new", "A4 wake")["id"]
    until = (datetime.now(UTC) + timedelta(seconds=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    e.orch(ws, "wait", t, "--until", until)
    check(tload(ws, t)["waiting_on"] == {"kind": "time", "until": until}, f"waiting_on: {tload(ws, t).get('waiting_on')}")
    check("wake_at" not in tload(ws, t), "legacy wake_at written")
    rc, out, err = _sched(e, ws, "start")
    check(rc == 0, f"scheduler start: {err or out}")
    try:
        check(_sched(e, ws, "status")[0] == 0, "scheduler not running")
        started = _wait(lambda: "start" in log.read_text(), 40)
        check(started, "agent was not started within 40 s")
        _wait(lambda: "end" in log.read_text(), 15)
        d = tload(ws, t)
        check(not d.get("waiting_on"), f"waiting_on not cleared: {d.get('waiting_on')}")
        check(any("Scheduler started an agent run" in h["text"] for h in d["history"]), "no scheduler history entry")
        check(any(h["by"] == "agent:scheduler" for h in d["history"]), "history not by agent:scheduler")
        check(t in log.read_text(), "prompt did not name the ticket")
        check(len(list((ws / ".orch/addons/scheduler/logs").glob(f"{t}-*.log"))) == 1, "run log missing")
    finally:
        _sched(e, ws, "stop")
    check(_sched(e, ws, "status")[0] == 1, "scheduler did not stop")


@scenario("A5", slow=True)
def a5(e):
    """Recurring ticket (cron every minute): two runs, one at a time, logs written."""
    e.ensure_addons()
    ws = e.ws("Reports")
    for a in ("scheduler",):
        e.sh(["orch", "addon", "add", a, "--yes"], cwd=ws, check_rc=True, timeout=600)
    log = _fake_agent(e, ws)
    t = e.orchj(ws, "ticket", "new", "A5 weekly report")["id"]
    rep = e.orchj(ws, "scheduler", "repeat", t, "* * * * *")
    check(rep["recurring"] is True and rep["cron"] == "* * * * *", f"repeat: {rep}")
    check(tload(ws, t)["ext"]["scheduler"]["cron"] == "* * * * *" and "recurring" not in tload(ws, t), "ext.scheduler not set / legacy field")
    rc, out, err = _sched(e, ws, "start")
    check(rc == 0, f"scheduler start: {err or out}")
    try:
        ok = _wait(lambda: log.read_text().count("start") >= 2 and log.read_text().count("end") >= 2, 170, 2)
        check(ok, f"fewer than 2 finished runs in 170 s: {log.read_text()!r}")
        time.sleep(5)  # let the scheduler reap the finished runs (log footer)
    finally:
        _sched(e, ws, "stop")
    lines = log.read_text().split("\n")
    kinds = [l.split()[0] for l in lines if l.strip()]
    check(all(kinds[i] != kinds[i + 1] for i in range(len(kinds) - 1)), f"runs overlapped: {kinds}")
    logs = sorted((ws / ".orch/addons/scheduler/logs").glob(f"{t}-*.log"))
    check(len(logs) >= 2 and all("# end" in p.read_text() for p in logs[:2]), "run logs missing or unfinished")
    st = json.loads((ws / ".orch/addons/scheduler/state.json").read_text())
    check(st[t].get("next_run"), "state.json has no next_run")


@scenario("A6")
def a6(e):
    raise Skip("login-item start/stop on macOS and Windows: not built yet")
