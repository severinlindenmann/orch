"""Structural test (lane C's I11a): with a trusted throwaway ORCH_HOME, NO command opens anything under
the account's default orch home <Z>/.orch-tool for writing (write-mode open, mkdir, rename, unlink, rmtree).
Reads of trust state are allowed. The hook raises a BaseException (so no `except Exception` hides it) and also
records every hit."""

import builtins
import contextlib
import hashlib
import io
import os
import shutil
import sys
from pathlib import Path

import pytest

from orch import addons, cli, services
from orch import humanproof as hp

real_os_open = os.open
real_mkdir = os.mkdir
real_rmdir = os.rmdir
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


class AccountHomeWritten(BaseException):
    pass


def tree(root: Path) -> dict:
    """{relative path: (kind, size, mtime, sha256)} under root: names, sizes, mtimes, content."""
    out = {}
    if not root.exists():
        return out
    for p in sorted([root, *root.rglob("*")]):
        st = p.lstat()
        rel = str(p.relative_to(root.parent))
        if p.is_symlink():
            out[rel] = ("link", os.readlink(p))
        elif p.is_dir():
            out[rel] = ("dir", st.st_mode, st.st_mtime_ns)
        else:
            out[rel] = ("file", st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return out


def _fd_path(fd: int) -> str | None:
    try:
        if sys.platform == "darwin":
            import fcntl

            return fcntl.fcntl(fd, fcntl.F_GETPATH, b"\0" * 1024).split(b"\0", 1)[0].decode()
        return os.readlink(f"/proc/self/fd/{fd}")
    except (OSError, ImportError, AttributeError):
        return None


@pytest.fixture(params=["empty", "prefilled"])
def fsguard(request, tmp_path, monkeypatch):
    """A faked account home Z with a trusted throwaway ORCH_HOME and a workspace; installs the write hook."""
    z = tmp_path / "Z"
    z.mkdir()
    watched = os.path.realpath(z / ".orch-tool")
    if (
        request.param == "prefilled"
    ):  # the account's own orch home already has content: it must stay byte-identical
        (z / ".orch-tool" / "keys" / ("a" * 32)).mkdir(parents=True)
        (z / ".orch-tool" / "addons.json").write_text(
            '[{"name": "focus", "source": "built-in", "version": "0.1"}]'
        )
        (z / ".orch-tool" / "running.json").write_text("[]")
        (z / ".orch-tool" / "keys" / ("a" * 32) / "human.key").write_text("00" * 32)
    before = tree(z / ".orch-tool")
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
        if flags & WRITE_FLAGS:
            full = path
            if k.get("dir_fd") is not None:  # opened relative to a folder fd: resolve that folder first
                base = _fd_path(k["dir_fd"])
                full = os.path.join(base, os.fsdecode(path)) if base else None
                if full is None:
                    hit("os.open(dir_fd, unresolved)", path) if watched_exists() else None
            if full is not None and under(full):
                hit("os.open", full)
        return real_os_open(path, flags, *a, **k)

    def watched_exists() -> bool:
        return os.path.lexists(watched)

    monkeypatch.setattr(builtins, "open", open_)
    monkeypatch.setattr(io, "open", open_)
    monkeypatch.setattr(os, "open", os_open)
    for name in ("mkdir", "rmdir", "unlink", "remove", "makedirs", "chmod", "utime", "truncate"):
        orig = getattr(os, name)

        def wrap(path, *a, _o=orig, _n=name, **k):
            if under(path):
                hit(_n, path)
            return _o(path, *a, **k)

        monkeypatch.setattr(os, name, wrap)
    for name in ("symlink", "link"):
        orig_l = getattr(os, name)

        def wrap3(src, dst, *a, _o=orig_l, _n=name, **k):
            if under(dst) or under(src):
                hit(_n, f"{src} -> {dst}")
            return _o(src, dst, *a, **k)

        monkeypatch.setattr(os, name, wrap3)
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
    assert (
        tree(z / ".orch-tool") == before
    )  # byte-for-byte, mtimes included: nothing created, changed or removed


def _cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(list(argv))
    return code, out.getvalue()


def test_the_hook_catches_every_kind_of_write(fsguard):
    z, _, _, hits = fsguard
    home = z / ".orch-tool"
    made = not home.exists()
    if made:
        real_mkdir(home)  # made outside the hook, so every attempt below meets an existing folder
    f = home / "x"
    attempts = [
        lambda: Path(f).write_text("a"),
        lambda: os.open(f, os.O_WRONLY | os.O_CREAT),
        lambda: os.symlink("/etc", home / "l"),
        lambda: os.link(__file__, home / "h"),
        lambda: os.chmod(home, 0o755),
        lambda: os.utime(home, (1, 1)),
        lambda: os.rename(home / "a", home / "b"),
        lambda: os.mkdir(home / "d"),
        lambda: shutil.rmtree(home / "keys"),
    ]
    for go in attempts:
        with pytest.raises(AccountHomeWritten):
            go()
    dfd = real_os_open(home, os.O_RDONLY) if home.exists() else None
    if dfd is not None:  # a write relative to a folder fd is seen too (resolved to the folder's path)
        try:
            with pytest.raises(AccountHomeWritten):
                os.open("viadirfd", os.O_WRONLY | os.O_CREAT, dir_fd=dfd)
        finally:
            os.close(dfd)
    assert len(hits) >= len(attempts)
    hits.clear()  # expected here: clear so the fixture's final check passes
    if made:
        real_rmdir(home)  # back to how it was: the fixture compares the tree


def test_addon_commands(fsguard):
    z, orch_home, ws, _ = fsguard
    assert _cli("addon", "list")[0] == 0
    assert _cli("addon", "add", "focus", "--yes")[0] in (0, 2)
    assert _cli("addon", "remove", "focus")[0] in (0, 2)


def test_start_and_stop(fsguard):
    z, orch_home, ws, _ = fsguard
    assert services.running_path() == orch_home / "running.json"
    assert _cli("start", "--no-open")[0] in (0, 2)
    assert _cli("status")[0] == 0
    assert _cli("stop", "--all")[0] in (0, 2)


def test_update(fsguard):
    z, orch_home, ws, _ = fsguard
    addons._save_registry([{"name": "focus", "source": "built-in", "version": "0.1.0"}])
    assert _cli("update")[0] in (0, 2)
    assert (orch_home / "addons.json").is_file()


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


def test_start_update_stop_combined(fsguard):
    z, orch_home, ws, _ = fsguard
    addons._save_registry([{"name": "focus", "source": "built-in", "version": "0.1.0"}])
    _cli("start", "--no-open")
    _cli("update")
    _cli("stop", "--all")
    assert (orch_home / "addons.json").is_file()


def test_strict_state_writes_stay_in_orch_home(fsguard, monkeypatch, tmp_path):
    """ORCH_HOME_STRICT: ticket, key, registry and record writes all land under ORCH_HOME; the faked account
    home (and HOME, and the entry guard's real home) gets nothing."""
    import orch_entry

    z, orch_home, ws, _ = fsguard
    monkeypatch.setattr(orch_entry, "real_home", lambda: z)
    assert orch_entry.home_candidates() == [orch_home.resolve()]
    assert addons.home_candidates() == [orch_home.resolve()]
    assert (z / ".orch-tool").resolve() in addons.home_candidates(include_real=True)
    _cli("init", "--yes")
    assert _cli("ticket", "new", "strict home check", "--json", "--by", "agent:x")[0] == 0
    addons._save_registry([{"name": "focus", "source": "built-in", "version": "0.1.0"}])
    assert (orch_home / "addons.json").is_file()
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    prefix = z / ".orch-test"
    prefix.mkdir()
    tws = prefix / "ws"
    (tws / ".orch").mkdir(parents=True)
    monkeypatch.setenv("ORCH_HOME", str(prefix / "home"))
    (prefix / "home").mkdir()
    hp.human_key(tws, create=True)
    # HOME may get an agent tool's own scratch folder (probing an installed `codex` makes ~/.codex/tmp),
    # but never anything of orch's
    assert not (tmp_path / "X" / ".orch-tool").exists() and not (tmp_path / "X" / ".orch-test").exists()
    assert sorted(p.name for p in z.iterdir() if p.name not in (".orch-tool",)) == [
        ".orch-test",
        "lane-home",
        "work",
    ]
