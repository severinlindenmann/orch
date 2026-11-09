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


@pytest.mark.parametrize("hint", ["run.sh", "page.html", "x.svg", "x.exe", "noext", ".md", "..", "a.py", ""])
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
