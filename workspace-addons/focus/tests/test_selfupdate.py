"""After an update replaced the installed files, a running server restarts itself on the next page request:
same pid, same port, new code (the new page's files are served, no 404 blank page)."""

import contextlib
import os
import shutil
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


def test_new_argv_keeps_the_port_and_drops_ready_file_and_auto_port():
    argv = [
        "python",
        "-P",
        "-m",
        PKG,
        "--dir",
        "/w",
        "serve",
        "--ready-file",
        "/r.json",
        "--port",
        "8420",
        "--auto-port",
    ]
    assert selfupdate.new_argv(argv, 8431) == [
        "python",
        "-P",
        "-m",
        PKG,
        "--dir",
        "/w",
        "serve",
        "--port",
        "8431",
    ]
    assert selfupdate.new_argv([*argv[:-3], "--port=1"], 9) == [*argv[:7], "--port", "9"]
