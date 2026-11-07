"""Workspace (W) and add-on (A) scenarios: CLI only, fake agent for the automation."""
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
    check((d / ".orch/harness/AGENTS.orch.md").is_file(), "orch block missing under .orch/harness")
    check(not (d / "AGENTS.md").exists() and not (d / "CLAUDE.md").exists() and not (d / ".gitignore").exists(), "init wrote a team file")
    check((d / ".claude/skills/orch").is_symlink() and (d / ".claude/skills/orch/SKILL.md").is_file(), ".claude/skills/orch is not a link")
    check("@.orch/harness/AGENTS.orch.md" in (d / "CLAUDE.local.md").read_text(), "CLAUDE.local.md lacks the import")
    gi = (d / ".orch/.gitignore").read_text()
    for line in (".local-id", "secrets/", "inbox/", "inbox-seen.json", "addons/"):
        check(line in gi.splitlines(), f".orch/.gitignore lacks {line}")
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
    """3 links (known site, plain, titled) + orch ext set kept; an unknown hand-added field survives the next CLI write."""
    ws = e.ws("Pilatus")
    t = e.orchj(ws, "ticket", "new", "W6 links")["id"]
    for url in ("https://acme.atlassian.net/browse/X-1", "https://teams.microsoft.com/l/x", "https://intranet.example/a"):
        e.orch(ws, "link", "add", t, url)
    e.orch(ws, "ext", "set", t, "demo", '{"k": 1}')
    p = ws / ".orch/tickets" / f"{t}.json"
    d = json.loads(p.read_text())
    d["x_hand"] = {"note": "keep me"}
    d["ext"]["unknown_addon"] = {"a": [1, 2]}
    p.write_text(json.dumps(d))
    e.orch(ws, "log", t, "another write")
    e.orch(ws, "check", "add", t, "again")
    d = tload(ws, t)
    check([l["kind"] for l in d["links"]] == ["link", "link", "link"] and all(l.get("at") and l.get("by") for l in d["links"]), f"links {d['links']}")
    listed = e.orch(ws, "link", "list", t)[1]
    check("Jira" in listed and "Teams" in listed and "intranet.example/a" in listed, f"link list {listed!r}")
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
    """addon add dashboard + automation (--yes), list --json shape, skills + AGENTS blocks, remove automation, add again."""
    ws = e.ws("Pilatus")
    for a in ("dashboard", "automation"):
        rc, out, err = e.addon_add(ws, a)
        check(rc == 0, f"addon add {a}: {(err or out)[-200:]}")
    lst = {x["name"]: x for x in e.orchj(ws, "addon", "list")}
    check(set(lst) >= {"dashboard", "automation"}, f"list: {list(lst)}")
    for a in ("dashboard", "automation"):
        x = lst[a]
        check(x["active"] is True and x["source"] == "built-in", f"{a}: {x}")
        check(set(x) >= {"name", "version", "description", "source", "active", "dashboard", "ticket_view", "background"}, f"keys {sorted(x)}")
        check((ws / f".agents/skills/orch-{a}/SKILL.md").is_file(), f"skill orch-{a} missing")
        check(f"orch-{a}" in (ws / ".orch/harness/AGENTS.orch.md").read_text(), f"orch block {a} missing")
    check(lst["automation"]["background"] is True and lst["automation"]["dashboard"]["label"], f"automation entry {lst['automation']}")
    act = json.loads((ws / ".orch/addons.json").read_text())["active"]
    check({"dashboard", "automation"} <= set(act) and act["automation"]["version"], f"addons.json {act}")
    check((ws / ".orch/.local-id").is_file(), ".orch/.local-id missing")
    reg = {x["name"] for x in json.loads((e.orch_home / "addons.json").read_text())}
    check({"dashboard", "automation"} <= reg, f"install registry {reg}")
    check((e.orch_home / "consent.json").is_file(), "consent record missing under ORCH_HOME")
    e.orch(ws, "addon", "remove", "automation")
    check(not (ws / ".agents/skills/orch-automation").exists(), "automation skill still there")
    check("orch-automation" not in (ws / ".orch/harness/AGENTS.orch.md").read_text(), "automation block still there")
    check("orch-dashboard" in (ws / ".orch/harness/AGENTS.orch.md").read_text(), "dashboard block was removed too")
    rc, out, err = e.addon_add(ws, "automation")  # back for A4/A5
    check(rc == 0, f"addon add automation again: {(err or out)[-200:]}")
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
    return e.sh(["orch", "automation", *args], cwd=ws)


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
    """orch wait --until: the automation starts the (fake) agent at that time; history entry; waiting_on cleared."""
    e.ensure_addons()
    ws = e.ws("Pilatus")
    log = _fake_agent(e, ws)
    t = e.orchj(ws, "ticket", "new", "A4 wake")["id"]
    until = (datetime.now(UTC) + timedelta(seconds=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    e.orch(ws, "wait", t, "--until", until)
    check(tload(ws, t)["waiting_on"] == {"kind": "time", "until": until}, f"waiting_on: {tload(ws, t).get('waiting_on')}")
    check("wake_at" not in tload(ws, t), "legacy wake_at written")
    rc, out, err = _sched(e, ws, "start")
    check(rc == 0, f"automation start: {err or out}")
    try:
        check(_sched(e, ws, "status")[0] == 0, "automation not running")
        started = _wait(lambda: "start" in log.read_text(), 40)
        check(started, "agent was not started within 40 s")
        _wait(lambda: "end" in log.read_text(), 15)
        d = tload(ws, t)
        check(not d.get("waiting_on"), f"waiting_on not cleared: {d.get('waiting_on')}")
        check(any("Automation started an agent run" in h["text"] for h in d["history"]), "no automation history entry")
        check(any(h["by"] == "agent:automation" for h in d["history"]), "history not by agent:automation")
        check(t in log.read_text(), "prompt did not name the ticket")
        check(len(list((ws / ".orch/run/logs").glob(f"{t}-*.log"))) == 1, "run log missing")
    finally:
        _sched(e, ws, "stop")
    check(_sched(e, ws, "status")[0] == 1, "automation did not stop")


@scenario("A5", slow=True)
def a5(e):
    """Recurring ticket (cron every minute): two runs, one at a time, logs written."""
    e.ensure_addons()
    ws = e.ws("Reports")
    for a in ("automation",):
        e.sh(["orch", "addon", "add", a, "--yes"], cwd=ws, check_rc=True, timeout=600)
    log = _fake_agent(e, ws)
    t = e.orchj(ws, "ticket", "new", "A5 weekly report")["id"]
    rep = e.orchj(ws, "automation", "repeat", t, "* * * * *")
    check(rep["recurring"] is True and rep["cron"] == "* * * * *", f"repeat: {rep}")
    check(tload(ws, t)["ext"]["automation"]["cron"] == "* * * * *" and "recurring" not in tload(ws, t), "ext.automation not set / legacy field")
    rc, out, err = _sched(e, ws, "start")
    check(rc == 0, f"automation start: {err or out}")
    try:
        ok = _wait(lambda: log.read_text().count("start") >= 2 and log.read_text().count("end") >= 2, 170, 2)
        check(ok, f"fewer than 2 finished runs in 170 s: {log.read_text()!r}")
        time.sleep(5)  # let the automation reap the finished runs (log footer)
    finally:
        _sched(e, ws, "stop")
        # end the recurrence: an open every-minute ticket left in Reports would start the agent in later
        # scenarios (R6-R8 assert exact agent runs there)
        e.orch(ws, "ticket", "status", t, "dropped")
    lines = log.read_text().split("\n")
    kinds = [l.split()[0] for l in lines if l.startswith("start ") or (l.startswith("end ") and l[4:].isdigit())]  # the prompt spans lines
    check(all(kinds[i] != kinds[i + 1] for i in range(len(kinds) - 1)), f"runs overlapped: {kinds}")
    logs = sorted((ws / ".orch/run/logs").glob(f"{t}-*.log"))
    ends = [l for l in lines if l.startswith("end ")]  # the fake agent writes one end line per finished run
    check(len(logs) >= 2 and len(ends) >= 2, f"run logs missing or unfinished: {len(logs)} logs, {len(ends)} ends")
    st = json.loads((ws / ".orch/addons/automation/state.json").read_text())
    check(st[t].get("next_run"), "state.json has no next_run")


@scenario("A6")
def a6(e):
    raise Skip("login-item start/stop on macOS and Windows: not built yet")
