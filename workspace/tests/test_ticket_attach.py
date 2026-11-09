"""Files kept with a ticket (orch ticket attach): the server picks the name, type and content are checked."""

import json
import os
import sys

import pytest

from orch import tickets
from orch.errors import Refused


def _new(run):
    return json.loads(run("ticket", "new", "Make a report", "--json", "--by", "human:t")[1])["id"]


def test_attach_keeps_text_as_a_file_with_a_history_line(proj, run):
    tid = _new(run)
    r = tickets.attach(proj, tid, "note.md", b"# Hello\n" * 5, "human:t")
    assert r["name"] == "note.md" and r["path"] == f".orch/tickets/{tid}/artifacts/note.md"
    assert (proj / r["path"]).read_bytes() == b"# Hello\n" * 5
    assert tickets.load(proj, tid)["history"][-1]["text"] == "Attached note.md"
    again = tickets.attach(proj, tid, "note.md", b"two", "human:t")
    assert again["name"] == "note (2).md"  # never overwritten
    assert [f["name"] for f in tickets.artifacts_list(proj, tid)] == ["note (2).md", "note.md"]


@pytest.mark.parametrize(
    "hint,final",
    [
        ("../../etc/passwd.txt", "passwd.txt"),
        ("..\\..\\secret.md", "secret.md"),
        ("/abs/path/plan.md", "plan.md"),
        ("we ird<>:name?.TXT", "we ird___name_.txt"),
        ("a..b.md", "a.b.md"),
    ],
)
def test_attach_name_is_a_safe_base_name(proj, run, hint, final):
    tid = _new(run)
    r = tickets.attach(proj, tid, hint, b"x", "human:t")
    assert r["name"] == final
    assert (proj / r["path"]).parent == proj / ".orch" / "tickets" / tid / "artifacts"


@pytest.mark.parametrize(
    "hint", ["run.sh", "page.html", "x.svg", "x.xml", "CON", "x.exe", "noext", ".md", "..", "a.py", ""]
)
def test_attach_refuses_other_types(proj, run, hint):
    tid = _new(run)
    with pytest.raises(Refused):
        tickets.attach(proj, tid, hint, b"x", "human:t")
    assert tickets.artifacts_list(proj, tid) == []


def test_attach_checks_content_and_size(proj, run):
    tid = _new(run)
    for hint, data in (
        ("a.txt", b""),
        ("a.txt", b"nul\x00byte"),
        ("a.txt", b"\xff\xfe\x00bad"),
        ("a.png", b"not a png"),
        ("a.webp", b"RIFF1234XXXX"),
        ("big.txt", b"x" * (tickets.ATTACH_MAX + 1)),
    ):
        with pytest.raises(Refused):
            tickets.attach(proj, tid, hint, data, "human:t")
    ok = tickets.attach(proj, tid, "p.png", b"\x89PNG\r\n\x1a\n....", "human:t")
    assert ok["name"] == "p.png"


def test_attach_refuses_a_linked_artifacts_folder(proj, run, tmp_path):
    tid = _new(run)
    outside = tmp_path / "outside"
    outside.mkdir()
    (proj / ".orch" / "tickets" / tid).mkdir(exist_ok=True)
    os.symlink(outside, proj / ".orch" / "tickets" / tid / "artifacts")
    with pytest.raises(Refused):
        tickets.attach(proj, tid, "n.md", b"x", "human:t")
    assert list(outside.iterdir()) == []


def test_attach_does_not_follow_a_planted_link_in_the_folder(proj, run, tmp_path):
    tid = _new(run)
    d = tickets.artifacts_dir(proj, tid)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    os.symlink(victim, d / "note.md")
    r = tickets.attach(proj, tid, "note.md", b"new", "human:t")
    assert victim.read_text() == "keep" and r["name"] == "note (2).md"


def test_cli_attach_reads_stdin(proj, run, monkeypatch):
    import io

    tid = _new(run)

    class In:
        buffer = io.BytesIO("Grüsse\n".encode())

    monkeypatch.setattr(sys, "stdin", In())
    code, out, _ = run("ticket", "attach", tid, "--name", "../x/list.txt", "--by", "human:t", "--json")
    assert code == 0 and json.loads(out)["name"] == "list.txt"


def test_attach_refuses_a_bad_id_and_a_link_above_artifacts(proj, run, tmp_path, monkeypatch):
    with pytest.raises(Refused):
        tickets.attach(proj, "../../x", "n.md", b"x", "human:t")
    import io

    monkeypatch.setattr(sys, "stdin", type("In", (), {"buffer": io.BytesIO(b"x")})())
    code, _, err = run("ticket", "attach", "../../x", "--name", "n.md", "--by", "human:t")
    assert code != 0
    tid = _new(run)
    outside = tmp_path / "outside2"
    (outside / tid).mkdir(parents=True)
    import shutil

    shutil.rmtree(proj / ".orch" / "tickets" / tid, ignore_errors=True)
    os.symlink(outside / tid, proj / ".orch" / "tickets" / tid)  # the ticket folder is a link
    with pytest.raises(Refused):
        tickets.attach(proj, tid, "n.md", b"x", "human:t")
    assert list((outside / tid).iterdir()) == []


def test_attach_exact_name_is_written_once(proj, run):
    tid = _new(run)
    a = tickets.attach(proj, tid, "", b"one", "human:t", exact="note-abc12345.md")
    b = tickets.attach(proj, tid, "", b"two", "human:t", exact="note-abc12345.md")
    assert b["existed"] is True and a["path"] == b["path"]
    assert (proj / a["path"]).read_bytes() == b"one"
    with pytest.raises(Refused):
        tickets.attach(proj, tid, "", b"x", "human:t", exact="../evil.md")


def test_attach_name_edges():
    assert tickets.attach_name("CON.txt") == "_CON.txt"
    assert tickets.attach_name(("a" * 79) + " .md").endswith("a.md")


def test_edit_and_fields_refuse_the_protected_ones(proj, run):
    tid = _new(run)
    for k in ("title_auto", "description", "description_by"):
        with pytest.raises(Refused):
            tickets.edit(proj, tid, None, "agent:x", {k: "x"})
        with pytest.raises(Refused):
            tickets.clean_field(k, "x")
        with pytest.raises(Refused):
            tickets.create(proj, "T", "agent:x", fields={k: "x"})
    assert "description" not in tickets.load(proj, tid)


def test_a_file_system_without_hard_links_still_keeps_the_file(proj, run, monkeypatch):
    tid = _new(run)

    def no_link(*a, **k):
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_link)
    r = tickets.attach(proj, tid, "", b"text", "human:t", exact="note-aaaa1111.md")
    assert (proj / r["path"]).read_bytes() == b"text"
    again = tickets.attach(proj, tid, "", b"other", "human:t", exact="note-aaaa1111.md")
    assert again["existed"] is True and (proj / r["path"]).read_bytes() == b"text"
    two = tickets.attach(proj, tid, "x.md", b"1", "human:t")
    three = tickets.attach(proj, tid, "x.md", b"2", "human:t")
    assert (two["name"], three["name"]) == ("x.md", "x (2).md")
    assert [p.name for p in (proj / r["path"]).parent.iterdir() if p.name.startswith(".")] == []


def test_a_file_swapped_in_after_linking_is_refused(proj, run, monkeypatch):
    tid = _new(run)
    real = os.link

    def link_then_swap(src, dst, *a, **k):
        real(src, dst, *a, **k)
        d = proj / ".orch" / "tickets" / tid / "artifacts"
        (d / dst).unlink()
        (d / dst).write_bytes(b"someone else")  # a different file under the final name

    monkeypatch.setattr(os, "link", link_then_swap)
    with pytest.raises(Refused):
        tickets.attach(proj, tid, "n.md", b"mine", "human:t")
    assert not (proj / ".orch" / "tickets" / tid / "artifacts" / "n.md").exists()


def test_part_files_are_hidden_and_old_ones_swept(proj, run):
    tid = _new(run)
    d = tickets.artifacts_dir(proj, tid)
    old = d / ".abc.part"
    old.write_bytes(b"x")
    os.utime(old, (1, 1))
    fresh = d / ".fresh.part"
    fresh.write_bytes(b"y")
    assert tickets.artifacts_list(proj, tid) == []  # dotfiles are not listed
    tickets.attach(proj, tid, "n.md", b"z", "human:t")
    assert not old.exists() and fresh.exists()
    assert [f["name"] for f in tickets.artifacts_list(proj, tid)] == ["n.md"]


def test_attach_works_where_links_cannot_be_followed_or_made(proj, run, monkeypatch):
    """Windows CPython: no follow_symlinks for os.link (NotImplementedError); some file systems: no links."""
    tid = _new(run)
    real = os.link

    def windows_link(src, dst, *a, follow_symlinks=True, **k):
        if not follow_symlinks:
            raise NotImplementedError("link: follow_symlinks unavailable on this platform")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(os, "link", windows_link)
    monkeypatch.setattr(os, "supports_follow_symlinks", set())  # os.link is not in it
    r = tickets.attach(proj, tid, "a.md", b"one", "human:t")
    assert (proj / r["path"]).read_bytes() == b"one"

    def broken(*a, **k):
        raise NotImplementedError("no links at all")

    monkeypatch.setattr(os, "link", broken)
    r2 = tickets.attach(proj, tid, "b.md", b"two", "human:t")
    assert (proj / r2["path"]).read_bytes() == b"two"
    assert [p.name for p in (proj / r["path"]).parent.iterdir() if p.name.startswith(".")] == []
