"""Add-on scenarios A7-A15: the core knows no add-on by name; add-ons look like built-ins, switch on only by the user, leave cleanly."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from lib import check, free_port, http, scenario
from scenarios_ws import tload

FIXTURE = Path(__file__).parent / "fixtures" / "hello-world"


def _local_addon(e, name: str = "hello-world") -> Path:
    """A private copy of the fixture add-on (scenarios edit it)."""
    dst = e.tmp / "addons" / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(FIXTURE, dst)
    return dst


@contextmanager
def _dashboard(e, ws: Path):
    """`orch dashboard serve` on a free port; yields (base url, get(path) -> (status, json))."""
    port = free_port(e.used_ports)
    p = subprocess.Popen(["orch", "dashboard", "serve", "--port", str(port)], cwd=ws, env=e.env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    e.pids.append(p.pid)
    base = f"http://127.0.0.1:{port}"
    try:
        end = time.time() + 20
        while time.time() < end and p.poll() is None:
            try:
                if http("GET", base + "/", timeout=2).status == 200:
                    break
            except OSError:
                time.sleep(0.3)
        else:
            check(False, "dashboard did not start")

        def get(path: str):
            r = http("GET", base + path, timeout=15)
            return r.status, r.json()

        yield base, get
    finally:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


def _help(e, ws) -> str:
    return e.sh(["orch", "--help-all"], cwd=ws)[1] + e.sh(["orch", "--help"], cwd=ws)[1]


def _tree_text(ws: Path) -> str:
    """All text a fresh agent could read: AGENTS.md, CLAUDE.md and every skill."""
    out = []
    for p in [ws / "AGENTS.md", ws / "CLAUDE.md", *sorted((ws / ".agents").rglob("*"))]:
        if p.is_file():
            out.append(p.read_text(errors="replace"))
    return "\n".join(out).lower()


@scenario("A7")
def a7(e):
    """Local-folder add-on (fixture hello-world): consent text, command in --help, skill + block, dashboard tab."""
    src = _local_addon(e)
    ws = e.ws("Hello")
    rc, out, err = e.sh(["orch", "addon", "add", str(src)], cwd=ws)  # no tty, no --yes: consent is refused, nothing changes
    check(rc == 2 and "local folder (not checked by orch)" in (out + err) and "--yes" in (out + err), f"no consent: {rc} {(err or out)[-200:]}")
    check(not (ws / ".orch/addons.json").exists() and not (ws / ".agents/skills/orch-hello-world").exists(), "changed without consent")
    rc, out, err = e.sh(["orch", "addon", "add", str(src), "--yes"], cwd=ws, timeout=600)
    check(rc == 0 and "Adds the command: orch hello-world" in out and "dashboard tab: Hello" in out, f"add: {(err or out)[-300:]}")
    e.addon_add(ws, "dashboard")
    rc, out, _ = e.sh(["orch", "hello-world", "hello", "--json"], cwd=ws)
    check(rc == 0 and json.loads(out) == {"hello": "world"}, f"command: {rc} {out}")
    check("hello-world" in _help(e, ws) and "Add-ons" in _help(e, ws), "command not in --help under Add-ons")
    check((ws / ".agents/skills/orch-hello-world/SKILL.md").is_file(), "skill missing")
    check("<!-- orch:addon:hello-world -->" in (ws / "AGENTS.md").read_text(), "AGENTS block missing")
    lst = {x["name"]: x for x in e.orchj(ws, "addon", "list")}
    check(lst["hello-world"]["source"] == "local" and lst["hello-world"]["active"], f"list: {lst['hello-world']}")
    with _dashboard(e, ws) as (base, get):
        st, state = get("/api/state")
        tabs = [a for a in state["addons"] if a["dashboard"]]
        check([a["name"] for a in tabs] == ["hello-world"] and tabs[0]["dashboard"]["label"] == "Hello", f"tabs {tabs}")
        st, v = get("/api/addon/hello-world")
        check(st == 200 and v["state"] == "ok" and v["view"]["blocks"][0]["type"] == "stat", f"view {v}")
    # consent is bound to this machine and workspace
    consent = json.loads((e.orch_home / "consent.json").read_text())
    rec = [c for c in consent if c["name"] == "hello-world"]
    check(len(rec) == 1 and rec[0]["source"] == "local" and rec[0].get("hash"), f"consent record {rec}")


@scenario("A8")
def a8(e):
    """remove scheduler: command refused, tab + skill + block gone, ext kept and hidden; --purge deletes data and [scheduler]."""
    ws = e.ws("Reports2")
    for a in ("dashboard", "scheduler"):
        check(e.addon_add(ws, a)[0] == 0, f"add {a}")
    t = e.orchj(ws, "ticket", "new", "A8 repeating")["id"]
    e.orch(ws, "scheduler", "repeat", t, "0 7 * * 1")
    check("scheduler" in e.orchj(ws, "ticket", "show", t)["ext"], "ext.scheduler not visible while active")
    e.sched_config(ws, 'agent = "true"')
    (ws / ".orch/addons/scheduler").mkdir(parents=True, exist_ok=True)
    (ws / ".orch/addons/scheduler/state.json").write_text("{}")
    with _dashboard(e, ws) as (_, get):
        check(any(a["name"] == "scheduler" and a["dashboard"] for a in get("/api/state")[1]["addons"]), "tab missing before remove")
    e.orch(ws, "addon", "remove", "scheduler")
    rc, out, err = e.sh(["orch", "scheduler", "list"], cwd=ws)
    check(rc == 2 and "not turned on in this workspace" in err and "orch addon add scheduler" in err, f"command not refused: {rc} {err!r}")
    check(not (ws / ".agents/skills/orch-scheduler").exists(), "skill still there")
    check("orch:addon:scheduler" not in (ws / "AGENTS.md").read_text(), "block still there")
    check("scheduler" not in _help(e, ws).lower(), "scheduler still in --help")
    check("scheduler" not in json.loads((ws / ".orch/addons.json").read_text())["active"], "still in addons.json")
    with _dashboard(e, ws) as (_, get):
        check(not any(a["name"] == "scheduler" for a in get("/api/state")[1]["addons"]), "tab still there after remove")
    # data kept, hidden
    check(tload(ws, t)["ext"]["scheduler"]["cron"] == "0 7 * * 1", "ext.scheduler lost from the ticket file")
    check("scheduler" not in (e.orchj(ws, "ticket", "show", t).get("ext") or {}), "inactive ext shown")
    e.orch(ws, "log", t, "still works")  # a hidden ext never blocks the ticket
    check((ws / ".orch/addons/scheduler/state.json").exists(), "add-on data folder was deleted")
    # the add-on is still installed on the machine, so it can come back; --purge on the second removal
    check(e.addon_add(ws, "scheduler")[0] == 0, "add again")
    check("scheduler" in (e.orchj(ws, "ticket", "show", t).get("ext") or {}), "ext not visible again after add")
    e.orch(ws, "addon", "remove", "scheduler", "--purge")
    check(not (ws / ".orch/addons/scheduler").exists(), "--purge kept the data folder")
    cfg = (ws / ".orch/config.toml").read_text() if (ws / ".orch/config.toml").exists() else ""
    check("[scheduler]" not in cfg, "--purge kept [scheduler] in config.toml")
    check(tload(ws, t)["ext"]["scheduler"]["cron"] == "0 7 * * 1", "--purge deleted ticket ext data")
    return "ext kept and hidden; purge removes data folder and config table, not ticket data"


@scenario("A9")
def a9(e):
    """A 'cloned repo' with .orch/addons.json, leftover data and ext.<name> alone activates nothing; prints the turn-on hint."""
    ws = e.ws("Cloned")
    e.sh(["git", "init", "-q", "-b", "main"], cwd=ws, check_rc=True)
    e.orch(ws, "init")
    t = e.orchj(ws, "ticket", "new", "A9 from the clone")["id"]
    d = tload(ws, t)
    d["ext"] = {"scheduler": {"recurring": True, "cron": "* * * * *"}}
    (ws / ".orch/tickets" / f"{t}.json").write_text(json.dumps(d))
    (ws / ".orch/addons.json").write_text(json.dumps({"active": {"scheduler": {"version": "0.2.0", "activated_at": "2026-11-01T00:00:00Z"}}}))
    (ws / ".orch/addons/scheduler").mkdir(parents=True)
    (ws / ".orch/addons/scheduler/state.json").write_text("{}")
    (ws / ".orch/.local-id").unlink(missing_ok=True)  # a clone never brings the (gitignored) local id
    rc, out, err = e.sh(["orch", "scheduler", "list"], cwd=ws)
    check(rc == 2 and "not turned on" in err and "orch addon add scheduler" in err, f"clone activated or no hint: {rc} {err!r}")
    check("scheduler" not in _help(e, ws).lower(), "listed add-on shows in --help")
    check(not (ws / ".agents/skills/orch-scheduler").exists() and "scheduler" not in _tree_text(ws), "skill/AGENTS text from a file alone")
    check("scheduler" not in (e.orchj(ws, "ticket", "show", t).get("ext") or {}), "ext shown without the add-on")
    lst = {x["name"]: x for x in e.orchj(ws, "addon", "list")}
    check(not lst.get("scheduler", {}).get("active"), f"list says active: {lst.get('scheduler')}")
    check("scheduler" not in [a["name"] for a in _dash_tabs(e, ws)], "tab from a file alone")
    # an empty background run does nothing either: no process, no log
    check(not list((ws / ".orch/addons/scheduler").glob("*.pid")), "a process was started")
    # turning it on is the user's action
    check(e.addon_add(ws, "scheduler")[0] == 0, "addon add scheduler in the clone")
    check(e.sh(["orch", "scheduler", "list"], cwd=ws)[0] == 0, "command not available after the user turned it on")


def _dash_tabs(e, ws) -> list[dict]:
    if e.sh(["orch", "dashboard", "--help"], cwd=ws)[0] != 0:  # dashboard add-on is not on here: no tab can exist
        return []
    with _dashboard(e, ws) as (_, get):
        return [a for a in get("/api/state")[1]["addons"] if a["dashboard"]]


@scenario("A10")
def a10(e):
    """A view that is too slow: last good result shown as stale ('as of'), then the error state when there never was one."""
    src = _local_addon(e)
    ws = e.ws("Hello")
    check(e.addon_add(ws, src)[0] == 0 and e.addon_add(ws, "dashboard")[0] == 0, "add")
    slow = ws / ".orch/addons/hello-world/slow"
    slow.parent.mkdir(parents=True, exist_ok=True)
    slow.write_text("")  # never answered in time: error state
    with _dashboard(e, ws) as (_, get):
        t0 = time.time()
        st, v = get("/api/addon/hello-world")
        check(st == 200 and v["state"] == "error" and v["view"] is None and v["message"], f"no last-good: {v}")
        check(time.time() - t0 < 5, f"pull did not time out: {time.time() - t0:.1f}s")
        slow.unlink()
        st, v = get("/api/addon/hello-world")
        check(v["state"] == "ok" and v["as_of"], f"fast again: {v}")
        slow.write_text("")
        st, v = get("/api/addon/hello-world")
        check(v["state"] == "stale" and v["view"] and v["as_of"] and v["message"], f"stale expected: {v}")
        slow.unlink()
        check(get("/api/addon/hello-world")[1]["state"] == "ok", "does not recover")
    return "error without last good, ok, stale with 'as of', recovered"


@scenario("A11")
def a11(e):
    """Snapshot leaves add-on tabs, ticket ext rows and add-on data out; --with-addons puts them in."""
    ws = e.ws("Snap")
    for a in ("dashboard", "scheduler"):
        check(e.addon_add(ws, a)[0] == 0, f"add {a}")
    t = e.orchj(ws, "ticket", "new", "A11 visible ticket")["id"]
    e.orch(ws, "scheduler", "repeat", t, "17 3 * * 2")
    d = ws / ".orch/addons/scheduler"
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({"marker": "ADDON-DATA-XYZ"}))
    out1, out2 = e.tmp / "snap-plain.html", e.tmp / "snap-addons.html"
    check(e.sh(["orch", "dashboard", "snapshot", "--out", str(out1)], cwd=ws)[0] == 0, "snapshot failed")
    check(e.sh(["orch", "dashboard", "snapshot", "--out", str(out2), "--with-addons"], cwd=ws)[0] == 0, "snapshot --with-addons failed")
    plain, withadd = out1.read_text(), out2.read_text()
    check("A11 visible ticket" in plain, "ticket missing from the snapshot")
    for needle in ("17 3 * * 2", "ADDON-DATA-XYZ", "orch-scheduler"):
        check(needle not in plain, f"snapshot contains add-on content: {needle}")
    check('"scheduler"' not in plain.split("window.ORCH_SNAPSHOT=", 1)[1].split("</script>", 1)[0], "scheduler named in the snapshot data")
    check("17 3 * * 2" in withadd, "--with-addons has no ticket ext")
    check("ADDON-DATA-XYZ" not in withadd, "add-on data folder leaked into the snapshot")


@scenario("A12")
def a12(e):
    """No add-on on: no scheduler/dashboard trace in CLI help, skills, AGENTS.md or tickets; the commands are refused with the hint."""
    ws = e.ws("Bare")
    h = _help(e, ws).lower()
    for w in ("scheduler", "dashboard", "add-ons:"):
        check(w not in h.replace("orch addon", "").replace("add-ons: add, remove, list", ""), f"--help mentions {w}")
    txt = _tree_text(ws)
    for w in ("scheduler", "dashboard", "wake_at", "--recurring"):
        check(w not in txt, f"skills/AGENTS.md mention {w}")
    t = e.orchj(ws, "ticket", "new", "A12 plain")["id"]
    for cmd in ("scheduler", "dashboard"):
        rc, out, err = e.sh(["orch", cmd, "--help"], cwd=ws)
        check(rc == 2 and (f"orch addon add {cmd}" in err or "is not an orch command" in err), f"orch {cmd}: {rc} {err!r}")
    rc, out, err = e.sh(["orch", "ticket", "new", "x", "--recurring", "* * * * *"], cwd=ws)
    check(rc != 0, "--recurring still accepted")
    lst = e.orchj(ws, "addon", "list")
    check(all(x["active"] is False for x in lst), f"active add-ons in a bare workspace: {lst}")
    check(not (ws / ".orch/addons.json").exists(), "addons.json without any add-on")
    with_dash = e.ws("BareDash")
    check(e.addon_add(with_dash, "dashboard")[0] == 0, "add dashboard")
    check("scheduler" not in _help(e, with_dash).lower() and "scheduler" not in _tree_text(with_dash), "dashboard alone mentions scheduler")
    d1 = e.orchj(with_dash, "ticket", "new", "A12 finished work")["id"]
    e.orch(with_dash, "ticket", "status", d1, "dropped")
    with _dashboard(e, with_dash) as (_, get):
        st = get("/api/state")[1]
        check(any(t["id"] == d1 for t in st["tickets"]), "a finished (dropped) ticket is missing from the dashboard")
        check(not [a for a in st["addons"] if a["dashboard"]], f"tabs with no add-on on: {st['addons']}")
        check(not st["relay"], "Inbox shown without relay")
    return t


@scenario("A13")
def a13(e):
    """Add scheduler: command, help group, skill, AGENTS block and dashboard tab appear and read like the built-ins."""
    ws = e.ws("Looks")
    before_help = _help(e, ws)
    for a in ("dashboard", "scheduler"):
        check(e.addon_add(ws, a)[0] == 0, f"add {a}")
    h = e.sh(["orch", "--help"], cwd=ws)[1]
    check("Add-ons" in h and "scheduler" in h and "dashboard" in h, f"help has no Add-ons group:\n{h}")
    check(h.index("ticket") < h.index("Add-ons"), "Add-ons group not below the core commands")
    check(e.sh(["orch", "scheduler", "--help"], cwd=ws)[0] == 0, "orch scheduler --help")
    rc, out, err = e.sh(["orch", "scheduler", "repeat", "t_nonexist", "* * * * *"], cwd=ws)
    check(rc == 2 and err.startswith("Refused:"), f"refusal style: {rc} {err!r}")
    rc, out, _ = e.sh(["orch", "scheduler", "repeat", "t_nonexist", "* * * * *", "--json"], cwd=ws)
    check(rc == 2 and "error" in json.loads(out), f"--json error shape: {out!r}")
    sk = (ws / ".agents/skills/orch-scheduler/SKILL.md").read_text()
    check(sk.startswith("---\nname: orch-scheduler\n"), "skill front matter")
    core = (ws / ".agents/skills/orch/SKILL.md").read_text()
    check(sk.count("`orch ") >= 3 and core.count("`orch ") >= 3, "skills do not lead with commands")
    check("--recurring" not in sk and "wake_at" not in sk, "old scheduler wording in the skill")
    names = sorted(p.name for p in (ws / ".agents/skills").iterdir() if p.is_dir())
    check({"orch", "orch-dashboard", "orch-scheduler"} <= set(names) and all(n == "orch" or n.startswith("orch-") for n in names), f"skill folder names {names}")
    check((ws / ".claude/skills").is_symlink() and (ws / ".claude/skills/orch-scheduler/SKILL.md").is_file(), ".claude/skills does not show the add-on")
    a = (ws / "AGENTS.md").read_text()
    blk = a.split("<!-- orch:addon:scheduler -->")[1].split("<!-- /orch:addon:scheduler -->")[0]
    check(blk.strip().startswith("## orch-scheduler") and "SKILL.md" in blk and len(blk.strip().splitlines()) <= 6, f"AGENTS block shape: {blk!r}")
    with _dashboard(e, ws) as (base, get):
        st = get("/api/state")[1]
        tabs = {x["name"]: x["dashboard"] for x in st["addons"] if x["dashboard"]}
        check("scheduler" in tabs and tabs["scheduler"]["label"] == "Schedule", f"tabs {tabs}")
        st2, v = get("/api/addon/scheduler")
        check(st2 == 200 and v["state"] == "ok" and v["view"]["schema"] == "orch.addon-view/1", f"scheduler view: {v}")
        check(get("/api/addon/nope")[0] == 404, "unknown add-on tab not 404")
    check(before_help != _help(e, ws), "help unchanged")


@scenario("A14")
def a14(e):
    """Edit a local add-on folder after consent: 'changed on disk', inactive until the user turns it on again."""
    src = _local_addon(e)
    ws = e.ws("Edited")
    check(e.addon_add(ws, src)[0] == 0, "add")
    check(e.sh(["orch", "hello-world", "hello"], cwd=ws)[0] == 0, "works before the edit")
    (src / "src/orch_hello/__main__.py").write_text(
        (src / "src/orch_hello/__main__.py").read_text() + "\n# evil change\n")
    rc, out, err = e.sh(["orch", "hello-world", "hello"], cwd=ws)
    check(rc == 2 and "not turned on" in err, f"changed add-on still ran: {rc} {err!r}")
    check("hello-world" not in _help(e, ws), "changed add-on still in --help")
    check(not [x for x in e.orchj(ws, "addon", "list") if x["name"] == "hello-world" and x["active"]], "still active in list")
    rc, out, err = e.sh(["orch", "update"], cwd=ws, timeout=600)
    check("changed on disk" in (out + err), f"update does not say 'changed on disk': {(err or out)[-300:]}")
    check(e.sh(["orch", "hello-world", "hello"], cwd=ws)[0] == 2, "update re-activated a changed add-on")
    # the user checks it and turns it on again
    check(e.addon_add(ws, src)[0] == 0, "re-add")
    check(e.sh(["orch", "hello-world", "hello"], cwd=ws)[0] == 0, "not active after re-add")


@scenario("A15")
def a15(e):
    """Reserved and duplicate names are refused; a broken manifest is refused; nothing changes."""
    ws = e.ws("Names")
    for n in ("ticket", "addon", "update", "init"):  # relay/publish are built-in add-ons now (A16)
        rc, out, err = e.sh(["orch", "addon", "add", n, "--yes"], cwd=ws)
        check(rc == 2 and "Refused" in err, f"reserved name {n} accepted: {rc} {err!r}")
    src = _local_addon(e)
    bad = e.tmp / "addons" / "reserved"
    shutil.copytree(FIXTURE, bad)
    mf = bad / "src/orch_hello/orch-addon.toml"
    mf.write_text(mf.read_text().replace('name = "hello-world"', 'name = "ticket"'))
    rc, out, err = e.sh(["orch", "addon", "add", str(bad), "--yes"], cwd=ws)
    check(rc == 2 and "core command" in err, f"manifest with a core name: {rc} {err!r}")
    esc = e.tmp / "addons" / "escape"
    shutil.copytree(FIXTURE, esc)
    mf = esc / "src/orch_hello/orch-addon.toml"
    mf.write_text(mf.read_text().replace('skill = "skills/orch-hello-world"', 'skill = "../../../../etc"'))
    rc, out, err = e.sh(["orch", "addon", "add", str(esc), "--yes"], cwd=ws)
    check(rc == 2, f"path escape accepted: {rc} {err!r}")
    check(not (ws / ".orch/addons.json").exists(), "a refused add-on changed the workspace")
    # a second folder with the same add-on name must not replace the first one silently
    check(e.addon_add(ws, src)[0] == 0, "add the first one")
    dup = e.tmp / "addons" / "hello-copy"
    shutil.copytree(FIXTURE, dup)
    rc, out, err = e.sh(["orch", "addon", "add", str(dup), "--yes"], cwd=ws, timeout=600)
    reg = [x for x in json.loads((e.orch_home / "addons.json").read_text()) if x["name"] == "hello-world"]
    check(len(reg) == 1, f"duplicate name registered twice: {reg}")
    if rc == 0:
        check(reg[0]["source"] == str(dup.resolve()), f"duplicate add did not update the single entry: {reg}")
        return "same name from a second folder replaces the single entry (no double)"
    return "duplicate refused"


@scenario("I1", slow=True)
def i1(e):
    """Real installer from git (not the dev checkout), like the owner: install.sh with ORCH_REF=<this commit>,
    then a fresh project, orch init, add dashboard by answering y in a terminal, add scheduler with --yes.
    Both add-ons and orch itself must come from the same commit (no silent reinstall from main)."""
    import os
    import pty

    from lib import Skip

    rc, sha, _ = e.sh(["git", "-C", str(e.repo), "rev-parse", "HEAD"])
    if rc != 0:
        raise Skip("not a git checkout")
    sha = sha.strip()
    d = e.tmp / "i1"
    home, bin_, ws = d / "home", d / "bin", d / "proj"
    for p in (home, bin_, ws):
        p.mkdir(parents=True)
    env = {k: v for k, v in e.env.items() if k != "ORCH_REPO"}
    env.update({"HOME": str(home), "UV_TOOL_DIR": str(d / "uvtools"), "UV_TOOL_BIN_DIR": str(bin_),
                "PATH": f"{bin_}{os.pathsep}{e.path}", "ORCH_HOME": str(e.orch_home / "i1"),
                "ORCH_REPO": "https://github.com/severinlindenmann/orch", "ORCH_REF": sha})
    rc, out, err = e.sh(["sh", str(e.repo / "install.sh")], env=env, timeout=900)
    check(rc == 0, f"install.sh: {(err or out)[-300:]}")
    del env["ORCH_REPO"], env["ORCH_REF"]  # a new terminal: the installer's variables are gone

    def run(*args, stdin=None, timeout=900):
        p = subprocess.run(["orch", *args], cwd=ws, env=env, capture_output=True, text=True, stdin=stdin,
                           timeout=timeout)
        return p.returncode, p.stdout, p.stderr

    check(run("init")[0] == 0, "orch init")
    # a terminal: the consent text is shown and asked; answer y
    master, slave = pty.openpty()
    os.write(master, b"y\n")
    try:
        rc, out, err = run("addon", "add", "dashboard", stdin=slave)
    finally:
        os.close(slave)
        os.close(master)
    check(rc == 0 and "Add it? [y/N]" in err and "Adds the command: orch dashboard" in err, f"add dashboard (tty): {rc} {(err or out)[-300:]}")
    rc, out, err = run("addon", "add", "scheduler", stdin=subprocess.DEVNULL)  # no terminal, no --yes: hint
    check(rc == 2 and "--yes" in err, f"scheduler without --yes: {rc} {(err or out)[-200:]}")
    rc, out, err = run("addon", "add", "scheduler", "--yes")
    check(rc == 0, f"add scheduler --yes: {(err or out)[-300:]}")
    lst = {x["name"]: x["active"] for x in json.loads(run("addon", "list", "--json")[1])}
    check(lst == {"dashboard": True, "scheduler": True, "publish": False, "relay": False}, f"addon list {lst}")
    tools = (d / "uvtools" / "orch-workspace" / "uv-receipt.toml").read_text()
    check(tools.count(sha) >= 3 and "@main" not in tools, f"orch and add-ons not all from {sha[:8]}: {tools[-400:]}")
    rc, out, _ = run("scheduler", "--help")
    check(rc == 0, "orch scheduler --help")


@scenario("A16")
def a16(e):
    """A clean `orch init`: none of publish, relay, dashboard, scheduler in --help, skills or AGENTS.md; their
    commands answer with `orch addon add <name>`. Adding relay brings exactly its command, skill and block."""
    ws = e.ws("Clean")
    help_ = _help(e, ws)
    tree = _tree_text(ws)
    for name in ("publish", "relay", "dashboard", "scheduler"):
        check(f"\n    {name} " not in help_ and f"\n  {name} " not in help_, f"{name} in a clean --help")
        check(f"orch-{name}" not in tree and f"orch {name}" not in tree, f"{name} in a clean skill/AGENTS.md")
        rc, _, err = e.sh(["orch", name, "--help"], cwd=ws)
        # dashboard/scheduler: "not an orch command" when not installed on this computer, else "orch addon add"
        check(rc == 2 and (f"orch addon add {name}" in err or "not an orch command" in err), f"orch {name} while off: {rc} {err[-200:]}")
    rc, out, err = e.sh(["orch", "addon", "add", "relay", "--yes"], cwd=ws)
    check(rc == 0 and "Adds the command: orch relay" in out, f"add relay: {(err or out)[-200:]}")
    check("relay" in _help(e, ws).split("Add-ons:")[1], "relay not under Add-ons in --help")
    check((ws / ".agents/skills/orch-relay/SKILL.md").is_file(), "relay skill missing")
    check("<!-- orch:addon:relay -->" in (ws / "AGENTS.md").read_text(), "relay AGENTS block missing")
    check("publish" not in _help(e, ws), "publish appeared with relay")
    e.orch(ws, "addon", "remove", "relay")
    check("orch-relay" not in _tree_text(ws), "relay left a trace after remove")
