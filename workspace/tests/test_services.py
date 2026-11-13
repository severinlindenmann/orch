"""orch start / stop / status: background processes of active add-ons, registry of running workspaces."""

import io
import json
import os
import subprocess
import sys

import pytest
from test_addons import install, make_addon, uv_calls  # noqa: F401  (fixture)

from orch import addons, services, skills

NO_WIN_LINKS = pytest.mark.skipif(os.name == "nt", reason="file symlinks need admin rights on Windows")

SVC_MAIN = """\
import json, os, sys
from pathlib import Path
f = Path(os.environ["ORCH_ROOT"], "svc.txt")
cmd = sys.argv[1]
if cmd == "start":
    if Path(os.environ["ORCH_ROOT"], "fail.txt").exists():
        print("Refused: port is busy\x1b]0;evil\x07", file=sys.stderr)
        sys.exit(2)
    f.write_text("on", encoding="utf-8")
    pref = os.environ.get("ORCH_PREFERRED_PORT", "-")
    Path(os.environ["ORCH_ROOT"], "pref.txt").write_text(pref, encoding="utf-8")
    bad = Path(os.environ["ORCH_ROOT"], "bad.json")
    over = json.loads(bad.read_text(encoding="utf-8")) if bad.exists() else {}
    print(json.dumps({"running": True, "pid": int(os.environ["TEST_ALIVE_PID"]), "url": "http://127.0.0.1:18420",
                      **over}))
elif cmd == "stop":
    was = f.exists()
    f.unlink(missing_ok=True)
    print(json.dumps({"stopped": was}))
elif cmd == "status":
    print(json.dumps({"running": f.exists()}))
"""


@pytest.fixture
def svc(proj, run, tmp_path, monkeypatch, request):
    """Add-on 'hello' with a background service, plus 'quiet' without one; both on in proj."""
    request.getfixturevalue("uv_calls")
    monkeypatch.setenv(
        "TEST_ALIVE_PID", str(os.getpid())
    )  # a pid that stays alive (getppid is a launcher on Windows)
    folder = make_addon(tmp_path / "s", bg=True)
    (folder / "src/orch_hello/__main__.py").write_text(SVC_MAIN, encoding="utf-8")
    quiet = make_addon(tmp_path / "q", name="quiet")
    for f in (folder, quiet):
        monkeypatch.syspath_prepend(str(f / "src"))
    monkeypatch.setenv("PYTHONPATH", f"{folder / 'src'}{__import__('os').pathsep}{quiet / 'src'}")
    monkeypatch.setattr(addons, "_entry_points", lambda: {"hello": "orch_hello", "quiet": "orch_quiet"})
    assert run("init")[0] == 0
    install(run, folder)
    install(run, quiet)
    return folder


def _second(run, monkeypatch, tmp_path, folder, name="other"):
    ws = tmp_path.parent / f"{tmp_path.name}-{name}" / name  # outside proj (proj is tmp_path)
    ws.mkdir(parents=True)
    monkeypatch.chdir(ws)
    assert run("init")[0] == 0
    install(run, folder)
    return ws


def test_start_starts_only_background_addons_and_records_them(svc, proj, run):
    code, out, err = run("start")
    assert code == 0, err
    assert f"Started in {proj.name}:" in out and "hello" in out and "http://127.0.0.1:18420" in out
    assert "quiet" not in out
    assert (proj / "svc.txt").exists()
    reg = json.loads(services.running_path().read_text(encoding="utf-8"))
    assert [(e["workspace"], e["name"], e["addon"]) for e in reg] == [
        (str(proj.resolve()), proj.name, "hello")
    ]
    code, out, _ = run("status", "--json")
    assert json.loads(out) == [
        {
            "workspace": str(proj.resolve()),
            "name": proj.name,
            "addons": [
                {
                    "addon": "hello",
                    "name": "hello",
                    "running": True,
                    "since": reg[0]["started_at"],
                    "last_seen": json.loads(out)[0]["addons"][0]["last_seen"],
                    "pid": reg[0]["pid"],
                    "url": "http://127.0.0.1:18420",
                }
            ],
            "icon": None,
            "color": None,
        }
    ]
    run("start")  # again: one entry, not two
    assert len(json.loads(services.running_path().read_text(encoding="utf-8"))) == 1


def test_start_json_and_failure(svc, proj, run):
    (proj / "fail.txt").write_text("x", encoding="utf-8")
    code, out, err = run("start", "--json")
    assert code == 2 and "hello did not start" in err
    rows = json.loads(out.split('\n{"error"')[0])["addons"]
    assert rows == [
        {"addon": "hello", "running": False, "error": "port is busy]0;evil"}
    ]  # control chars gone
    assert services.status() == []


def test_start_outside_a_workspace_is_refused(proj, run, tmp_path, monkeypatch):
    out = tmp_path.parent / f"{tmp_path.name}-plain"
    out.mkdir()
    monkeypatch.chdir(out)
    code, _, err = run("start")
    assert code == 2 and "No orch workspace here" in err


def test_nothing_to_start(proj, run):
    run("init")
    code, out, _ = run("start")
    assert code == 0 and "Nothing to start" in out


def test_stop_inside_a_workspace_stops_that_one(svc, proj, run, tmp_path, monkeypatch):
    run("start")
    ws2 = _second(run, monkeypatch, tmp_path, svc)
    run("start")
    monkeypatch.chdir(proj)
    code, out, _ = run("stop")
    assert code == 0 and f"Stopped in {proj.name}: hello" in out
    assert not (proj / "svc.txt").exists() and (ws2 / "svc.txt").exists()
    assert [w["name"] for w in services.status()] == ["other"]


def test_stop_by_name_path_and_all(svc, proj, run, tmp_path, monkeypatch):
    run("start")
    ws2 = _second(run, monkeypatch, tmp_path, svc)
    run("start")
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    assert run("stop", "nosuch")[0] == 2
    code, out, _ = run("stop", "other")
    assert code == 0 and not (ws2 / "svc.txt").exists() and (proj / "svc.txt").exists()
    code, out, _ = run("stop", "--all", "--json")
    assert code == 0 and [d["workspace"] for d in json.loads(out)] == [str(proj.resolve())]
    assert not (proj / "svc.txt").exists() and services.status() == []
    code, out, _ = run("status")
    assert "Nothing runs in the background" in out


def test_stop_outside_asks_which(svc, proj, run, tmp_path, monkeypatch):
    run("start")
    ws2 = _second(run, monkeypatch, tmp_path, svc)
    run("start")
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    code, _, err = run("stop")  # no terminal: refused with the non-interactive forms
    assert code == 2 and "orch stop --all" in err

    class Tty(io.StringIO):
        def isatty(self):
            return True

    names = sorted([proj.name, "other"], key=str.lower)
    monkeypatch.setattr(sys, "stdin", Tty(f"{names.index('other') + 1}\n"))
    code, out, _ = run("stop")
    assert code == 0 and "Running workspaces:" in out and "  1  " in out and "  2  " in out
    assert "Stopped in other: hello" in out and not (ws2 / "svc.txt").exists() and (proj / "svc.txt").exists()
    monkeypatch.setattr(sys, "stdin", Tty("\n"))
    code, out, _ = run("stop")
    assert code == 0 and "Nothing was stopped" in out and (proj / "svc.txt").exists()
    monkeypatch.setattr(sys, "stdin", Tty("all\n"))
    assert run("stop")[0] == 0 and services.status() == []


def test_pick_inside_a_workspace(svc, proj, run, monkeypatch):
    run("start")

    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Tty("1\n"))
    code, out, _ = run("stop", "--pick")
    assert code == 0 and "Running workspaces:" in out and not (proj / "svc.txt").exists()


def test_dead_pids_are_pruned(proj):
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    services._save(
        [
            {"workspace": str(proj), "name": "x", "addon": "hello", "pid": p.pid},
            {"workspace": str(proj), "name": "x", "addon": "keep", "pid": __import__("os").getpid()},
        ]
    )
    assert [e["addon"] for e in services.running()] == ["keep"]
    assert len(json.loads(services.running_path().read_text(encoding="utf-8"))) == 1


def test_start_stop_status_are_reserved_names():
    assert {"start", "stop", "status"} <= addons.RESERVED


@pytest.mark.parametrize(
    "url",
    [
        "http://evil.example:80/",
        "https://127.0.0.1:8420",
        "http://127.0.0.1:8420/\x1b[2J",
        "javascript:alert(1)",
        42,
    ],
)
def test_only_local_urls_are_printed_or_opened(svc, proj, run, monkeypatch, url):
    (proj / "bad.json").write_text(json.dumps({"url": url}), encoding="utf-8")
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u))
    code, out, _ = run("start")
    assert code == 0 and "running (pid " in out and "\x1b" not in out
    # a non-text url (42) is checked by shape: its digits can legitimately occur in a pid or a path
    assert "://" not in out and (not isinstance(url, str) or url not in out)
    assert opened == [] and all("url" not in a for w in services.status() for a in w["addons"])


@pytest.mark.parametrize("pid", [-1, 0, 1, True, "12"])
def test_bad_pids_from_an_addon_are_not_recorded(svc, proj, run, pid):
    (proj / "bad.json").write_text(json.dumps({"pid": pid}), encoding="utf-8")
    assert run("start")[0] == 0
    assert services.status() == []
    assert not any(services.pid_alive(p) for p in (-1, 0, 1))


def test_add_on_error_text_has_no_escape_sequences(svc, proj, run):
    (proj / "fail.txt").write_text("x", encoding="utf-8")
    code, out, err = run("start")
    assert code == 2 and "port is busy" in out and "\x1b" not in out and "\x07" not in out


def test_start_keeps_runtime_files_out_of_git(svc, proj, run):
    run("start")
    assert "run/" in (proj / ".orch/.gitignore").read_text(encoding="utf-8").splitlines()
    assert not (proj / ".gitignore").exists()  # the team's .gitignore is not orch's


@NO_WIN_LINKS
@pytest.mark.parametrize("name", [".orch/.gitignore", "CLAUDE.local.md"])
def test_local_files_never_written_through_a_link(proj, tmp_path, name):

    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    (proj / ".orch").mkdir()
    (proj / name).symlink_to(victim)
    skills.set_block(proj, "orch", "x")
    try:
        skills.apply_agent_files(proj)
    except skills.Refused:
        pass
    assert victim.read_text(encoding="utf-8") == "keep"


@NO_WIN_LINKS
def test_a_link_for_orch_gitignore_makes_orch_refuse_secrets_without_git(proj, tmp_path):
    from orch import net

    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    (proj / ".orch").mkdir()
    (proj / ".orch/.gitignore").symlink_to(victim)
    with pytest.raises(skills.Refused, match="Nothing was stored"):
        net.write_json(proj / ".orch/secrets/x.json", {"t": 1}, True)
    assert victim.read_text(encoding="utf-8") == "keep"


def test_status_says_when_an_addon_is_not_running(svc, proj, run):
    run("start")
    run("stop")
    code, out, _ = run("status", "--json")
    row = json.loads(out)[0]["addons"][0]
    assert row["name"] == "hello" and row["running"] is False and row["since"] is None and row["last_seen"]
    code, out, _ = run("status")
    assert "hello" in out and "not running (last seen just now) - start it: orch start" in out


def test_ago_words():
    assert services.ago(None) == "never seen"
    from datetime import UTC, datetime, timedelta

    def at(**kw):
        return (datetime.now(UTC) - timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%SZ")

    assert services.ago(at(hours=3)) == "3 h ago"
    assert services.ago(at(minutes=10)) == "10 min ago"
    assert services.ago(at(days=3)) == "3 d ago"


def test_restart_reuses_the_last_port(svc, proj, run):
    pref = proj / "pref.txt"
    assert run("start")[0] == 0
    assert pref.read_text() == "-"  # first start: no history
    assert services.last_port(proj, "hello") == 18420
    assert run("stop")[0] == 0
    assert services.last_port(proj, "hello") == 18420  # kept across stop
    assert run("start")[0] == 0
    assert pref.read_text() == "18420"


def test_sticky_port_follows_the_port_it_really_got(svc, proj, run):
    assert run("start")[0] == 0
    run("stop")
    (proj / "bad.json").write_text(json.dumps({"url": "http://127.0.0.1:19999"}), encoding="utf-8")
    assert run("start")[0] == 0  # the old one was taken: the add-on fell back to another
    assert services.last_port(proj, "hello") == 19999
    run("stop")
    (proj / "bad.json").unlink()
    assert run("start")[0] == 0
    assert (proj / "pref.txt").read_text() == "19999"


def test_bad_port_file_is_ignored(svc, proj, run):
    services._ports_path().parent.mkdir(parents=True, exist_ok=True)
    services._ports_path().write_text(json.dumps({services._port_key(proj, "hello"): 22}), encoding="utf-8")
    assert services.last_port(proj, "hello") is None
    services._ports_path().write_text("not json", encoding="utf-8")
    assert services.last_port(proj, "hello") is None
    assert run("start")[0] == 0
    assert (proj / "pref.txt").read_text() == "-"
