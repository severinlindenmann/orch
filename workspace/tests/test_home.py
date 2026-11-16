"""Guarded home, key folder, loose-file reset, install record."""

import contextlib
import os
from pathlib import Path

import pytest
from conftest import key_file

from orch import addons
from orch import home as hp
from orch.errors import Refused


@pytest.fixture
def tws(tmp_path, monkeypatch):
    """A test workspace under <fake account home>/.orch-test with its test home; source-tree install =
    test."""
    acct = tmp_path / "acct"
    base = acct / ".orch-test"
    ws = base / "ws"
    (ws / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    for k in list(os.environ):
        if k.startswith("CODEX_"):
            monkeypatch.delenv(k)
    return ws


# ---------------------------------------------------------------- guarded home


def test_test_workspace_uses_test_home(tws):
    assert hp.guarded_home(tws) == tws.parent / "home"


def test_normal_install_real_workspace_with_env_home_is_refused(tws, monkeypatch):
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    acct = tws.parent.parent
    with pytest.raises(hp.HomeRefused, match="different orch folder than your account's") as e:
        hp.guarded_home(tws)  # real workspace + env-chosen home
    assert e.value.code == hp.NOT_TOGETHER
    with pytest.raises(Refused):
        key_file(tws)
    assert not (acct / ".orch-tool").exists()  # nothing created in the account home


def test_home_ok_refuses_other_pairings():
    a = "/Users/pat"
    assert not hp.home_ok(a, "test", True, a + "/.orch-test/ws", a + "/.orch-tool")
    assert not hp.home_ok(a, "dev", True, a + "/work", a + "/.orch-test/h")


def test_real_workspace_with_agent_chosen_home_refused(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    (acct / ".orch-test").mkdir(parents=True)
    ws = tmp_path / "elsewhere"
    ws.mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setattr(hp, "install_kind", lambda: "dev")
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "evil"))
    with pytest.raises(hp.HomeRefused, match="different orch folder than your account's"):
        hp.guarded_home(ws)
    assert not (acct / ".orch-tool").exists() and not (acct / ".orch-test" / "evil").exists()
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-tool"))
    assert hp.guarded_home(ws) == acct / ".orch-tool"  # the default home itself is fine
    monkeypatch.delenv("ORCH_HOME")
    assert hp.guarded_home(ws) == acct / ".orch-tool"


def test_symlinked_prefix_is_no_test_path(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    acct.mkdir()
    real = tmp_path / "real"
    (real / "ws").mkdir(parents=True)
    (acct / ".orch-test").symlink_to(real)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "h"))
    with pytest.raises(Refused):  # a real workspace: the symlinked prefix is no test path
        hp.guarded_home(acct / ".orch-test" / "ws")


# ---------------------------------------------------------------- key and proofs


def test_key_file_rights_and_reuse(tws):
    k = key_file(tws)
    assert len(k) == 32 and key_file(tws) == k
    f = hp.key_dir(tws) / "test.key"
    assert oct(f.stat().st_mode & 0o777) == "0o600"


def test_keys_folder_symlink_refused_on_read(tws):
    key_file(tws)
    home = tws.parent / "home"
    real = home / "keys-real"
    (home / "keys").rename(real)
    (home / "keys").symlink_to(real)
    with pytest.raises(Refused, match="wrong rights"):
        hp.key_dir(tws, create=False)


def test_loose_folders_are_tightened_not_refused(tws):
    k = key_file(tws)
    home = tws.parent / "home"
    for d in (home, home / "keys", hp.key_dir(tws)):
        d.chmod(0o755)
    assert key_file(tws, create=False) == k  # same key: only the folders were tightened
    for d in (home, home / "keys", hp.key_dir(tws)):
        assert oct(d.stat().st_mode & 0o777) == "0o700"


# ---------------------------------------------------------------- loose secret files: reset


def _loose_setup(tws):
    """A key and a store file."""
    key = key_file(tws)
    hp._write_private(hp.key_dir(tws) / "notes.json", "{}")
    return key, hp.key_dir(tws), tws.parent / "home"


READERS = {
    "test.key": lambda tws: key_file(tws),
    "notes.json": lambda tws: hp._read_json(tws, hp.key_dir(tws) / "notes.json", {}),
}


@pytest.mark.parametrize("name", list(READERS))
def test_loose_secret_file_resets_protection(tws, name):
    key, d, home = _loose_setup(tws)
    path = d / name
    path.chmod(0o644)  # loose: the content is never trusted
    with contextlib.suppress(Refused):
        READERS[name](tws)
    if name == "test.key":
        assert key_file(tws) != key  # rotated
    log = (home / "protection-reset.log").read_text()
    assert name in log and key.hex() not in log


def test_wrong_type_is_loose_too(tws):
    key = key_file(tws)
    f = hp.key_dir(tws) / "test.key"
    f.unlink()
    f.symlink_to(tws / "elsewhere")
    assert key_file(tws) != key  # a link in place of the key: never followed, key rotated
    assert not (hp.key_dir(tws) / "test.key").is_symlink()


def test_extra_file_check_hook_counts_as_loose(tws, monkeypatch):
    key = key_file(tws)
    flagged = []  # the hook flags the key once; the reset writes a good one

    def acl(p):
        if p.name == "test.key" and not flagged:
            flagged.append(1)
            return "acl"

    monkeypatch.setattr(hp, "FILE_CHECKS", [acl])
    assert key_file(tws) != key
    monkeypatch.setattr(hp, "FILE_CHECKS", [])


# ---------------------------------------------------------------- the reset runs under the key lock


def _key_lock_held(d):
    return hp._LOCKS.__dict__.get("held", {}).get((str(d), "keys.lock"), 0) > 0


def test_reset_holds_the_key_lock(tws, monkeypatch):
    key_file(tws)
    d = hp.key_dir(tws)
    seen = []
    real = os.open

    def spy(path, *a, **k):
        if Path(path).name == "protection-reset.log":
            seen.append(_key_lock_held(d))
        return real(path, *a, **k)

    monkeypatch.setattr(hp.os, "open", spy)
    hp.reset_protection(tws, "test:mode")
    monkeypatch.undo()
    assert seen and all(seen)  # the write of the reset ran under keys.lock
    assert not _key_lock_held(d)  # and it was released
    with hp._key_lock(d), hp._key_lock(d):  # re-entrant for readers that already hold it
        assert _key_lock_held(d)
    assert not (d / "keys.lock").exists()


# ---------------------------------------------------------------- guarded reads go through saferead


def test_fifo_in_place_of_a_guarded_file_does_not_hang(tws):
    key = key_file(tws)
    f = hp.key_dir(tws) / "notes.json"
    os.mkfifo(f, 0o600)
    with contextlib.suppress(Refused):
        hp._read_json(tws, f, {})  # returns, never blocks: reset
    assert key_file(tws) == key


def test_symlinked_and_oversized_and_hardlinked_files_are_loose(tws):
    for kind in ("symlink", "big", "hardlink"):
        key = key_file(tws)
        f = hp.key_dir(tws) / "test.key"
        f.unlink()
        if kind == "symlink":
            f.symlink_to(tws / ".orch")
        elif kind == "big":
            hp._write_private(f, "a" * (hp.MAX_READ + 10))
        else:
            hp._write_private(tws / "other", key.hex())
            os.link(tws / "other", f)
        assert key_file(tws) != key, kind  # never read, reset


def test_install_record_read_through_saferead(tmp_path, monkeypatch):
    (tmp_path / "orch-install.json").write_text(hp.install_record_text("dev", tmp_path))
    monkeypatch.setattr(hp.sys, "prefix", str(tmp_path))
    assert hp.install_kind() == "dev"
    (tmp_path / "orch-install.json").unlink()
    os.mkfifo(tmp_path / "orch-install.json")
    assert hp.install_kind() in ("test", "normal")  # a FIFO is no record, and does not hang


def test_plain_refusal_texts(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    (acct / ".orch-test" / "home").mkdir(parents=True)
    real = tmp_path / "work"
    real.mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setattr(hp, "install_kind", lambda: "dev")
    monkeypatch.delenv("ORCH_HOME", raising=False)
    (acct / "elsewhere").mkdir()
    (acct / ".orch-tool").symlink_to(acct / "elsewhere")  # the default folder is a link
    with pytest.raises(hp.HomeRefused, match="is a link to somewhere else") as e:
        hp.guarded_home(real)
    assert str(acct / ".orch-tool") in str(e.value) and "belong together" not in str(e.value)
    (acct / ".orch-tool").unlink()
    ws = acct / ".orch-test" / "ws"
    ws.mkdir()
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-tool"))  # a test workspace with the default home
    with pytest.raises(hp.HomeRefused, match="test workspace; start it with its own test orch folder"):
        hp.guarded_home(ws)
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    with pytest.raises(hp.HomeRefused, match="only works in test folders"):
        hp.guarded_home(real)
