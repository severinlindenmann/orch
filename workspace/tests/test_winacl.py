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

_REAL_WRITE_DACL = winacl._write_dacl
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
def win(monkeypatch, tmp_path):
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
    monkeypatch.setattr(winacl, "_floor", lambda: None)  # walk everything unless a test sets a floor
    monkeypatch.setattr(winacl, "_attrs", lambda p: state["attrs"])
    monkeypatch.setattr(subprocess, "run", no_process)
    monkeypatch.setattr(subprocess, "Popen", no_process)
    monkeypatch.setattr(os, "system", no_process)
    # the scope guard: a fake profile folder holding this test's folders; tmp_path counts as a guarded home
    monkeypatch.setattr(winacl, "_guard_profile", lambda: str(tmp_path.parent))
    monkeypatch.setattr(winacl, "_homes", set())
    winacl.allow_home(tmp_path)
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
    assert winacl.file_check(tmp_path / "k") == "unknown"  # not a finding: no reset for it
    win["err"] = winacl._cant("Windows would not tell its rights")
    assert winacl.file_check(tmp_path / "k") == "unknown"
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


# ---------------------------------------------------------------- Opus B fixes


def test_unknown_is_refused_without_reset_protection(win, tws):
    key = hp.human_key(tws)
    n = len(win["calls"])
    win["err"] = winacl._cant("Windows would not tell its rights")  # an API error on the file check
    with pytest.raises(Refused) as e:
        hp.human_key(tws, create=False)
    assert not isinstance(e.value, hp.LooseFile)
    win["err"] = None
    assert hp.human_key(tws, create=False) == key  # same key: nothing was reset
    assert hp.take_notices(tws) == []
    assert not [c for c in win["calls"][n:] if c[0] == "write" and c[1].endswith("human.key")]


def test_only_link_type_reparse_tags_are_refused(win, tmp_path, monkeypatch):
    win["attrs"] = 0x400
    for tag, ok in (
        (0xA000000C, False),
        (0xA0000003, False),
        (0, False),
        (0x9000001A, True),
        (0x80000013, True),
    ):
        monkeypatch.setattr(winacl, "_tag", lambda p, tag=tag: tag)  # cloud (OneDrive) and dedup tags pass
        if ok:
            winacl.no_reparse(tmp_path)
        else:
            with pytest.raises(Refused, match="link or junction"):
                winacl.no_reparse(tmp_path)


def test_walk_starts_below_the_profile_folder(win, tmp_path, monkeypatch):
    prof = tmp_path / "Users" / "x"
    home = prof / ".orch-tool"
    home.mkdir(parents=True)
    monkeypatch.setattr(winacl, "_floor", lambda: str(prof))
    monkeypatch.setattr(winacl, "_tag", lambda p: 0xA0000003)
    win["attrs"] = 0x400  # everything is a junction ...
    with pytest.raises(Refused, match="link or junction"):
        winacl.no_reparse(home)  # ... the home below the profile is refused
    seen = []
    monkeypatch.setattr(winacl, "_attrs", lambda p: seen.append(p) or 0x400)
    with pytest.raises(Refused):
        winacl.no_reparse(home)
    assert seen == [home] or str(prof) not in map(
        str, seen
    )  # the profile folder and above are never looked at
    monkeypatch.setattr(winacl, "_attrs", lambda p: seen.append(p) or 0)
    seen.clear()
    winacl.no_reparse(home)
    assert seen == [home]


def test_user_profile_comes_from_the_token_not_the_environment(monkeypatch, tmp_path):
    from conftest import _REAL_HOME_FN  # the true real_home (the suite fakes addons.real_home)

    monkeypatch.setattr(winacl, "_windows", lambda: True)
    monkeypatch.setattr(winacl, "_profile_cache", None)
    monkeypatch.setattr(winacl, "_profile_raw", lambda: "C:\\Users\\real")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOMEDRIVE", "Z:")
    monkeypatch.setenv("HOMEPATH", str(tmp_path))
    assert str(_REAL_HOME_FN()) == "C:\\Users\\real"
    assert str(tmp_path) not in str(_REAL_HOME_FN())


def test_posix_real_home_is_unchanged(monkeypatch, tmp_path):
    from conftest import _REAL_HOME_FN

    monkeypatch.setenv("HOME", str(tmp_path))
    assert _REAL_HOME_FN() != tmp_path  # the account database, not $HOME


def test_profile_lookup_failure_is_refused(monkeypatch):
    monkeypatch.setattr(winacl, "_profile_cache", None)
    for bad in (None, "", "relative\\path"):
        monkeypatch.setattr(winacl, "_profile_raw", lambda bad=bad: bad)
        with pytest.raises(Refused):
            winacl.profile_dir()
    monkeypatch.setattr(winacl, "_profile_raw", lambda: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(Refused):
        winacl.profile_dir()


def _read_fails_once(monkeypatch):
    real, n = hp.saferead.read_private, []

    def once(*a):
        if not n and str(a[1]).endswith("human.key"):  # the human key only, not the binding
            n.append(1)
            return None  # a transient read error, once
        return real(*a)

    monkeypatch.setattr(hp.saferead, "read_private", once)


def test_read_none_with_a_clean_file_on_windows_is_unknown_not_a_reset(win, tws, monkeypatch):
    key = hp.human_key(tws)
    _read_fails_once(monkeypatch)
    with pytest.raises(winacl.Unknown):
        hp.human_key(tws, create=False)
    assert hp.human_key(tws, create=False) == key and hp.take_notices(tws) == []


def test_read_none_with_a_real_finding_still_resets(win, tws, monkeypatch):
    key = hp.human_key(tws)
    d = hp.key_dir(tws, create=False)
    os.link(d / "human.key", d / "second-name")  # a second name: a finding, not a transient error
    assert hp.human_key(tws) != key  # read_private is None for it: reset_protection rotates the key
    assert [n["text"] for n in hp.take_notices(tws)] == [hp.RESET_NOTICE]


def test_a_loose_or_unreadable_binding_refuses_without_a_reset(tws, monkeypatch):
    hp.human_key(tws)
    d = hp.key_dir(tws, create=False)
    before = sorted(p.name for p in d.iterdir())
    with monkeypatch.context() as m:
        m.setattr(hp.saferead, "read_private", lambda *a: None)  # unreadable
        with pytest.raises(Refused, match="copied or moved"):
            hp.human_key(tws, create=False)
    assert sorted(p.name for p in d.iterdir()) == before  # nothing written, nothing reset
    assert hp.take_notices(tws) == []
    os.chmod(d / "binding.json", 0o644)  # a loose binding file
    with pytest.raises(Refused, match="copied or moved"):
        hp.human_key(tws, create=False)
    assert sorted(p.name for p in d.iterdir()) == before and hp.take_notices(tws) == []


def test_posix_read_none_is_still_a_loose_file(tws, monkeypatch):
    key = hp.human_key(tws)
    _read_fails_once(monkeypatch)
    assert hp.human_key(tws) != key  # POSIX behaviour unchanged: reset


# ------------------------------------------------- scope guard (I11b: rights only inside the home)


@pytest.fixture
def users(win, tmp_path, monkeypatch):
    """A fake C:\\Users: Users/user = the profile, Users/Public = the shared folder, .orch-tool = the home."""
    root = tmp_path / "Users"
    prof, public, home = root / "user", root / "Public", root / "user" / ".orch-tool"
    for d in (home, public / "i11b"):
        d.mkdir(parents=True)
    monkeypatch.setattr(winacl, "_guard_profile", lambda: str(prof))
    monkeypatch.setattr(winacl, "_homes", set())
    winacl.allow_home(home)
    return {"root": root, "prof": prof, "public": public, "home": home, "shared": public / "i11b"}


def _writes(win):
    return [c for c in win["calls"] if c[0] == "write"]


def test_scope_refuses_a_target_outside_the_home_before_any_write(win, users):
    outside = users["prof"] / "Documents"
    outside.mkdir()
    for target, is_dir in ((outside, True), (outside / "f", False), (users["shared"], True)):
        with pytest.raises(Refused):
            winacl.set_private(target, is_dir)
    assert _writes(win) == []
    winacl.set_private(users["home"] / "keys", True)  # inside the home: allowed
    assert len(_writes(win)) == 1


def test_scope_ensure_private_never_tightens_outside_the_home(win, users):
    win["dacl"] = INHERITED  # too open: ensure_private would tighten it if it were ours
    for target in (users["prof"] / "Documents", users["shared"]):
        target.mkdir(exist_ok=True)
        with pytest.raises(Refused):
            winacl.ensure_private(target)
    assert _writes(win) == []


def test_scope_guard_holds_in_the_dacl_writer_itself(monkeypatch, tmp_path):
    """_write_dacl (the only real writer) checks the scope before it touches the Win32 API."""
    monkeypatch.setattr(winacl, "_windows", lambda: True)
    monkeypatch.setattr(winacl, "_guard_profile", lambda: str(tmp_path))
    monkeypatch.setattr(winacl, "_homes", set())
    monkeypatch.setattr(winacl, "_api", lambda: pytest.fail("the DACL API was reached"))
    with pytest.raises(Refused):
        winacl._write_dacl(tmp_path / "x", True, SID)


def test_scope_refuses_when_no_home_was_recorded(win, users, monkeypatch):
    monkeypatch.setattr(winacl, "_homes", set())
    with pytest.raises(Refused, match="not inside orch's own folder"):
        winacl.set_private(users["home"], True)
    assert _writes(win) == []


def test_scope_refuses_when_the_profile_is_unknown(win, users, monkeypatch):
    def gone():
        raise winacl._cant("no profile")

    monkeypatch.setattr(winacl, "_guard_profile", gone)
    with pytest.raises(Refused, match="profile folder could not be found"):
        winacl.set_private(users["home"], True)
    assert _writes(win) == []


def test_scope_refuses_a_junction_escape(win, users):
    esc = users["home"] / "esc"
    esc.symlink_to(users["shared"], target_is_directory=True)  # a junction from the home to the outside
    with pytest.raises(Refused, match="Public"):
        winacl.set_private(esc, True)
    win["dacl"] = INHERITED  # too open: only the scope guard stops it (the link check is faked off)
    with pytest.raises(Refused, match="Public"):
        winacl.ensure_private(esc)
    assert _writes(win) == []


def test_scope_refuses_a_home_in_public_the_profile_or_above(win, users):
    for bad in (users["public"] / "orch", users["shared"], users["prof"], users["root"],
                Path(os.path.abspath(os.sep))):  # fmt: skip
        with pytest.raises(Refused):
            winacl.allow_home(bad)
    link = users["prof"] / "home-link"
    link.symlink_to(users["shared"], target_is_directory=True)
    with pytest.raises(Refused, match="Public"):
        winacl.allow_home(link)  # a home that is a junction into Public is judged by its real path


def test_scope_never_the_current_folder_or_above(win, users, monkeypatch):
    sub = users["home"] / "keys"
    sub.mkdir()
    monkeypatch.chdir(sub)
    with pytest.raises(Refused, match="current folder"):
        winacl.set_private(sub, True)
    assert _writes(win) == []
    # The guarded home itself may contain the current folder (ORCH_HOME=~/.orch-test, a workspace under it,
    # the shell standing in that workspace): it is validated by humanproof.guarded_home, so it is allowed.
    winacl.allow_home(users["home"])
    winacl.set_private(users["home"], True)
    assert [c[1] for c in _writes(win)] == [str(users["home"])]


def test_public_like_cwd_stays_untouched_through_keys(win, tws, tmp_path, monkeypatch):
    """I11b: orch run from a shared helper folder (the cwd) writes rights only inside the guarded home, never
    on the cwd, the workspace root or a parent."""
    shared = tmp_path / "Public" / "i11b"
    shared.mkdir(parents=True)
    monkeypatch.chdir(shared)
    hp.human_key(tws)
    home = os.path.realpath(hp.guarded_home(tws))
    writes = [os.path.realpath(c[1]) for c in _writes(win)]
    assert writes, "the home must have been set private"
    assert all(w == home or w.startswith(home + os.sep) for w in writes), writes
    assert os.path.realpath(shared) not in writes and os.path.realpath(tws) not in writes


def test_scope_is_a_no_op_on_posix(tmp_path, monkeypatch):
    monkeypatch.setattr(winacl, "_homes", set())
    winacl.check_scope(tmp_path)  # POSIX: modes and lstat do the job; nothing to refuse here
    winacl.allow_home(tmp_path)
    assert winacl._homes == set()


# ------------------------------------------------------------- install record, one-handle write, home refusal


def test_install_record_is_written_with_no_rights_change_outside_any_home(win, tmp_path, monkeypatch):
    """`orch update` rewrites orch-install.json in the uv tool folder (outside every guarded home). Not a
    secret: it must succeed with no recorded home and never reach the DACL writer or the scope guard."""
    monkeypatch.setattr(winacl, "_homes", set())  # no guarded home recorded
    monkeypatch.setattr(
        winacl, "set_private", lambda *a: pytest.fail("a rights write for the install record")
    )
    monkeypatch.setattr(winacl, "_write_dacl", lambda *a: pytest.fail("a DACL write outside the home"))
    env = tmp_path / "tools" / "orch"
    env.mkdir(parents=True)
    hp.write_install_record(env, "dev")
    assert (env / "orch-install.json").read_text() == hp.install_record_text("dev", env)
    assert not [p for p in env.iterdir() if p.name.endswith(".tmp")]
    assert _writes(win) == []


def _handle_seams(monkeypatch, *, attrs=0, final=None, log=None, tag=0, links=1):
    log = [] if log is None else log
    monkeypatch.setattr(winacl, "_open_target", lambda p: log.append("open") or "H")
    monkeypatch.setattr(winacl, "_close_target", lambda h: log.append("close"))
    monkeypatch.setattr(winacl, "_handle_attrs", lambda h: log.append("attrs") or attrs)
    monkeypatch.setattr(winacl, "_handle_path", lambda h: log.append("final") or final)
    monkeypatch.setattr(winacl, "_handle_tag", lambda h: log.append("tag") or tag)
    monkeypatch.setattr(winacl, "_handle_links", lambda h: log.append("links") or links)
    monkeypatch.setattr(winacl, "_set_dacl_on_handle", lambda h, d, s: log.append("set"))
    monkeypatch.setattr(winacl, "_read_dacl", lambda p, handle=None: log.append(("read", handle)) or FILE_OK)
    return log


def test_write_dacl_opens_once_checks_the_final_path_then_sets_and_reads_by_handle(
    win, tmp_path, monkeypatch
):
    f = tmp_path / "k.key"
    f.write_text("x")
    monkeypatch.setattr(winacl, "_write_dacl", _REAL_WRITE_DACL)  # the fixture fakes it; run the real one
    log = _handle_seams(monkeypatch, final=str(f))
    winacl._write_dacl(f, False, SID)
    assert log == ["open", "attrs", "final", "links", "set", ("read", "H"), "close"]


def test_write_dacl_refuses_when_the_final_path_is_outside_the_home(win, users, monkeypatch):
    """The name looked inside the home at check time but the handle points at Public: refused."""
    monkeypatch.setattr(winacl, "_write_dacl", _REAL_WRITE_DACL)
    f = users["home"] / "k.key"
    f.write_text("x")
    log = _handle_seams(monkeypatch, final=str(users["shared"] / "k.key"))
    with pytest.raises(Refused, match="Public"):
        winacl._write_dacl(f, False, SID)
    assert "set" not in log and log[-1] == "close"


def test_write_dacl_refuses_a_reparse_point_handle(win, tmp_path, monkeypatch):
    monkeypatch.setattr(winacl, "_write_dacl", _REAL_WRITE_DACL)
    f = tmp_path / "k.key"
    f.write_text("x")
    for tag in (winacl.TAG_SYMLINK, winacl.TAG_MOUNT_POINT, 0):  # unknown tag: fail closed
        log = _handle_seams(monkeypatch, attrs=winacl.REPARSE, final=str(f), tag=tag)
        with pytest.raises(Refused, match="link or junction"):
            winacl._write_dacl(f, False, SID)
        assert log == ["open", "attrs", "tag", "close"]


def test_write_dacl_allows_a_cloud_placeholder_reparse_point(win, tmp_path, monkeypatch):
    """OneDrive and similar reparse points are not name-surrogates: ordinary files for us (L2)."""
    monkeypatch.setattr(winacl, "_write_dacl", _REAL_WRITE_DACL)
    f = tmp_path / "k.key"
    f.write_text("x")
    log = _handle_seams(monkeypatch, attrs=winacl.REPARSE, final=str(f), tag=0x9000001A)
    winacl._write_dacl(f, False, SID)
    assert "set" in log


def test_final_path_is_not_resolved_by_name_again(win, tmp_path, monkeypatch):
    """L1: the handle's final path is only normalised; os.path.realpath is never called on it."""
    monkeypatch.setattr(winacl, "_write_dacl", _REAL_WRITE_DACL)
    f = tmp_path / "k.key"
    f.write_text("x")
    _handle_seams(monkeypatch, final=str(f))
    calls = []
    real = os.path.realpath
    monkeypatch.setattr(
        os.path, "realpath", lambda p, *a, **k: calls.append(os.fspath(p)) or real(p, *a, **k)
    )
    winacl._write_dacl(f, False, SID)
    assert calls.count(os.fspath(f)) == 1  # the early name check only; the final path is not re-resolved


def test_untrusted_mount_point_error_is_a_plain_refusal(win, users, monkeypatch):
    """WinError 448 from realpath on a user-created junction: refused, nothing written."""

    def boom(p, *a, **k):
        raise OSError(448, "The path cannot be traversed because it contains an untrusted mount point")

    monkeypatch.setattr(os.path, "realpath", boom)
    home = users["home"]
    calls = [
        lambda: winacl.check_scope(home / "k"),
        lambda: winacl.set_private(home, True),
        lambda: winacl.allow_home(home / "x"),
    ]
    for fn in calls:
        with pytest.raises(Refused, match="real path could not be read"):
            fn()
    assert _writes(win) == []


def test_link_reparse_uses_the_name_surrogate_bit():
    R = winacl.REPARSE
    assert winacl.link_reparse(R, 0xA000001D)  # another name-surrogate tag (e.g. cloud-files symlink kind)
    assert winacl.link_reparse(R, 0)
    assert not winacl.link_reparse(R, 0x8000001B)  # APPEXECLINK
    assert not winacl.link_reparse(R, 0x9000001A)  # OneDrive placeholder
    assert not winacl.link_reparse(0, 0xA000000C)  # not a reparse point at all


def test_inside_is_a_pure_component_comparison():
    """A trailing dot or space is not trimmed: "home." is not "home" (final=True paths are not resolved)."""
    assert winacl._inside(
        os.path.join("c:", os.sep, "u", "home", "k"), os.path.join("c:", os.sep, "u", "home")
    )
    assert not winacl._inside(
        os.path.join("c:", os.sep, "u", "home.", "k"), os.path.join("c:", os.sep, "u", "home")
    )
    assert not winacl._inside(
        os.path.join("c:", os.sep, "u", "home ", "k"), os.path.join("c:", os.sep, "u", "home")
    )
    assert not winacl._inside(
        os.path.join("c:", os.sep, "u", "homer"), os.path.join("c:", os.sep, "u", "home")
    )


def test_write_dacl_refuses_a_hard_linked_file(win, tmp_path, monkeypatch):
    monkeypatch.setattr(winacl, "_write_dacl", _REAL_WRITE_DACL)
    f = tmp_path / "k.key"
    f.write_text("x")
    log = _handle_seams(monkeypatch, final=str(f), links=2)
    with pytest.raises(Refused, match="more than one name"):
        winacl._write_dacl(f, False, SID)
    assert "set" not in log and log[-1] == "close"


def test_os_error_448_in_check_and_ensure_private_is_a_plain_refusal(win, tmp_path, monkeypatch):
    """Elevated process, user-made junction: lstat/realpath raise OSError(448): a plain refusal."""

    def boom(p):
        raise OSError(448, "The path cannot be traversed because it contains an untrusted mount point")

    monkeypatch.setattr(winacl, "_attrs", boom)
    for fn in (winacl.check_private, winacl.ensure_private):
        with pytest.raises(Refused, match="not private to you"):
            fn(tmp_path)
    assert _writes(win) == []
    monkeypatch.setattr(winacl, "_attrs", lambda p: 0)
    monkeypatch.setattr(winacl, "_owner_sid", boom)  # the owner lookup path
    win["dacl"] = INHERITED
    with pytest.raises(Refused):
        winacl.ensure_private(tmp_path)
    assert _writes(win) == []


def test_guarded_home_raises_home_refused_not_a_winacl_refusal(tws, tmp_path, monkeypatch):
    # independent of the install kind and of where the test runs (native Windows too): a normal install with
    # the default home and a home that passes the pairing check, so only allow_home's refusal is under test
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    monkeypatch.setattr(hp, "home_ok", lambda *a: True)
    monkeypatch.delenv("ORCH_HOME", raising=False)

    def refuse(path):
        raise winacl._no("orch would change rights outside its own folder: it is a drive root")

    monkeypatch.setattr(winacl, "allow_home", refuse)
    with pytest.raises(hp.HomeRefused) as e:
        hp.guarded_home(tws)
    assert str(e.value) == hp.MSG_HOME_PLACE
