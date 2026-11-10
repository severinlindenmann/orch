"""saferead on Windows (no dir_fd, no O_NOFOLLOW, text-mode os.open), simulated on POSIX through the ONE
no-dir_fd path that read_private, file_state and safe_read_tail share: saferead._DIRFD is False, the reparse
seam is replaced and os.open must never get a dir_fd."""

import ctypes
import hashlib
import os
import stat
import types

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
    monkeypatch.setattr(saferead, "_win_resolve", lambda p: p)  # no subst, no mapped drive, no 8.3 here
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


def test_final_path_compare_ignores_case_prefix_and_slashes(monkeypatch):
    monkeypatch.setattr(saferead, "_win_resolve", lambda p: p)
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


# ---------------------------------------------------------------- W2a review fixes


@pytest.mark.parametrize("name", ["CON", "nul", "Aux.txt", "COM1", "lpt9.log", "PRN.tar.gz", "CONIN$"])
def test_dos_device_names_are_refused_before_any_open(win, name):
    r = win["root"]
    assert rp(r, name) is None and rp(r, f"d/{name}") is None
    assert fs(r, name) == "?" and fs(r, f"d/{name}") == "?"
    assert not win["raw"]  # CreateFileW was never called
    mk(r, "console.log")
    assert rp(r, "console.log") == b"{}"  # CON-prefixed but not a device


@pytest.mark.parametrize("rel", ["", "/", "/abs", ".", "..", "../x", "a/./b", "a//b", "a/", "x\0y"])
@pytest.mark.parametrize("windows", [False, True])
def test_odd_rel_is_none_on_both_branches(tmp_path, monkeypatch, rel, windows):
    if windows:
        monkeypatch.setattr(saferead, "_DIRFD", False)
        monkeypatch.setattr(winacl, "_windows", lambda: True)
    r = tmp_path.resolve()
    mk(r, "x")
    assert saferead.read_private(r, rel, 100) is None  # no IndexError, no escape
    assert saferead.file_state(r, rel, 100, [100]) == "?"
    with pytest.raises(OSError):
        saferead._anchor(r, ())


def test_reparse_point_file_is_refused(win):
    r = win["root"]
    f = mk(r, "a.log")
    win["reparse"] = {str(f)}  # CreateFileW reports FILE_ATTRIBUTE_REPARSE_POINT for the file itself
    assert rp(r, "a.log") is None and fs(r, "a.log") == "?" and tail(r, "a.log") is None


def test_not_a_disk_file_or_a_different_index_is_refused(win, monkeypatch):
    r = win["root"]
    mk(r, "a.log")
    real = saferead._win_open_raw

    def pipe(path):  # GetFileType != DISK makes the real _win_open_raw return None
        return None

    monkeypatch.setattr(saferead, "_win_open_raw", pipe)
    assert rp(r, "a.log") is None
    monkeypatch.setattr(saferead, "_win_open_raw", real)
    lstat = os.lstat

    def other(p, *a, **k):  # the path now names another file than the handle
        st = lstat(p, *a, **k)
        return os.stat_result((*tuple(st)[:1], st.st_ino + 7, *tuple(st)[2:]))

    monkeypatch.setattr(saferead.os, "lstat", other)
    assert rp(r, "a.log") is None and fs(r, "a.log") == "?" and tail(r, "a.log") is None


def test_ctypes_argument_error_is_none(win, monkeypatch):
    import ctypes

    r = win["root"]
    mk(r, "a.log")

    def bad(path):
        raise ctypes.ArgumentError("argument 1: wrong type")

    monkeypatch.setattr(saferead, "_win_open_raw", bad)
    assert rp(r, "a.log") is None and fs(r, "a.log") == "?" and tail(r, "a.log") is None


# ---------------------------------------------------------------- Opus B fixes (W1, W2)


def test_cloud_placeholder_folder_and_file_are_not_links(win, monkeypatch):
    """OneDrive Files On-Demand: a reparse point with a cloud tag is an ordinary file for saferead."""
    r = win["root"]
    f = mk(r, "d/a.log")
    monkeypatch.undo()  # use the real _reparse with a fake lstat tag below
    monkeypatch.setattr(saferead, "_DIRFD", False)
    monkeypatch.setattr(winacl, "_windows", lambda: True)
    lstat = os.lstat

    def cloud(p, *a, **k):
        st = lstat(p, *a, **k)
        if str(p) in (str(r / "d"), str(f)):
            return types.SimpleNamespace(
                st_file_attributes=0x400,
                st_reparse_tag=0x9000001A,
                st_mode=st.st_mode,
                st_dev=st.st_dev,
                st_ino=st.st_ino,
                st_nlink=st.st_nlink,
                st_size=st.st_size,
            )
        return st

    monkeypatch.setattr(saferead.os, "lstat", cloud)
    assert saferead._reparse(r / "d") is False and saferead._reparse(f) is False
    monkeypatch.setattr(
        saferead.os,
        "lstat",
        lambda p, *a, **k: types.SimpleNamespace(st_file_attributes=0x400, st_reparse_tag=0xA0000003),
    )
    assert saferead._reparse(r / "d") is True  # a junction


def test_open_checked_without_a_check_path_is_none_on_windows(win):
    r = win["root"]
    f = mk(r, "a.log")
    assert saferead._open_checked(str(f), {}, None) is None  # no os.open fallback (it follows links)


def test_a_final_path_as_long_as_the_buffer_is_a_failure():
    import inspect

    assert "< 32768" in inspect.getsource(saferead._win_open_raw)


# ---------------------------------------------------------------- #414: UNC, mapped drives, 8.3, subst

SHORT = "C:\\USERS\\USER~1.WIN\\WORK\\F.LOG"
LONG = "C:\\Users\\user.WINDEV\\work\\f.log"


def resolver(table, calls=None):
    """_win_resolve with a table: path (no prefix) -> long real path; anything else is unknown (None)."""

    def r(p):
        if calls is not None:
            calls.append(p)
        return table.get(p)

    return r


@pytest.mark.parametrize(
    "final, expected",
    [
        ("\\\\?\\UNC\\host\\share\\d\\f.log", "\\\\host\\share\\d\\f.log"),  # UNC root
        ("\\\\?\\UNC\\HOST\\Share\\d\\f.log", "//host/share/d/f.log"),  # case, slashes
        ("\\\\?\\UNC\\host\\share\\d\\f.log", "Z:\\d\\f.log"),  # mapped drive Z: = \\host\share
        ("\\\\?\\C:\\work\\d\\f.log", "Q:\\d\\f.log"),  # subst Q: = C:\work
        ("\\\\?\\" + LONG, SHORT),  # 8.3 root
    ],
)
def test_canonical_form_makes_these_the_same_place(final, expected, monkeypatch):
    table = {
        "\\\\host\\share\\d\\f.log": "\\\\host\\share\\d\\f.log",
        "//host/share/d/f.log": "\\\\host\\share\\d\\f.log",
        "Z:\\d\\f.log": "\\\\host\\share\\d\\f.log",
        "Q:\\d\\f.log": "C:\\work\\d\\f.log",
        "C:\\work\\d\\f.log": "C:\\work\\d\\f.log",
        "\\\\HOST\\Share\\d\\f.log": "\\\\host\\share\\d\\f.log",
        SHORT: LONG,
        LONG: LONG,
    }
    monkeypatch.setattr(saferead, "_win_resolve", resolver(table))
    assert saferead._same_path(final, expected)


def test_other_places_and_unknowns_are_never_the_same(monkeypatch):
    table = {
        "\\\\host\\share\\f": "\\\\host\\share\\f",
        "\\\\host\\other\\f": "\\\\host\\other\\f",
        "\\\\evil\\share\\f": "\\\\evil\\share\\f",
    }
    monkeypatch.setattr(saferead, "_win_resolve", resolver(table))
    assert saferead._same_path("\\\\?\\UNC\\host\\share\\f", "\\\\host\\share\\f")
    assert not saferead._same_path("\\\\?\\UNC\\host\\share\\f", "\\\\host\\other\\f")  # other share
    assert not saferead._same_path("\\\\?\\UNC\\host\\share\\f", "\\\\evil\\share\\f")  # other host
    assert not saferead._same_path("\\\\?\\UNC\\host\\share\\f", "Z:\\unmapped\\f")  # can not resolve
    assert not saferead._same_path("Z:\\unmapped\\f", "Z:\\unmapped\\f")  # unknown on both sides: refuse
    monkeypatch.setattr(saferead, "_win_resolve", lambda p: (_ for _ in ()).throw(OSError("x")))
    assert not saferead._same_path("C:\\a", "C:\\a")
    monkeypatch.setattr(saferead, "_win_resolve", lambda p: (_ for _ in ()).throw(ctypes.ArgumentError("x")))
    assert not saferead._same_path("C:\\a", "C:\\a")


def test_dos_device_results_become_plain_paths():
    t = saferead._dos_target
    assert t("\\??\\C:\\work") == "C:\\work"  # subst
    assert t("\\??\\UNC\\host\\share\\dir") == "\\\\host\\share\\dir"  # subst of a UNC path
    assert t("\\Device\\HarddiskVolume3") is None  # a real disk
    assert saferead._is_network_dev("\\Device\\LanmanRedirector\\;Z:0000000000012345\\host\\share")
    assert saferead._is_network_dev("\\Device\\Mup\\;LanmanRedirector\\;Z:0\\host\\share")
    assert not saferead._is_network_dev("\\Device\\HarddiskVolume3")
    assert not saferead._is_network_dev("\\??\\C:\\work")


def test_mapped_unc_and_short_roots_read_through_all_three_readers(win, monkeypatch):
    """The expected path is spelled one way (Z:, 8.3), the handle reports another (UNC): same place, read."""
    r = win["root"]
    mk(r, "d/app.log", CRLF)
    real_raw = saferead._win_open_raw

    def spelled_otherwise(path):
        got = real_raw(path)
        return got and (got[0], got[1], got[2], "\\\\?\\UNC\\host\\share\\" + Path_tail(path))

    def Path_tail(path):
        return str(path)[len(str(r)) :].lstrip("/").replace("/", "\\")

    monkeypatch.setattr(saferead, "_win_open_raw", spelled_otherwise)

    def resolve(p):  # Z: and the handle's UNC name are one share; the root spelled with 8.3 too
        p = p.replace("/", "\\")
        if p.startswith("\\\\host\\share\\"):
            return p
        return (
            "\\\\host\\share\\" + Path_tail(p.replace("\\", "/")) if str(r) in p.replace("\\", "/") else None
        )

    monkeypatch.setattr(saferead, "_win_resolve", resolve)
    assert rp(r, "d/app.log") == CRLF
    assert fs(r, "d/app.log").startswith("F:")
    assert tail(r, "d/app.log") == CRLF


def test_junction_swap_is_still_refused_when_both_sides_are_canonical(win, monkeypatch):
    r = win["root"]
    mk(r, "d/a.log")
    mk(r, "elsewhere/a.log")
    monkeypatch.setattr(saferead, "_win_resolve", lambda p: p)  # canonical: just normalised
    win["redirect"] = {str(r / "d" / "a.log"): "\\\\?\\UNC\\host\\share\\elsewhere\\a.log"}
    assert rp(r, "d/a.log") is None and fs(r, "d/a.log") == "?" and tail(r, "d/a.log") is None


def test_hard_link_device_and_stream_refusals_are_unchanged_on_a_network_root(win, monkeypatch):
    r = win["root"]
    mk(r, "real.log")
    os.link(r / "real.log", r / "hard.log")
    assert rp(r, "hard.log") is None and rp(r, "CON") is None and rp(r, "real.log:x") is None
