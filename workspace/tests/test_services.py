"""orch start / stop / status: background processes of active add-ons, registry of running workspaces."""

import io
import json
import os
import subprocess
import sys

import pytest
from test_addons import install, make_addon, uv_calls  # noqa: F401  (fixture)

from orch import addons, services

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
            "addons": [{"addon": "hello", "pid": reg[0]["pid"], "url": "http://127.0.0.1:18420"}],
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
    assert code == 0 and "running (pid " in out and str(url) not in out and "\x1b" not in out
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
    assert ".orch/run/" in (proj / ".gitignore").read_text(encoding="utf-8").splitlines()


@NO_WIN_LINKS
@pytest.mark.parametrize("name", [".gitignore", "AGENTS.md", "CLAUDE.md"])
def test_project_files_never_written_through_a_link_outside(proj, tmp_path, name):
    from orch import skills
    from orch.errors import Refused

    victim = tmp_path.parent / f"{tmp_path.name}-victim.txt"
    victim.write_text("keep me", encoding="utf-8")
    (proj / name).symlink_to(victim)
    with pytest.raises(Refused, match="link orch does not write through"):
        {".gitignore": skills.ensure_gitignore, "CLAUDE.md": skills.ensure_claude_md}.get(
            name, lambda r: skills.set_block(r, "x", "body")
        )(proj)
    assert victim.read_text(encoding="utf-8") == "keep me"


@NO_WIN_LINKS
def test_start_refuses_a_gitignore_link_outside(svc, proj, run, tmp_path):
    victim = tmp_path.parent / f"{tmp_path.name}-victim2.txt"
    victim.write_text("keep me", encoding="utf-8")
    (proj / ".gitignore").unlink()
    (proj / ".gitignore").symlink_to(victim)
    code, _, err = run("start")
    assert (
        code == 2
        and "link orch does not write through" in err
        and victim.read_text(encoding="utf-8") == "keep me"
    )


@NO_WIN_LINKS
def test_claude_md_linked_to_agents_md_inside_still_works(proj, run):
    (proj / "AGENTS.md").write_text("# mine\n", encoding="utf-8")
    (proj / "CLAUDE.md").symlink_to("AGENTS.md")
    assert run("init")[0] == 0
    assert (proj / "CLAUDE.md").is_symlink() and "@AGENTS.md" in (proj / "AGENTS.md").read_text(
        encoding="utf-8"
    )


@NO_WIN_LINKS
@pytest.mark.parametrize(
    "name,target",
    [(".gitignore", ".git/config"), ("CLAUDE.md", ".git/hooks/pre-commit"), ("AGENTS.md", ".orch/x")],
)
def test_links_inside_the_project_to_other_files_are_refused(proj, name, target):
    from orch import skills
    from orch.errors import Refused

    t = proj / target
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text("keep me\n", encoding="utf-8")
    (proj / name).symlink_to(t)
    with pytest.raises(Refused, match="link orch does not write through"):
        {".gitignore": skills.ensure_gitignore, "CLAUDE.md": skills.ensure_claude_md}.get(
            name, lambda r: skills.set_block(r, "x", "body")
        )(proj)
    assert t.read_text(encoding="utf-8") == "keep me\n"


@NO_WIN_LINKS
def test_gitignore_never_follows_a_link(proj):
    from orch import skills
    from orch.errors import Refused

    (proj / "AGENTS.md").write_text("x\n", encoding="utf-8")
    (proj / ".gitignore").symlink_to("AGENTS.md")
    with pytest.raises(Refused):
        skills.ensure_gitignore(proj)
