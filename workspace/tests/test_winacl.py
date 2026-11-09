"""Windows user+SYSTEM ACL for the guarded home (#405), simulated on POSIX with real icacls /save output
captured on Windows 11 (standard user). The flag winacl._windows and the icacls runner are replaced."""

import pytest

from orch import addons, winacl
from orch import humanproof as hp
from orch.errors import Refused

SID = "S-1-5-21-2313884086-3657026201-3636488430-1002"
OTHER = "S-1-5-21-2313884086-3657026201-3636488430-1003"
# real: icacls <file> /save out.txt after /inheritance:r /grant:r *SID:(F) *S-1-5-18:(F)
FILE_OK = f"k.key\nD:PAI(A;;FA;;;SY)(A;;FA;;;{SID})\n"
DIR_OK = f"acltest\nD:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;{SID})\n"
# real: a fresh file in the profile: inherits user, SYSTEM, Administrators
INHERITED = f"k.key\nD:AI(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;FA;;;{SID})\n"
BAD = {
    "users": f"x\nD:PAI(A;;FA;;;SY)(A;;FA;;;{SID})(A;;0x1200a9;;;BU)\n",
    "everyone": f"x\nD:PAI(A;;FA;;;SY)(A;;FA;;;{SID})(A;;FA;;;WD)\n",
    "admins": f"x\nD:PAI(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;{SID})\n",
    "other user": f"x\nD:PAI(A;;FA;;;SY)(A;;FA;;;{SID})(A;;FA;;;{OTHER})\n",
    "inherits": INHERITED,
    "inherits unprotected": f"x\nD:AI(A;;FA;;;SY)(A;;FA;;;{SID})\n",
    "read only user": f"x\nD:PAI(A;;FA;;;SY)(A;;FR;;;{SID})\n",
    "deny": f"x\nD:PAI(D;;FA;;;BU)(A;;FA;;;SY)(A;;FA;;;{SID})\n",
    "no user": "x\nD:PAI(A;;FA;;;SY)\n",
    "empty": "x\nD:PAI\n",
    "no dacl": "x\nO:SY\n",
    "garbage": "x\nD:PAI(A;;FA;;;SY)junk(A;;FA;;;S-1-5-21-1-2-3-4)\n",
    "short ace": f"x\nD:PAI(A;;FA;;SY)(A;;FA;;;{SID})\n",
    "nothing": "",
}


@pytest.fixture
def win(monkeypatch):
    calls = []
    state = {"sddl": FILE_OK, "rc": 0, "attrs": 0}

    def fake_icacls(args):
        calls.append(list(args))
        if "/save" in args:
            if state["rc"] == 0:
                out = args[args.index("/save") + 1]
                with open(out, "wb") as f:
                    f.write(state["sddl"].encode("utf-16"))
            return state["rc"], ""
        return state["rc"], "Successfully processed 1 files; Failed processing 0 files"

    monkeypatch.setattr(winacl, "_windows", lambda: True)
    monkeypatch.setattr(winacl, "_run_icacls", fake_icacls)
    monkeypatch.setattr(winacl, "_whoami", lambda: f'"windev\\user","{SID}"\n')
    monkeypatch.setattr(winacl, "_sid_cache", None)
    monkeypatch.setattr(winacl, "_attrs", lambda p: state["attrs"])
    state["calls"] = calls
    return state


def test_posix_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setattr(winacl, "_run_icacls", lambda a: pytest.fail("icacls on POSIX"))
    winacl.set_private(tmp_path, True)
    winacl.check_private(tmp_path)
    winacl.no_reparse(tmp_path)


def test_owner_and_system_only_ok(win, tmp_path):
    f = tmp_path / "k.key"
    f.write_text("x")
    winacl.check_private(f)
    win["sddl"] = DIR_OK
    winacl.check_private(tmp_path)


@pytest.mark.parametrize("name", sorted(BAD))
def test_extra_or_odd_rights_are_refused(win, tmp_path, name):
    win["sddl"] = BAD[name]
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


def test_icacls_failure_refused(win, tmp_path):
    win["rc"] = 5
    with pytest.raises(Refused, match="would not tell"):
        winacl.check_private(tmp_path)
    with pytest.raises(Refused, match="would not set"):
        winacl.set_private(tmp_path, True)


def test_icacls_missing_refused(win, tmp_path, monkeypatch):
    def boom(args):
        raise winacl._no("Windows would not tell its rights")

    monkeypatch.setattr(winacl, "_run_icacls", boom)
    with pytest.raises(Refused):
        winacl.check_private(tmp_path)


def test_unknown_account_refused(win, tmp_path, monkeypatch):
    monkeypatch.setattr(winacl, "_whoami", lambda: "garbage")
    with pytest.raises(Refused, match="account"):
        winacl.check_private(tmp_path)


def test_missing_path_is_not_wrong_rights(win, tmp_path, monkeypatch):
    def gone(p):
        raise FileNotFoundError(p)

    monkeypatch.setattr(winacl, "_attrs", gone)
    with pytest.raises(FileNotFoundError):
        winacl.check_private(tmp_path / "nope")


def test_set_private_argv_list_with_sids_and_inheritance_removed(win, tmp_path):
    win["sddl"] = DIR_OK
    winacl.set_private(tmp_path, True)
    cmd = win["calls"][0]
    assert cmd[0] == str(tmp_path) and "/inheritance:r" in cmd
    assert f"*{SID}:(OI)(CI)(F)" in cmd and "*S-1-5-18:(OI)(CI)(F)" in cmd
    win["sddl"] = FILE_OK
    winacl.set_private(tmp_path / "f", False)
    assert f"*{SID}:(F)" in win["calls"][-2]
    assert win["calls"][-1][1] == "/save"  # verified right after setting


def test_set_private_refuses_when_result_not_private(win, tmp_path):
    win["sddl"] = INHERITED
    with pytest.raises(Refused):
        winacl.set_private(tmp_path, True)


# ---- humanproof wiring (POSIX modes stay; the Windows check is added)


@pytest.fixture
def tws(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    base = acct / ".orch-test"
    ws = base / "ws"
    (ws / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    return ws


def test_humanproof_sets_and_checks_acl_on_every_file(win, tws):
    win["sddl"] = FILE_OK
    key = hp.human_key(tws)
    assert len(key) == 32
    sets = [c for c in win["calls"] if "/grant:r" in c]
    assert any("human.key" in c[0] for c in sets) or any(".tmp" in c[0] for c in sets)
    assert any(c[0].endswith("keys") for c in sets)  # the key folders too
    n = len(win["calls"])
    assert hp.human_key(tws, create=False) == key
    assert len(win["calls"]) > n  # read-back checks the rights again


def test_humanproof_refuses_a_loose_key_on_read(win, tws):
    win["sddl"] = FILE_OK
    hp.human_key(tws)
    win["sddl"] = BAD["admins"]
    with pytest.raises(Refused, match="not private"):
        hp.human_key(tws, create=False)


def test_humanproof_refuses_junction_in_home_path(win, tws, monkeypatch):
    home = hp.guarded_home(tws)
    monkeypatch.setattr(winacl, "_attrs", lambda p: 0x400 if p == home else 0)
    with pytest.raises(Refused, match="link or junction"):
        hp.human_key(tws)
