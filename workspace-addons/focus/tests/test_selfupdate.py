"""After an update replaced the installed files, a running server restarts itself on the next page request:
same pid, same port, new code (the new page's files are served, no 404 blank page)."""

import contextlib
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

import pytest

import orch_focus
from orch_focus import selfupdate, service

PKG = "orch_focus"
NEW = "/web/newfile.js" if PKG == "orch_focus" else "/newfile.js"
SRC = Path(orch_focus.__file__).parent


def get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except OSError:  # the process is being replaced: not listening for a moment
        return 0, b""


@pytest.fixture
def build(tmp_path, monkeypatch):
    """A copy of the package that the servers run from (v1), plus a helper that turns it into v2."""
    lib = tmp_path / "lib"
    shutil.copytree(SRC, lib / PKG, ignore=shutil.ignore_patterns("__pycache__"))
    ui = Path(__file__).resolve().parents[3] / "workspace" / "src"  # orch_ui, as the add-on tests find it
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(lib), str(ui), os.environ.get("PYTHONPATH", "")]))

    def v2():
        (lib / PKG / "web" / "newfile.js").write_text("window.NEW = 1;\n")
        server = lib / PKG / "server.py"
        s = server.read_text()
        s = s.replace('"helpers.js"', '"helpers.js", "newfile.js"', 1)
        server.write_text(s + "\n# v2\n")

    return v2


def stop(root):
    with contextlib.suppress(Exception):
        service.stop(root)


def test_old_server_restarts_itself_and_serves_the_new_files(tmp_path, build, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "launchd-home"))  # the starter's HOME is not the caller's
    roots = []
    for n in ("Pilatus", "Rigi"):
        r = tmp_path / n
        (r / ".orch").mkdir(parents=True)
        roots.append(r)
    started = {}
    try:
        for r in roots:
            info = service.start(r)
            started[r] = info
            assert get(info["port"], NEW)[0] == 404  # old build
        build()
        for r in roots:
            info = started[r]
            code, body = get(info["port"], "/")
            assert code == 200 and b"restarting" in body  # the update is noticed on the page request
            end = time.time() + 40
            while time.time() < end:
                code, body = get(info["port"], NEW)
                if code == 200:
                    break
                time.sleep(0.3)
            assert code == 200 and b"window.NEW" in body
            now = service.running(r)  # still verified as ours: same pid, same port, same nonce
            assert now == {"pid": info["pid"], "port": info["port"]}
    finally:
        for r in roots:
            stop(r)


def test_stamp_is_cached_and_changes_with_the_files(tmp_path, monkeypatch):
    monkeypatch.setattr(selfupdate, "stamp", lambda: ("v1",))
    monkeypatch.setattr(selfupdate, "_START", ("v1",))
    selfupdate._cache.update(at=-1e9, stamp=None)
    assert selfupdate.changed(now=100.0) is False
    monkeypatch.setattr(selfupdate, "stamp", lambda: ("v2",))
    assert selfupdate.changed(now=100.5) is False  # cached for 2 s
    assert selfupdate.changed(now=103.0) is True


def test_new_argv_is_rebuilt_isolated_and_keeps_the_port():
    argv = ["python", "-m", PKG, "--dir", "/w", "serve", "--ready-file", "/r.json", "--port", "8420", "--auto-port"]
    want = [sys.executable, "-P", "-m", PKG, "--dir", "/w", "serve", "--port", "8431"]
    assert selfupdate.new_argv(argv, 8431) == want  # -P added even when the old process had none
    assert selfupdate.new_argv([*argv[:-3], "--port=1"], 9) == [*want[:-1], "9"]
    assert selfupdate.new_argv(["python", "server.py"], 1) is None  # not started as -m <package>
    assert selfupdate.new_argv(["python", "-m", "other", "serve"], 1) is None


def _reset(monkeypatch, stamps):
    it = iter(stamps)
    monkeypatch.setattr(selfupdate, "stamp", lambda: next(it, stamps[-1]))
    monkeypatch.setattr(selfupdate, "_START", ("v1",))
    monkeypatch.setattr(selfupdate, "_state", {"restarting": False, "failed": None, "thread": None})
    selfupdate._cache.update(at=-1e9, stamp=None)
    monkeypatch.setattr(sys, "orig_argv", ["python", "-m", PKG, "--dir", "/w", "serve"], raising=False)


def test_exec_is_isolated_and_leaves_the_workspace_folder(monkeypatch):
    _reset(monkeypatch, [("v2",)])
    seen = {}
    monkeypatch.setattr(selfupdate, "_runs_new_code", lambda: True)
    monkeypatch.setattr(selfupdate.os, "chdir", lambda d: seen.setdefault("chdir", Path(d)))
    monkeypatch.setattr(selfupdate.os, "execv", lambda exe, argv: seen.update(exe=exe, argv=argv))
    assert selfupdate.restart(8431, delay=0)
    selfupdate._state["thread"].join(5)
    assert seen["argv"][:4] == [sys.executable, "-P", "-m", PKG]  # no working-folder imports
    assert seen["chdir"] == SRC.parent  # before the exec, never the workspace folder


def test_import_check_uses_the_same_isolation(monkeypatch):
    calls = []

    class R:
        returncode = 0

    monkeypatch.setattr(selfupdate.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)) or R())
    assert selfupdate._runs_new_code()
    cmd, kw = calls[0]
    assert cmd[:2] == [sys.executable, "-P"] and kw["cwd"] == SRC.parent and "env" not in kw  # same env as the exec


def test_broken_new_build_is_checked_once_and_the_normal_page_is_served(monkeypatch):
    _reset(monkeypatch, [("v2",)])
    checks = []
    monkeypatch.setattr(selfupdate, "_runs_new_code", lambda: checks.append(1) or False)
    monkeypatch.setattr(selfupdate.os, "execv", lambda *a: pytest.fail("exec of a broken build"))

    class H:
        def __init__(self):
            self.sent = []

        server = type("S", (), {"server_address": ("127.0.0.1", 8431)})()

        def _send(self, code, body, ctype):
            self.sent.append(body)

    h = H()
    assert selfupdate.answer(h) is True and b"restarting" in h.sent[0]  # the first request starts the check
    selfupdate._state["thread"].join(5)
    for _ in range(5):  # then the normal page, no new spawn, until the files change again
        selfupdate._cache["at"] = -1e9
        assert selfupdate.answer(h) is False
    assert checks == [1]
    # the files change again: one more check
    monkeypatch.setattr(selfupdate, "stamp", lambda: ("v3",))
    selfupdate._cache["at"] = -1e9
    assert selfupdate.answer(h) is True
    selfupdate._state["thread"].join(5)
    assert checks == [1, 1]


def test_concurrent_requests_start_one_restart(monkeypatch):
    import threading

    _reset(monkeypatch, [("v2",)])
    gate = threading.Event()
    checks = []
    monkeypatch.setattr(selfupdate, "_runs_new_code", lambda: checks.append(1) or gate.wait(5) and False)
    results = []
    ts = [threading.Thread(target=lambda: results.append(selfupdate.restart(1, delay=0))) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    gate.set()
    selfupdate._state["thread"].join(5)
    assert results.count(True) == 1 and checks == [1]
