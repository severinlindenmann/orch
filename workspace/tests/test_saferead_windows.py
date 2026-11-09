"""saferead.read_private on Windows (no dir_fd, no O_NOFOLLOW, text-mode os.open), simulated on POSIX:
winacl._windows is True, the reparse-attribute seam is replaced, and os.open must never get a dir_fd."""

import os

import pytest

from orch import saferead, winacl


@pytest.fixture
def winread(monkeypatch, tmp_path):
    root = tmp_path.resolve()
    state = {"reparse": set(), "flags": []}
    real_open = os.open

    def spy_open(path, flags, *a, **kw):
        assert "dir_fd" not in kw, "dir_fd is not supported on Windows"
        state["flags"].append(flags)
        return real_open(path, flags & ~0x8000, *a, **kw)  # 0x8000 = the simulated O_BINARY

    monkeypatch.setattr(winacl, "_windows", lambda: True)
    monkeypatch.setattr(winacl, "_attrs", lambda p: winacl.REPARSE if str(p) in state["reparse"] else 0)
    monkeypatch.setattr(os, "O_BINARY", 0x8000, raising=False)
    monkeypatch.setattr(os, "open", spy_open)
    state["root"] = root
    return state


def test_plain_file_is_read_in_binary_mode(winread):
    f = winread["root"] / "keys" / "ws" / "human.key"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"ab\r\ncd\x1a\r\n")  # CRLF and Ctrl-Z: text mode would change or cut these
    assert saferead.read_private(winread["root"], "keys/ws/human.key", 100) == b"ab\r\ncd\x1a\r\n"
    assert winread["flags"][-1] & 0x8000


def test_missing_and_oversize_and_odd_names_are_none(winread):
    r = winread["root"]
    assert saferead.read_private(r, "nope.json", 100) is None
    (r / "big.json").write_bytes(b"x" * 101)
    assert saferead.read_private(r, "big.json", 100) is None
    (r / "ok.json").write_bytes(b"{}")
    for bad in ("", "../ok.json", "a/../ok.json", "ok.json:stream", "a\\ok.json"):
        assert saferead.read_private(r, bad, 100) is None


def test_reparse_point_on_any_part_or_the_root_is_none(winread):
    r = winread["root"]
    (r / "d").mkdir()
    (r / "d" / "f.json").write_bytes(b"{}")
    assert saferead.read_private(r, "d/f.json", 100) == b"{}"
    for bad in (r / "d", r / "d" / "f.json", r):
        winread["reparse"] = {str(bad)}
        assert saferead.read_private(r, "d/f.json", 100) is None


def test_symlink_and_hard_link_and_fifo_are_none(winread):
    r = winread["root"]
    (r / "real.json").write_bytes(b"{}")
    os.symlink(r / "real.json", r / "link.json")
    assert saferead.read_private(r, "link.json", 100) is None
    os.link(r / "real.json", r / "hard.json")
    assert saferead.read_private(r, "hard.json", 100) is None  # two names
    os.mkfifo(r / "pipe.json")
    assert saferead.read_private(r, "pipe.json", 100) is None  # never blocks, never read
    (r / "dir.json").mkdir()
    assert saferead.read_private(r, "dir.json", 100) is None


def test_swap_between_lstat_and_open_is_none(winread, monkeypatch):
    r = winread["root"]
    (r / "a.json").write_bytes(b"{}")
    real = os.lstat

    def lie(p, *a, **k):
        st = real(p, *a, **k)
        return os.stat_result((*tuple(st)[:1], st.st_ino + 1, *tuple(st)[2:]))

    monkeypatch.setattr(os, "lstat", lie)
    assert saferead.read_private(r, "a.json", 100) is None


def test_posix_path_is_unchanged(tmp_path, monkeypatch):
    (tmp_path / "a.json").write_bytes(b"{}")
    monkeypatch.setattr(saferead, "_read_private_windows", lambda *a: pytest.fail("windows branch on POSIX"))
    assert saferead.read_private(tmp_path.resolve(), "a.json", 100) == b"{}"
