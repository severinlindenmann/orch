# ruff: noqa: F811
"""Windows user+SYSTEM ACL for the guarded home (#405), simulated on POSIX with the ACEs the real Win32 API
returned on Windows 11 (standard user). The flag winacl._windows and the API seams are replaced; any child
process (icacls, whoami) fails the test."""

import contextlib
import inspect
import os
import subprocess
from pathlib import Path

import pytest
from test_humanproof import READERS, TID, _loose_setup, tws  # noqa: F401

from orch import humanproof as hp
from orch import winacl
from orch.errors import Refused

SID = "S-1-5-21-2313884086-3657026201-3636488430-1002"
OTHER = "S-1-5-21-2313884086-3657026201-3636488430-1003"
SY = "S-1-5-18"
FA = 0x1F01FF
# What the Win32 API returned for a real file/folder after set_private as a standard user on Windows 11
# (icacls showed: SYSTEM:(F) and WINDEV\user:(F), SDDL D:PAI(A;;FA;;;SY)(A;;FA;;;<user>))
FILE_OK = (True, [(0, 0, FA, SY), (0, 0, FA, SID)])
DIR_OK = (True, [(0, 3, FA, SY), (0, 3, FA, SID)])
# a fresh file in the profile: inherits user, SYSTEM, Administrators
INHERITED = (False, [(0, 0x10, FA, SY), (0, 0x10, FA, "S-1-5-32-544"), (0, 0x10, FA, SID)])
BAD = {
    "users": (True, [*FILE_OK[1], (0, 0, 0x1200A9, "S-1-5-32-545")]),
    "everyone": (True, [*FILE_OK[1], (0, 0, FA, "S-1-1-0")]),
    "admins": (True, [*FILE_OK[1], (0, 0, FA, "S-1-5-32-544")]),
    "other user": (True, [*FILE_OK[1], (0, 0, FA, OTHER)]),
    "inherits": INHERITED,
    "inherits unprotected": (False, FILE_OK[1]),
    "inherited ace on protected": (True, [(0, 0x10, FA, SY), (0, 0x10, FA, SID)]),
    "read only user": (True, [(0, 0, FA, SY), (0, 0, 0x120089, SID)]),
    "deny": (True, [(1, 0, FA, "?"), *FILE_OK[1]]),
    "no user": (True, [(0, 0, FA, SY)]),
    "empty": (True, []),
    "odd ace flags": (True, [(0, 0x40, FA, SY), (0, 0, FA, SID)]),
}


@pytest.fixture
def win(monkeypatch):
    calls = []
    state = {"dacl": FILE_OK, "attrs": 0, "err": None, "set_err": None, "owner": SID, "loose": set()}

    def read(p):
        calls.append(("read", str(p)))
        if state["err"]:
            raise state["err"]
        if Path(p).name in state["loose"]:
            return INHERITED
        return state["dacl"]

    def write(p, is_dir, sid):
        calls.append(("write", str(p), is_dir, sid))
        if state["set_err"]:
            raise state["set_err"]
        name = Path(p).name
        if name.startswith(".") and name.endswith(".tmp"):  # a file written anew is private again
            state["loose"].discard(name[1:].rsplit(".", 2)[0])
        if is_dir:
            state["loose"].discard(name)
        state["dacl"] = DIR_OK if is_dir else FILE_OK  # what the real API leaves behind

    def owner(p):
        if isinstance(state["owner"], Exception):
            raise state["owner"]
        return state["owner"]

    def no_process(*a, **k):
        pytest.fail("a child process was started (PATH/cwd lookup of icacls or whoami)")

    monkeypatch.setattr(winacl, "_windows", lambda: True)
    monkeypatch.setattr(winacl, "_read_dacl", read)
    monkeypatch.setattr(winacl, "_write_dacl", write)
    monkeypatch.setattr(winacl, "_owner_sid", owner)
    monkeypatch.setattr(winacl, "_sid_cache", SID)
    monkeypatch.setattr(winacl, "_attrs", lambda p: state["attrs"])
    monkeypatch.setattr(subprocess, "run", no_process)
    monkeypatch.setattr(subprocess, "Popen", no_process)
    monkeypatch.setattr(os, "system", no_process)
    state["calls"] = calls
    return state


def test_no_subprocess_in_module():
    assert not hasattr(winacl, "subprocess")
    assert "import subprocess" not in inspect.getsource(winacl)


def test_posix_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setattr(winacl, "_read_dacl", lambda p: pytest.fail("api on POSIX"))
    monkeypatch.setattr(winacl, "_write_dacl", lambda *a: pytest.fail("api on POSIX"))
    winacl.set_private(tmp_path, True)
    winacl.check_private(tmp_path)
    winacl.no_reparse(tmp_path)


def test_owner_and_system_only_ok(win, tmp_path):
    winacl.check_private(tmp_path / "k.key")
    win["dacl"] = DIR_OK
    winacl.check_private(tmp_path)
    win["dacl"] = (True, [(0, 0, FA, SID)])  # user only is still private
    winacl.check_private(tmp_path)


@pytest.mark.parametrize("name", sorted(BAD))
def test_extra_or_odd_rights_are_refused(win, tmp_path, name):
    win["dacl"] = BAD[name]
    with pytest.raises(Refused, match="not private to you"):
        winacl.check_private(tmp_path)


def test_reparse_point_refused_anywhere_on_the_path(win, tmp_path, monkeypatch):
    f = tmp_path / "a" / "k.key"
    f.parent.mkdir()
    f.write_text("x")
    real = winacl._attrs
    monkeypatch.setattr(winacl, "_attrs", lambda p: 0x400 if p == tmp_path / "a" else 0)
    with pytest.raises(Refused, match="link or junction"):
        winacl.check_private(f)
    with pytest.raises(Refused, match="link or junction"):
        winacl.no_reparse(f)
    monkeypatch.setattr(winacl, "_attrs", real)
    winacl.no_reparse(f)


def test_api_failure_refused(win, tmp_path):
    win["err"] = winacl._no("Windows would not tell its rights")
    with pytest.raises(Refused, match="would not tell"):
        winacl.check_private(tmp_path)
    win["err"] = OSError("boom")  # any surprise, not only Refused
    with pytest.raises(Refused, match="would not tell"):
        winacl.check_private(tmp_path)
    win["set_err"] = RuntimeError("boom")
    with pytest.raises(Refused, match="would not set"):
        winacl.set_private(tmp_path, True)


def test_attribute_check_failure_refused(win, tmp_path, monkeypatch):
    def bad(p):
        raise PermissionError(p)

    monkeypatch.setattr(winacl, "_attrs", bad)
    with pytest.raises(Refused):
        winacl.no_reparse(tmp_path)


def test_missing_path_is_not_wrong_rights(win, tmp_path, monkeypatch):
    def gone(p):
        raise FileNotFoundError(p)

    monkeypatch.setattr(winacl, "_attrs", gone)
    with pytest.raises(FileNotFoundError):
        winacl.check_private(tmp_path / "nope")


def test_set_private_writes_user_and_system_then_verifies(win, tmp_path):
    win["dacl"] = DIR_OK
    winacl.set_private(tmp_path, True)
    assert win["calls"] == [("write", str(tmp_path), True, SID), ("read", str(tmp_path))]
    win["dacl"] = FILE_OK
    winacl.set_private(tmp_path / "f", False)
    assert win["calls"][-2][2] is False


def test_set_private_refuses_when_result_not_private(win, tmp_path, monkeypatch):
    monkeypatch.setattr(winacl, "_write_dacl", lambda *a: None)  # the API "succeeds" but leaves it open
    win["dacl"] = INHERITED
    with pytest.raises(Refused):
        winacl.set_private(tmp_path, True)


def test_ensure_private_tightens_a_loose_folder_of_this_user(win, tmp_path):
    win["dacl"] = INHERITED  # an old home: user, SYSTEM, Administrators, inherited
    winacl.ensure_private(tmp_path)
    assert ("write", str(tmp_path), True, SID) in win["calls"]
    winacl.check_private(tmp_path)  # and it is private now


def test_ensure_private_leaves_a_private_one_alone(win, tmp_path):
    winacl.ensure_private(tmp_path)
    assert not [c for c in win["calls"] if c[0] == "write"]


def test_ensure_private_refuses_foreign_owner_or_unknown_owner(win, tmp_path):
    win["dacl"] = INHERITED
    win["owner"] = OTHER
    with pytest.raises(Refused, match="another account"):
        winacl.ensure_private(tmp_path)
    win["owner"] = "S-1-5-32-544"  # created by an administrator
    with pytest.raises(Refused, match="another account"):
        winacl.ensure_private(tmp_path)
    win["owner"] = OSError("boom")
    with pytest.raises(Refused, match="who owns"):
        winacl.ensure_private(tmp_path)
    assert not [c for c in win["calls"] if c[0] == "write"]


def test_ensure_private_never_tightens_a_junction(win, tmp_path):
    win["dacl"] = INHERITED
    win["attrs"] = 0x400
    with pytest.raises(Refused, match="link or junction"):
        winacl.ensure_private(tmp_path)
    assert not [c for c in win["calls"] if c[0] == "write"]


def test_ensure_private_refuses_when_tightening_fails(win, tmp_path):
    win["dacl"] = INHERITED
    win["set_err"] = RuntimeError("denied")
    with pytest.raises(Refused, match="would not set"):
        winacl.ensure_private(tmp_path)


# ---- humanproof wiring (POSIX modes stay; the Windows check is added)


def test_humanproof_sets_and_checks_acl_on_every_file(win, tws):
    win["dacl"] = FILE_OK
    key = hp.human_key(tws)
    assert len(key) == 32
    sets = [c[1] for c in win["calls"] if c[0] == "write"]
    assert any(".human.key" in x and x.endswith(".tmp") for x in sets)
    assert any(x.endswith("keys") for x in sets)  # the key folders too
    n = len(win["calls"])
    assert hp.human_key(tws, create=False) == key
    assert len(win["calls"]) > n  # read-back checks the rights again


def test_humanproof_tightens_an_old_loose_folder_of_this_user(win, tws):
    key = hp.human_key(tws)
    n = len(win["calls"])
    win["loose"].add("keys")  # made before this check existed: inherited, Administrators on it
    assert hp.human_key(tws, create=False) == key  # not watch-only: tightened, verified, same key
    assert any(c[0] == "write" and c[1].endswith("keys") and c[2] for c in win["calls"][n:])
    assert hp.take_notices(tws) == []


@pytest.mark.parametrize("name", list(READERS))
def test_loose_file_on_windows_is_never_tightened_it_resets_protection(win, tws, name):
    key, old, d, home = _loose_setup(tws)
    win["loose"].add(name)  # the ACL of this one file is loose
    n = len(win["calls"])
    with contextlib.suppress(Refused):
        READERS[name](tws)
    # never "tightened and trusted": no ACL write ever hits that file itself
    assert not [c for c in win["calls"][n:] if c[0] == "write" and Path(c[1]).name == name]
    assert hp.human_key(tws) != key  # human.key rotated
    with pytest.raises(Refused):
        hp.verify_and_consume(tws, old, "run.takeover", TID)
    assert not (d / "proofs-used.json").exists() and not (d / "delivered.json").exists()
    assert not (d / "handoffs.json").exists()
    assert hp.effective(tws, "focus.session_typing", True) is False
    assert [n["text"] for n in hp.take_notices(tws)] == [hp.RESET_NOTICE]


def test_file_check_hook_is_registered_and_fails_closed(win, tmp_path):
    assert winacl.file_check in hp.FILE_CHECKS
    assert winacl.file_check(tmp_path / "k") is None
    win["dacl"] = BAD["admins"]
    assert winacl.file_check(tmp_path / "k") == "acl"
    win["err"] = RuntimeError("boom")
    assert winacl.file_check(tmp_path / "k") == "acl"
    win["err"] = None
    win["attrs"] = 0x400
    assert winacl.file_check(tmp_path / "k") == "acl"  # a link in place of the file


def test_file_check_is_a_no_op_on_posix(tmp_path):
    assert winacl.file_check(tmp_path) is None


def test_humanproof_refuses_a_loose_key_of_another_owner(win, tws):
    hp.human_key(tws)
    win["dacl"] = BAD["admins"]
    win["owner"] = OTHER
    with pytest.raises(Refused, match="another account"):
        hp.human_key(tws, create=False)


def test_humanproof_refuses_junction_in_home_path(win, tws, monkeypatch):
    home = hp.guarded_home(tws)
    monkeypatch.setattr(winacl, "_attrs", lambda p: 0x400 if p == home else 0)
    with pytest.raises(Refused, match="link or junction"):
        hp.human_key(tws)
