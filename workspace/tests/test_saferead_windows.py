"""saferead on Windows (no dir_fd, no O_NOFOLLOW, text-mode os.open), simulated on POSIX through the ONE
no-dir_fd path that read_private, file_state and safe_read_tail share: saferead._DIRFD is False, the reparse
seam is replaced and os.open must never get a dir_fd."""

import hashlib
import os
import stat

import pytest

from orch import saferead, winacl
from orch.errors import Refused

CRLF = b"ab\r\ncd\x1a\r\n"  # text mode would change or cut these


@pytest.fixture
def win(monkeypatch, tmp_path):
    """Windows simulated: no dir_fd, winacl says Windows, and `_win_open_raw` (CreateFileW) is emulated with
    what Windows would answer. state["redirect"]: path -> the final path the handle reports (a junction that
    was swapped in after the folder check); state["reparse"]: paths that are a reparse point."""
    state = {"reparse": set(), "redirect": {}, "raw": [], "root": tmp_path.resolve()}

    def raw(path):
        state["raw"].append(path)
        try:
            st = os.lstat(path)
        except OSError:
            return None
        if stat.S_ISDIR(st.st_mode):
            return None  # no backup semantics: a folder can not be opened
        link = stat.S_ISLNK(st.st_mode) or path in state["reparse"]
        fd = os.open(os.devnull if stat.S_ISLNK(st.st_mode) else path, os.O_RDONLY | os.O_NONBLOCK)
        return fd, 0x400 if link else 0x20, st.st_nlink, state["redirect"].get(path, "\\\\?\\" + path)

    monkeypatch.setattr(saferead, "_DIRFD", False)
    monkeypatch.setattr(winacl, "_windows", lambda: True)
    monkeypatch.setattr(saferead, "_win_open_raw", raw)
    monkeypatch.setattr(saferead, "_reparse", lambda p: str(p) in state["reparse"])
    real_open = os.open

    def no_dir_fd(path, flags, *a, **kw):
        assert "dir_fd" not in kw, "dir_fd is not supported on Windows"
        return real_open(path, flags, *a, **kw)

    monkeypatch.setattr(saferead.os, "open", no_dir_fd)
    return state


def rp(r, rel, limit=100):
    return saferead.read_private(r, rel, limit)


def fs(r, rel):
    return saferead.file_state(r, rel, 1000, [1000])


def tail(r, rel):
    try:
        return saferead.safe_read_tail(r, str(r / rel), 100)
    except Refused:
        return None


def mk(r, rel, data=b"{}"):
    f = r / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return f


# ---------------------------------------------------------------- the same cases, three readers


def test_plain_file_is_read_in_binary_mode(win):
    r = win["root"]
    mk(r, "d/app.log", CRLF)
    assert rp(r, "d/app.log") == CRLF
    assert fs(r, "d/app.log") == "F:-:" + hashlib.sha256(CRLF).hexdigest()
    assert tail(r, "d/app.log") == CRLF
    assert win["raw"]  # every read went through the one Windows open


def test_missing_oversize_and_odd_names(win):
    r = win["root"]
    mk(r, "big.log", b"x" * 101)
    mk(r, "ok.log")
    assert rp(r, "nope.log") is None and fs(r, "nope.log") == "?"
    assert rp(r, "big.log") is None  # bigger than the limit
    for bad in ("", "../ok.log", "a/../ok.log", "ok.log:stream", "a\\ok.log"):
        assert rp(r, bad) is None
        assert fs(r, bad) == "?"
    assert tail(r, "ok.log:stream") is None and tail(r, "../ok.log") is None


@pytest.mark.parametrize("bad", ["root", "dir", "file"])
def test_reparse_point_on_the_root_a_folder_or_the_file(win, bad):
    r = win["root"]
    mk(r, "d/f.log")
    assert rp(r, "d/f.log") == b"{}" and fs(r, "d/f.log").startswith("F:") and tail(r, "d/f.log") == b"{}"
    win["reparse"] = {str({"root": r, "dir": r / "d", "file": r / "d" / "f.log"}[bad])}
    if bad != "file":  # a reparse FILE is refused where it is opened (the folders are refused by _anchor)
        assert fs(r, "d/f.log") == "?"
    assert rp(r, "d/f.log") is None
    assert tail(r, "d/f.log") is None


def test_symlink_hard_link_fifo_and_folder(win):
    r = win["root"]
    mk(r, "real.log")
    os.symlink(r / "real.log", r / "link.log")
    os.link(r / "real.log", r / "hard.log")
    os.mkfifo(r / "pipe.log")
    (r / "dir.log").mkdir()
    for name in ("link.log", "hard.log", "pipe.log", "dir.log"):
        assert rp(r, name) is None
        assert tail(r, name) is None
    assert fs(r, "link.log").startswith("L:") and fs(r, "hard.log").startswith("H:")
    assert fs(r, "pipe.log").startswith("S:") and fs(r, "dir.log").startswith("S:")


def test_junction_swapped_in_after_the_folder_check_is_refused(win):
    """The folders were clean when checked; the handle then reports another final path: refused everywhere."""
    r = win["root"]
    mk(r, "d/a.log")
    mk(r, "elsewhere/a.log")
    assert rp(r, "d/a.log") == b"{}"
    win["redirect"] = {str(r / "d" / "a.log"): "\\\\?\\" + str(r / "elsewhere" / "a.log")}
    assert rp(r, "d/a.log") is None
    assert fs(r, "d/a.log") == "?"
    assert tail(r, "d/a.log") is None


def test_final_path_compare_ignores_case_prefix_and_slashes():
    same = saferead._same_path
    assert same("\\\\?\\C:\\Users\\X\\f.json", "c:/users/x/f.json")
    assert same("\\\\?\\UNC\\srv\\share\\f", "\\\\SRV\\share\\f")
    assert not same("\\\\?\\C:\\Users\\X\\f.json", "C:\\Users\\Y\\f.json")


def test_api_failure_is_none(win, monkeypatch):
    r = win["root"]
    mk(r, "a.log")
    for boom in (OSError("x"), ImportError("x"), AttributeError("x")):
        monkeypatch.setattr(saferead, "_win_open_raw", lambda p, boom=boom: (_ for _ in ()).throw(boom))
        assert rp(r, "a.log") is None and fs(r, "a.log") == "?" and tail(r, "a.log") is None


def test_posix_path_is_unchanged(tmp_path):
    (tmp_path / "a.log").write_bytes(b"{}")
    r = tmp_path.resolve()
    assert saferead._DIRFD  # dir_fd walk on POSIX
    assert rp(r, "a.log") == b"{}" and tail(r, "a.log") == b"{}" and fs(r, "a.log").startswith("F:")
