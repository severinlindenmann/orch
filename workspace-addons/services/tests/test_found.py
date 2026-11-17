"""Found on this computer + Manage with orch, against fake platform tools on PATH (runs on any computer).

The fakes (launchctl, systemctl, journalctl, ps, lsof) answer from a JSON state file and write down every call, so a
test can prove that `found` and `list` only read and that `adopt` touches neither the entry nor the job."""

import hashlib
import json
import os
import plistlib
import sys
from pathlib import Path

import pytest
from conftest import CONTRACTS, jrun, validator

SCHEMA = CONTRACTS / "addons" / "services" / "service.schema.json"
TOKEN = "sk-ant-api03-" + "Qw7Er5Ty" * 6

FAKE = r"""#!{python}
import json, os, plistlib, sys
from pathlib import Path
tool = Path(sys.argv[0]).name
sf = Path(os.environ["FAKE_STATE"])
st = json.loads(sf.read_text())
args = sys.argv[1:]
st["calls"].append([tool, *args])
sf.write_text(json.dumps(st))
def out(s): sys.stdout.write(s)
if tool == "launchctl":
    verb = args[0]
    if verb == "print" and args[1].count("/") == 1:
        sys.exit(0)
    target = args[-1]
    label = target.split("/", 2)[-1]
    jobs = st["launchd"]
    if verb == "print":
        j = jobs.get(label)
        if not j or not j.get("loaded"):
            print("Could not find service", file=sys.stderr); sys.exit(113)
        out("state = %s\n" % ("running" if j.get("running") else "not running"))
        if j.get("running"):
            out("pid = %d\n" % j["pid"])
    elif verb == "bootstrap":
        d = plistlib.loads(Path(target).read_bytes())
        j = jobs.setdefault(d["Label"], {{}})
        run = bool(d.get("RunAtLoad") or d.get("KeepAlive"))  # like launchd: loading alone starts nothing
        j.update(loaded=True, running=run, pid=j.get("pid", 5000) + 1)
    elif verb == "bootout":
        jobs.get(label, {{}}).update(loaded=False, running=False)
    elif verb == "kickstart":
        j = jobs[label]; j.update(running=True, pid=j.get("pid", 5000) + 1)
    elif verb in ("enable", "disable"):
        jobs.setdefault(label, {{}})["disabled"] = verb == "disable"
elif tool == "systemctl":
    verb, rest = args[1], args[2:]
    units = st["systemd"]
    if verb == "show-environment":
        sys.exit(0)
    if verb == "list-units":
        for n, u in units.items():
            out("%s loaded %s running x\n" % (n, "active" if u["active"] else "inactive"))
        out("dbus.service loaded active running D-Bus\n")
    elif verb == "show":
        names = [a for a in rest if not a.startswith("-")]
        blocks = []
        for n in names:
            u = units.get(n)
            if n == "dbus.service":
                blocks.append("Id=dbus.service\nFragmentPath=/usr/lib/systemd/user/dbus.service\nActiveState=active")
                continue
            if not u:
                blocks.append("Id=%s\nFragmentPath=\nActiveState=inactive\nMainPID=0" % n); continue
            if len(names) == 1 and "--property=Id" not in " ".join(rest):  # the driver's status call
                print("ActiveState=" + ("active" if u["active"] else "inactive"))
                print("MainPID=" + (str(u["pid"]) if u["active"] else "0"))
                print("ActiveEnterTimestamp=Tue 2026-11-17 16:19:15 UTC")
                print("InactiveEnterTimestamp=Tue 2026-11-17 15:00:00 UTC")
                sys.exit(0)
            blocks.append("\n".join([
                "Id=" + n, "Description=" + u.get("desc", n), "FragmentPath=" + u["path"],
                "ActiveState=" + ("active" if u["active"] else "inactive"),
                "MainPID=" + (str(u["pid"]) if u["active"] else "0"),
                "ActiveEnterTimestamp=Tue 2026-11-17 16:19:15 UTC",
                "UnitFileState=" + ("enabled" if u.get("enabled") else "disabled"),
                "ExecStart={{ path=/usr/bin/python3 ; argv[]=" + " ".join(u["argv"]) + " ; ignore_errors=no }}",
            ]))
        out("\n\n".join(blocks) + "\n")
    elif verb in ("start", "restart"):
        units[rest[0]].update(active=True, pid=units[rest[0]].get("pid", 6000) + 1)
    elif verb == "stop":
        units[rest[0]]["active"] = False
    elif verb in ("enable", "disable"):
        units[rest[0]]["enabled"] = verb == "enable"
    sf.write_text(json.dumps({{**st, "systemd": units}}))
elif tool == "journalctl":
    out("job started\nusing key {token}\njob ready\n")
elif tool == "ps":
    if "-p" in args:
        out("Tue Nov 17 16:19:15 2026\n"); sys.exit(0)
    for p in st["ps"]:
        out("%d %d %s Tue Nov 17 16:19:15 2026 %s\n" % (p["pid"], p["ppid"], p["tty"], " ".join(p["argv"])))
elif tool == "lsof":
    for pid, cwd in st["lsof"].items():
        out("p%s\nfcwd\nn%s\n" % (pid, cwd))
if tool == "launchctl":
    sf.write_text(json.dumps(st))
"""


@pytest.fixture
def tools(tmp_path, monkeypatch, ws):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("launchctl", "systemctl", "journalctl", "ps", "lsof"):
        t = bin_dir / name
        t.write_text(FAKE.format(python=sys.executable, token=TOKEN), encoding="utf-8")
        t.chmod(0o755)
    state = tmp_path / "fake-state.json"
    state.write_text(json.dumps({"calls": [], "launchd": {}, "systemd": {}, "ps": [], "lsof": {}}))
    monkeypatch.setenv("FAKE_STATE", str(state))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}")

    class T:
        def read(self):
            return json.loads(state.read_text(encoding="utf-8"))

        def set(self, **kw):
            d = self.read()
            d.update(kw)
            state.write_text(json.dumps(d), encoding="utf-8")

        def calls(self, tool=None):
            return [c for c in self.read()["calls"] if tool is None or c[0] == tool]

        def clear(self):
            self.set(calls=[])

    return T()


def _platform(monkeypatch, name):
    from orch_services import drivers
    from orch_services.drivers.launchd import Launchd
    from orch_services.drivers.systemd import Systemd

    monkeypatch.setattr(sys, "platform", name)
    monkeypatch.setattr(drivers, "get", lambda: Launchd() if name == "darwin" else Systemd())


@pytest.fixture
def mac(tools, monkeypatch, ws):
    _platform(monkeypatch, "darwin")
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    log = Path.home() / "web-job.log"
    log.write_text(f"web up\nkey is {TOKEN}\nserving\n", encoding="utf-8")

    def plist(label, argv, run_at_load=False, **extra):
        p = agents / f"{label}.plist"
        d = {"Label": label, "ProgramArguments": argv, "RunAtLoad": run_at_load, **extra}
        p.write_bytes(plistlib.dumps(d))
        return p

    web = plist(
        "com.example.web-preview",
        ["/usr/bin/python3", "serve.py", "--token", TOKEN],
        True,
        StandardOutPath=str(log),
        EnvironmentVariables={"API_KEY": "zz-never-read-me-8812"},
    )
    plist("com.example.backup", ["/usr/local/bin/backup-now"])
    plist("com.apple.something", ["/usr/libexec/x"])
    plist("com.google.keystone.agent", ["/x"])
    plist("ch.orch.svc.0123456789abcdef0123456789abcdef.web", ["/x"])
    (agents / "broken.plist").write_text("not a plist", encoding="utf-8")
    tools.set(launchd={"com.example.web-preview": {"loaded": True, "running": True, "pid": 4321}})
    return {"web": web, "agents": agents}


@pytest.fixture
def linux(tools, monkeypatch, ws):
    _platform(monkeypatch, "linux")
    d = Path.home() / ".config" / "systemd" / "user"
    d.mkdir(parents=True)
    for n in ("notes-sync.service", "orch-svc-0123456789abcdef0123456789abcdef-web.service"):
        (d / n).write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")
    tools.set(
        systemd={
            "notes-sync.service": {
                "active": True,
                "pid": 777,
                "enabled": True,
                "desc": "Keeps my notes in sync",
                "path": str(d / "notes-sync.service"),
                "argv": ["/usr/bin/python3", "sync.py"],
            }
        }
    )
    return d


def _tree(*bases):
    """Every file under the folders with a hash of its bytes: a write anywhere shows as a difference."""
    out = {}
    for b in bases:
        for p in sorted(Path(b).rglob("*")):
            if p.is_file() and not p.is_symlink() and p.name != "fake-state.json":
                out[str(p)] = (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
    return out


# ---------------------------------------------------------------- found


def test_found_on_a_mac_lists_the_persons_jobs_and_hides_secrets(cli, mac, tools):
    code, out = jrun(cli, "found")
    assert code == 0, out
    items = {i["id"]: i for i in out["found"]}
    assert set(items) == {"launchd:com.example.web-preview", "launchd:com.example.backup"}
    web = items["launchd:com.example.web-preview"]
    assert web["name"] == "web-preview" and web["running"] is True and web["auto"] is True
    assert web["since"] == "2026-11-17T16:19:15Z" or web["since"].endswith("Z")
    assert web["how"] == {
        "kind": "launchd",
        "label": "com.example.web-preview",
        "path": str(mac["web"]),
        "pid": 4321,
    }
    assert web["what"] == "A job of your account that runs serve.py"
    assert web["command"][-1] == "••••••" and TOKEN not in json.dumps(out)
    assert "zz-never-read-me-8812" not in json.dumps(out)  # environment variables are never read
    backup = items["launchd:com.example.backup"]
    assert backup["running"] is False and backup["since"] is None and backup["name"] == "backup"


def test_found_text_and_nothing_found(cli, mac, tools):
    code, out, _ = cli("found")
    assert code == 0 and "web-preview" in out and "orch services adopt" in out and TOKEN not in out
    for p in mac["agents"].glob("com.example.*"):
        p.unlink()
    code, out = jrun(cli, "found")
    assert code == 0 and out == {"found": []}
    code, out, _ = cli("found")
    assert (
        out.strip() == "Nothing found: orch sees no other background jobs of your account on this computer."
    )


def test_found_on_linux_keeps_only_the_persons_own_units(cli, linux, tools, monkeypatch, tmp_path, ws):
    from orch_services import found

    proc = tmp_path / "proc"
    for pid, cwd in ((900, ws / "app"), (901, tmp_path), (902, ws), (777, ws), (903, ws)):
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "cwd").symlink_to(cwd)
    (ws / "app").mkdir()
    monkeypatch.setattr(found, "PROC", proc)
    tools.set(
        ps=[
            {"pid": 900, "ppid": 1, "tty": "?", "argv": ["node", "server.js", "--key", TOKEN]},
            {"pid": 901, "ppid": 1, "tty": "?", "argv": ["python3", "elsewhere.py"]},  # outside the workspace
            {"pid": 902, "ppid": 1, "tty": "pts/1", "argv": ["zsh"]},  # a terminal
            {"pid": 777, "ppid": 1, "tty": "?", "argv": ["python3", "sync.py"]},  # the unit's own process
            {"pid": 903, "ppid": 1, "tty": "?", "argv": ["/usr/local/bin/orch", "start"]},  # orch's own
        ]
    )
    code, out = jrun(cli, "found")
    assert code == 0, out
    items = {i["id"]: i for i in out["found"]}
    assert set(items) == {"systemd:notes-sync.service", "process:900"}
    unit = items["systemd:notes-sync.service"]
    assert unit["name"] == "notes-sync" and unit["what"] == "Keeps my notes in sync" and unit["auto"] is True
    assert unit["since"] == "2026-11-17T16:19:15Z" and unit["how"]["unit"] == "notes-sync.service"
    proc_item = items["process:900"]
    assert proc_item["name"] == "server.js" and proc_item["how"] == {"kind": "process", "pid": 900}
    assert proc_item["command"][-1] == "••••••" and TOKEN not in json.dumps(out)


def test_on_a_mac_processes_come_from_lsof_and_are_skipped_without_it(
    cli, mac, tools, ws, monkeypatch, tmp_path
):
    tools.set(
        ps=[{"pid": 950, "ppid": 1, "tty": "??", "argv": ["python3", "-m", "watcher"]}],
        lsof={"950": str(ws)},
    )
    _code, out = jrun(cli, "found")
    assert "process:950" in {i["id"] for i in out["found"]}
    (tmp_path / "bin" / "lsof").unlink()
    monkeypatch.setattr("orch_services.found.LSOF", str(tmp_path / "no-lsof"))
    _code, out = jrun(cli, "found")
    assert "process:950" not in {i["id"] for i in out["found"]}


def test_found_and_list_never_write_or_change_anything(cli, mac, tools, ws):
    before = _tree(Path.home(), ws)
    tools.clear()
    for argv in (("found",), ("list",), ("view",)):
        code, _out, _err = cli(*argv)
        assert code == 0
        cli(*argv, "--json")
    assert _tree(Path.home(), ws) == before
    verbs = {c[1] for c in tools.calls("launchctl")}
    assert verbs <= {"print"}, verbs
    assert not (ws / ".orch" / "addons").exists()


def test_found_and_list_never_write_on_linux(cli, linux, tools, ws):
    before = _tree(Path.home(), ws)
    tools.clear()
    for argv in (("found",), ("list",)):
        assert cli(*argv)[0] == 0
    assert _tree(Path.home(), ws) == before
    verbs = {c[2] for c in tools.calls("systemctl")}
    assert verbs <= {"list-units", "show", "show-environment"}, verbs


# ---------------------------------------------------------------- adopt


def test_adopt_on_a_mac_manages_the_job_without_touching_it(cli, mac, tools, ws):
    plist_before = mac["web"].read_bytes()
    tools.clear()
    code, out = jrun(cli, "adopt", "launchd:com.example.web-preview", "--ticket", "DM1-12")
    assert code == 0, out
    assert out["service"]["id"] == "web-preview" and out["service"]["state"] == "running"
    assert "not moved, changed or restarted" in out["next"]
    assert {c[1] for c in tools.calls("launchctl")} <= {"print"}  # adopt itself only reads
    assert mac["web"].read_bytes() == plist_before
    rec = json.loads((ws / ".orch/addons/services/services/web-preview.json").read_text(encoding="utf-8"))
    assert not [e.message for e in validator(SCHEMA).iter_errors(rec)]
    assert rec["made_by"] == {"found": True, "ticket": "DM1-12"}
    assert rec["adopted"] == {"kind": "launchd", "entry": "com.example.web-preview", "path": str(mac["web"])}
    assert TOKEN not in json.dumps(rec)
    # it is in the list now, no longer in found
    code, out = jrun(cli, "list")
    assert out["services"][0]["made_by"] == {"found": True, "ticket": "DM1-12"}
    assert "launchd:com.example.web-preview" not in {i["id"] for i in jrun(cli, "found")[1]["found"]}

    # stop, start, restart and auto act on the existing label; the plist is never rewritten
    target = f"gui/{os.getuid()}/com.example.web-preview"
    tools.clear()
    assert jrun(cli, "stop", "web-preview")[1]["service"]["state"] == "stopped"
    assert ["launchctl", "bootout", target] in tools.calls()
    code, out = jrun(cli, "act", "start", "--", "web-preview")
    assert code == 0 and out["service"]["state"] == "running"
    assert ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(mac["web"])] in tools.calls()
    assert jrun(cli, "restart", "web-preview")[0] == 0
    assert jrun(cli, "auto", "web-preview", "off")[0] == 0
    assert ["launchctl", "disable", target] in tools.calls()
    assert mac["web"].read_bytes() == plist_before
    assert sorted(p.name for p in mac["agents"].iterdir() if p.name.startswith("ch.orch")) == [
        "ch.orch.svc.0123456789abcdef0123456789abcdef.web.plist"
    ]

    # log reads the job's own log through the secret scan
    code, out = jrun(cli, "log", "web-preview")
    assert out["lines"][0] == "web up" and out["lines"][-1] == "serving" and TOKEN not in json.dumps(out)

    # remove only forgets it
    tools.clear()
    code, out = jrun(cli, "remove", "web-preview")
    assert code == 0 and out["forgotten"] is True and "left as it is" in out["next"]
    assert tools.calls() == [] and mac["web"].read_bytes() == plist_before
    assert jrun(cli, "list")[1]["services"] == []


def test_adopt_on_linux_and_log_from_the_journal(cli, linux, tools, ws):
    st = tools.read()
    st["systemd"]["notes-sync.service"]["argv"] = ["/no/such/program-zz", "sync.py"]
    tools.set(systemd=st["systemd"])
    code, out = jrun(cli, "act", "adopt", "--", "systemd:notes-sync.service")
    assert code == 0, out
    rec = json.loads((ws / ".orch/addons/services/services/notes-sync.json").read_text(encoding="utf-8"))
    assert rec["made_by"] == {"found": True} and rec["auto"] is True
    assert rec["adopted"]["entry"] == "notes-sync.service"
    unit_file = linux / "notes-sync.service"
    before = unit_file.read_bytes()
    tools.clear()
    assert jrun(cli, "restart", "notes-sync")[0] == 0
    assert jrun(cli, "auto", "notes-sync", "off")[0] == 0
    calls = tools.calls("systemctl")
    assert ["systemctl", "--user", "restart", "notes-sync.service"] in calls
    assert ["systemctl", "--user", "disable", "notes-sync.service"] in calls
    assert not any("daemon-reload" in c for c in calls)  # nothing was rewritten
    assert unit_file.read_bytes() == before
    code, out = jrun(cli, "log", "notes-sync")
    assert out["lines"][0] == "job started" and TOKEN not in json.dumps(out)
    assert jrun(cli, "remove", "notes-sync")[1]["forgotten"] is True and unit_file.read_bytes() == before


def test_adopt_names_ids_and_refusals(cli, mac, tools, ws):
    code, out = jrun(cli, "adopt", "launchd:com.example.backup", "--name", "Nightly backup")
    assert (
        code == 0 and out["service"]["id"] == "nightly-backup" and out["service"]["name"] == "Nightly backup"
    )
    code, out = jrun(cli, "adopt", "launchd:com.example.ghost")
    assert code == 2 and "orch services found" in out["error"]
    code, out = jrun(cli, "adopt", "../../etc")
    assert code == 2 and "is not a found service" in out["error"]
    code, out = jrun(cli, "adopt", "launchd:com.example.web-preview", "--id", "nightly-backup")
    assert code == 2 and "--id" in out["error"]


def test_a_bare_process_is_never_adopted_or_stopped(cli, mac, tools, ws):
    tools.set(
        ps=[{"pid": 960, "ppid": 1, "tty": "??", "argv": ["node", "dev.js", TOKEN]}],
        lsof={"960": str(ws)},
    )
    tools.clear()
    code, out = jrun(cli, "adopt", "process:960")
    assert code == 2 and "orch services add" in out["error"] and "stop it yourself" in out["error"]
    assert TOKEN not in out["error"]
    assert not (ws / ".orch/addons/services/services").exists()
    assert {c[1] for c in tools.calls("launchctl")} <= {"print"}


def test_a_ticket_key_resolves_even_when_the_core_cannot_be_asked(ws, monkeypatch):
    """CI 17 Nov: the core's lookup failed with an unexpected error and the key was reported as missing."""
    from orch import tickets

    from orch_services import cli

    def broken(root, ref):
        raise RuntimeError("core not usable here")

    monkeypatch.setattr(tickets, "resolve", broken)
    assert cli._ticket_key(ws, "dm1-12") == "DM1-12"


def test_adopt_refuses_a_name_with_a_secret_and_found_masks_names_and_descriptions(cli, linux, tools, ws):
    # review ORCH-378: adopt saved --name without the secret check add has; a unit description was shown as is
    st = tools.read()
    st["systemd"]["notes-sync.service"]["desc"] = f"Sync with key {TOKEN}"
    tools.set(systemd=st["systemd"])
    code, out = jrun(cli, "found")
    assert code == 0 and TOKEN not in json.dumps(out)
    assert out["found"][0]["what"] == "••••••"
    code, out = jrun(cli, "adopt", "systemd:notes-sync.service", "--name", f"Notes {TOKEN}")
    assert code == 2 and "secret" in out["error"] and TOKEN not in json.dumps(out)
    assert not (ws / ".orch/addons/services/services").is_dir() or not list(
        (ws / ".orch/addons/services/services").iterdir()
    )


def test_adopt_takes_the_page_id_of_a_found_job_with_capitals(cli, mac, tools, ws):
    # review ORCH-378: the page gives a label with capitals a hashed id; Manage with orch must still find the job
    from orch_services.found import page_id
    from orch_services.view import build

    mac["agents"].joinpath("ch.Example.Forwarder.plist").write_bytes(
        plistlib.dumps({"Label": "ch.Example.Forwarder", "ProgramArguments": ["/usr/local/bin/fwd"]})
    )
    found = jrun(cli, "found")[1]["found"]
    view = build(ws, ([], 0, None), found=found)
    vid = page_id("launchd:ch.Example.Forwarder")
    items = {i["id"]: i for i in view["blocks"][0]["groups"][-1]["items"]}
    fwd = items[vid]
    assert fwd["id"] == vid and vid.startswith("found-")
    assert fwd["panel"]["buttons"][0]["action"]["args"] == {"verb": "adopt", "target": vid}
    code, out = jrun(cli, "act", "adopt", "--", vid)
    assert code == 0, out
    rec = json.loads((ws / ".orch/addons/services/services" / f"{out['service']['id']}.json").read_text())
    assert rec["adopted"]["entry"] == "ch.Example.Forwarder"
    code, out = jrun(cli, "adopt", "found-000000000000")
    assert code == 2 and "no found service" in out["error"]


def test_start_on_a_taken_over_job_without_run_at_load_really_runs_it(cli, mac, tools, ws):
    # ORCH-371 bug 3: bootstrap only loads such a job; start answered "did not stay running"
    assert jrun(cli, "adopt", "launchd:com.example.backup")[0] == 0
    target = f"gui/{os.getuid()}/com.example.backup"
    tools.clear()
    code, out = jrun(cli, "start", "backup")
    assert code == 0 and out["service"]["state"] == "running", out
    assert ["launchctl", "kickstart", target] in tools.calls()


def test_orchs_own_background_pages_are_never_found(cli, mac, tools, ws):
    # ORCH-371 bug 2: orch starts its pages as `Python -P -m orch_dashboard ...` (macOS framework Python)
    py = "/opt/homebrew/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
    tools.set(
        ps=[
            {
                "pid": 960,
                "ppid": 1,
                "tty": "??",
                "argv": [py, "-P", "-m", "orch_dashboard", "--dir", str(ws)],
            },
            {"pid": 961, "ppid": 1, "tty": "??", "argv": [py, "-P", "-m", "orch_automation", "run"]},
            {"pid": 962, "ppid": 1, "tty": "??", "argv": [py, "-P", "watcher.py"]},
        ],
        lsof={"960": str(ws), "961": str(ws), "962": str(ws)},
    )
    found = {i["id"]: i for i in jrun(cli, "found")[1]["found"]}
    assert "process:960" not in found and "process:961" not in found
    assert found["process:962"]["name"] == "watcher.py"  # an interpreter shows the script, also as Python
