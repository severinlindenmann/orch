"""Structural test (lane C's I11a): with a trusted throwaway ORCH_HOME, NO command opens anything under
the account's default orch home <Z>/.orch-tool for writing (write-mode open, mkdir, rename, unlink, rmtree).
Reads of trust state are allowed. The hook raises a BaseException (so no `except Exception` hides it) and also
records every hit."""

import builtins
import contextlib
import io
import os
import shutil
from pathlib import Path

import pytest

from orch import addons, cli, services
from orch import humanproof as hp

WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


class AccountHomeWritten(BaseException):
    pass


@pytest.fixture
def fsguard(tmp_path, monkeypatch):
    """A faked account home Z with a trusted throwaway ORCH_HOME and a workspace; installs the write hook."""
    z = tmp_path / "Z"
    z.mkdir()
    watched = os.path.realpath(z / ".orch-tool")
    orch_home = z / "lane-home"
    orch_home.mkdir()
    ws = z / "work" / "ws"
    (ws / ".orch").mkdir(parents=True)
    hits: list[str] = []

    def under(p) -> bool:
        try:
            full = os.path.realpath(os.fspath(p))
        except (TypeError, ValueError):
            return False
        return full == watched or full.startswith(watched + os.sep)

    def hit(kind, p):
        hits.append(f"{kind} {p}")
        raise AccountHomeWritten(f"{kind} {p}")

    real_open, real_os_open = builtins.open, os.open

    def open_(file, mode="r", *a, **k):
        if isinstance(file, (str, bytes, os.PathLike)) and any(c in mode for c in "wax+") and under(file):
            hit("open", file)
        return real_open(file, mode, *a, **k)

    def os_open(path, flags, *a, **k):
        if flags & WRITE_FLAGS and "dir_fd" not in k and under(path):
            hit("os.open", path)
        return real_os_open(path, flags, *a, **k)

    monkeypatch.setattr(builtins, "open", open_)
    monkeypatch.setattr(io, "open", open_)
    monkeypatch.setattr(os, "open", os_open)
    for name in ("mkdir", "rmdir", "unlink", "remove", "makedirs"):
        orig = getattr(os, name)

        def wrap(path, *a, _o=orig, _n=name, **k):
            if under(path):
                hit(_n, path)
            return _o(path, *a, **k)

        monkeypatch.setattr(os, name, wrap)
    for name in ("rename", "replace"):
        orig = getattr(os, name)

        def wrap2(src, dst, *a, _o=orig, _n=name, **k):
            if under(src) or under(dst):
                hit(_n, f"{src} -> {dst}")
            return _o(src, dst, *a, **k)

        monkeypatch.setattr(os, name, wrap2)
    orig_rmtree = shutil.rmtree

    def rmtree(path, *a, **k):
        if under(path):
            hit("rmtree", path)
        return orig_rmtree(path, *a, **k)

    monkeypatch.setattr(shutil, "rmtree", rmtree)

    monkeypatch.setattr(addons, "real_home", lambda: z)
    monkeypatch.setenv("ORCH_HOME", str(orch_home))
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    monkeypatch.setenv("HOME", str(tmp_path / "X"))
    for k in list(os.environ):
        if k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT") or k.startswith("CODEX_"):
            monkeypatch.delenv(k)
    monkeypatch.chdir(ws)
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    monkeypatch.setattr(addons, "reexec", lambda a: None)
    monkeypatch.setattr(addons, "run_uv", lambda a: None)
    monkeypatch.setattr(addons, "_reinstall", lambda *a, **k: True)
    yield z, orch_home, ws, hits
    assert hits == [], hits


def _cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(list(argv))
    return code, out.getvalue()


def test_the_hook_catches_a_write(fsguard):
    z, _, _, hits = fsguard
    with pytest.raises(AccountHomeWritten):
        Path(z / ".orch-tool" / "x").write_text("a")
    assert hits and hits.pop()  # expected here: clear so the fixture's final check passes
    # reads of trust state are fine
    assert not (z / ".orch-tool").exists()


def test_addon_commands(fsguard):
    z, orch_home, ws, _ = fsguard
    assert _cli("addon", "list")[0] == 0
    assert _cli("addon", "add", "focus", "--yes")[0] in (0, 2)
    assert _cli("addon", "remove", "focus")[0] in (0, 2)
    assert not (z / ".orch-tool").exists()


def test_start_and_stop(fsguard):
    z, orch_home, ws, _ = fsguard
    assert services.running_path() == orch_home / "running.json"
    assert _cli("start", "--no-open")[0] in (0, 2)
    assert _cli("status")[0] == 0
    assert _cli("stop", "--all")[0] in (0, 2)
    assert not (z / ".orch-tool").exists()


def test_update(fsguard):
    z, orch_home, ws, _ = fsguard
    addons._save_registry([{"name": "focus", "source": "built-in", "version": "0.1.0"}])
    assert _cli("update")[0] in (0, 2)
    assert (orch_home / "addons.json").is_file()
    assert not (z / ".orch-tool").exists()


def test_relay_connect_and_refresh(fsguard):
    from fakes import make_relay

    z, orch_home, ws, _ = fsguard
    srv = make_relay()
    try:
        assert _cli("relay", "connect", srv.url, "--workspace", "ws_aaaaaaaaaa", "--token", srv.token)[0] in (
            0,
            2,
        )
        _cli("relay", "refresh")
        _cli("relay", "status")
    finally:
        srv.stop()
    assert not (z / ".orch-tool").exists()


def test_proof_mint_and_verify_on_the_test_path(fsguard, monkeypatch):
    """The dev/test proof path writes its key and nonce store to the TEST home only, never to Z/.orch-tool."""
    z, orch_home, ws, _ = fsguard
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    prefix = z / ".orch-test"
    prefix.mkdir()
    tws = prefix / "ws"
    (tws / ".orch").mkdir(parents=True)
    monkeypatch.setenv("ORCH_HOME", str(prefix / "home"))
    (prefix / "home").mkdir()
    key = hp.human_key(tws)
    pr = hp.mint(key, hp.new_payload("run.takeover", "t_abc123", "human:pat"))
    assert hp.verify_and_consume(tws, pr, "run.takeover", "t_abc123") == "human:pat"
    hp.reset_protection(tws, "test:mode")
    assert not (z / ".orch-tool").exists()


def test_start_update_stop_combined(fsguard):
    z, orch_home, ws, _ = fsguard
    addons._save_registry([{"name": "focus", "source": "built-in", "version": "0.1.0"}])
    _cli("start", "--no-open")
    _cli("update")
    _cli("stop", "--all")
    assert (orch_home / "addons.json").is_file()
    assert not (z / ".orch-tool").exists()
