"""orch.safefile: the one reader for ticket folder files (hard link, FIFO, swapped folder, links, shapes)."""

import os

import pytest

from orch import safefile

TID = "t_abcdef12"


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "ws"
    for f in ("artifacts", "evidence"):
        (r / ".orch" / "tickets" / TID / f).mkdir(parents=True)
    (r / ".orch" / "secrets").mkdir()
    (r / ".orch" / "secrets" / "key.txt").write_text("SECRET")
    return r


@pytest.fixture(params=[True, False], ids=["dir_fd", "windows_path"])
def mode(request, monkeypatch):
    monkeypatch.setattr(safefile, "_DIR_FD", request.param)
    return request.param


def rd(root, name, folder="artifacts", cap=1000, tid=TID):
    return safefile.read_ticket_file(root, tid, folder, name, cap)


def test_reads_a_plain_file_and_a_file_in_a_subfolder(root, mode):
    a = root / ".orch" / "tickets" / TID / "artifacts"
    (a / "n.md").write_text("hi")
    (a / "sub").mkdir()
    (a / "sub" / "x.txt").write_text("deep")
    assert rd(root, "n.md") == b"hi" and rd(root, "sub/x.txt") == b"deep"
    (root / ".orch" / "tickets" / TID / "evidence" / "p.txt").write_text("proof")
    assert rd(root, "p.txt", "evidence") == b"proof"


def test_hard_link_to_a_secret_is_refused(root, mode):
    os.link(root / ".orch" / "secrets" / "key.txt", root / ".orch" / "tickets" / TID / "artifacts" / "k.txt")
    assert rd(root, "k.txt") is None


def test_fifo_does_not_hang(root, mode):
    if not hasattr(os, "mkfifo"):
        pytest.skip("no FIFOs here")
    os.mkfifo(root / ".orch" / "tickets" / TID / "artifacts" / "pipe")
    assert rd(root, "pipe") is None  # returns at once (the test would hang otherwise)


def test_links_are_never_followed(root, mode, tmp_path):
    a = root / ".orch" / "tickets" / TID / "artifacts"
    os.symlink(root / ".orch" / "secrets" / "key.txt", a / "l.txt")
    os.symlink(root / ".orch" / "secrets", a / "dir")
    assert rd(root, "l.txt") is None and rd(root, "dir/key.txt") is None
    ev = root / ".orch" / "tickets" / TID / "evidence"
    ev.rmdir()
    os.symlink(root / ".orch" / "secrets", ev)
    assert rd(root, "key.txt", "evidence") is None


def test_a_folder_swapped_for_a_link_while_reading_is_not_followed(root, monkeypatch):
    """After the folder was opened, its path is swapped for a link to the secrets: the file is still read
    from the folder we hold, never from the link."""
    monkeypatch.setattr(safefile, "_DIR_FD", True)
    a = root / ".orch" / "tickets" / TID / "artifacts"
    (a / "x.txt").write_text("real")
    (root / ".orch" / "secrets" / "x.txt").write_text("SECRET")
    real_open = os.open
    swapped = []

    def swapping_open(path, flags, *a_, **kw):
        if path == "x.txt" and "dir_fd" in kw and not swapped:
            os.rename(a, a.with_name("artifacts-moved"))
            os.symlink(root / ".orch" / "secrets", a)
            swapped.append(1)
        return real_open(path, flags, *a_, **kw)

    monkeypatch.setattr(os, "open", swapping_open)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {swapping_open})
    assert rd(root, "x.txt") == b"real" and swapped


@pytest.mark.parametrize(
    "name",
    [
        "../../secrets/key.txt",
        "a/../n.md",
        "/etc/passwd",
        "",
        ".",
        "a//b",
        "C:x",
        "a\\b",
        "n\0.md",
        "sub/..",
        "x" * 300,
    ],
)
def test_odd_names_are_refused(root, mode, name):
    (root / ".orch" / "tickets" / TID / "artifacts" / "n.md").write_text("hi")
    assert rd(root, name) is None


def test_odd_ticket_and_folder_are_refused(root, mode):
    assert rd(root, "n.md", tid="../x") is None and rd(root, "n.md", tid="t_x") is None
    assert rd(root, "key.txt", folder="../secrets") is None and rd(root, "n.md", folder="tickets") is None


def test_size_cap_and_directories(root, mode):
    a = root / ".orch" / "tickets" / TID / "artifacts"
    (a / "big").write_bytes(b"x" * 11)
    (a / "d").mkdir()
    with pytest.raises(safefile.TooLarge):
        rd(root, "big", cap=10)
    assert rd(root, "big", cap=11) == b"x" * 11 and rd(root, "d") is None and rd(root, "nope") is None


def test_an_fstat_error_closes_the_file(root, mode, monkeypatch):
    """A failing fstat after open never leaks the handle (both paths: dir_fd and Windows)."""
    (root / ".orch" / "tickets" / TID / "artifacts" / "n.md").write_text("hi")
    opened, closed = [], []
    real_open, real_close, real_fstat = os.open, os.close, os.fstat

    def fake_open(*a, **kw):
        fd = real_open(*a, **kw)
        opened.append(fd)
        return fd

    def fake_close(fd):
        closed.append(fd)
        real_close(fd)

    def fake_fstat(fd):
        if fd in opened:
            raise OSError("fstat failed")
        return real_fstat(fd)

    monkeypatch.setattr(safefile.os, "open", fake_open)
    monkeypatch.setattr(safefile.os, "close", fake_close)
    monkeypatch.setattr(safefile.os, "fstat", fake_fstat)
    assert rd(root, "n.md") is None
    monkeypatch.undo()
    assert opened and sorted(opened) == sorted(closed)


@pytest.mark.parametrize("fallback", [False, True])
def test_project_file_reader(tmp_path, monkeypatch, fallback):
    from orch import safefile

    monkeypatch.setattr(safefile, "_DIR_FD", not fallback)
    root = tmp_path / "project"
    root.mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "spec.md").write_bytes(b"hello")
    assert safefile.open_file_ref(root, "docs/spec.md", 5) == b"hello"
    with pytest.raises(safefile.TooLarge):
        safefile.open_file_ref(root, "docs/spec.md", 4)
    for path in [
        "../secret",
        "/etc/passwd",
        ".orch/secrets/x",
        ".git/config",
        "docs/../docs/spec.md",
        "x\0y",
    ]:
        assert safefile.open_file_ref(root, path, 100) is None
    (root / "symlink").symlink_to(root / "docs" / "spec.md")
    (root / "folder").symlink_to(root / "docs", target_is_directory=True)
    os.link(root / "docs" / "spec.md", root / "hardlink")
    for path in ["symlink", "folder/spec.md", "hardlink"]:
        assert safefile.open_file_ref(root, path, 100) is None
    if hasattr(os, "mkfifo"):
        os.mkfifo(root / "pipe")
        assert safefile.open_file_ref(root, "pipe", 100) is None
