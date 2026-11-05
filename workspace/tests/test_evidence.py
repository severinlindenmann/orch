"""Proof files (--file), proof chips and marks in ticket show, gitignore line."""

import json
import os

import pytest

from orch import skills, tickets


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


@pytest.fixture
def tid(proj, run, new_ticket):
    t = new_ticket("Q3 invoice export")
    for text in ("Export CSV", "Send it"):
        run("check", "add", t, text)
    return t


def test_file_is_copied_with_metadata(proj, run, validate, tid):
    out = proj / "out"
    out.mkdir()
    (out / "q3 invoices.csv").write_text("a,b\n" * 100)
    code, text, _ = run(
        "check", "done", tid, "c1", "--file", "out/q3 invoices.csv", "--title", "Q3 invoices",
        "--role", "result", "--by", "agent:claude-code",
    )  # fmt: skip
    assert code == 0 and "Proof copied: .orch/tickets/" in text
    t = read(proj, tid)
    validate(t)
    ev = t["checklist"][0]["evidence"][0]
    assert ev["type"] == "file" and ev["title"] == "Q3 invoices" and ev["role"] == "result"
    assert ev["by"] == "agent:claude-code" and ev["at"].endswith("Z") and "\\" not in ev["ref"]
    assert (proj / ev["ref"]).read_text() == "a,b\n" * 100
    assert (proj / ev["ref"]).parent == proj / ".orch" / "tickets" / tid / "evidence"


def test_same_name_twice_keeps_both(proj, run, tid):
    (proj / "f.txt").write_text("1")
    run("check", "done", tid, "c1", "--file", "f.txt")
    (proj / "f.txt").write_text("2")
    run("check", "done", tid, "c2", "--file", "f.txt")
    t = read(proj, tid)
    refs = [c["evidence"][0]["ref"] for c in t["checklist"]]
    assert len(set(refs)) == 2 and [(proj / r).read_text() for r in refs] == ["1", "2"]


def test_too_big_refused(proj, run, tid, monkeypatch):
    big = proj / "demo.mov"
    big.write_bytes(b"x")
    monkeypatch.setattr(tickets, "MAX_PROOF_BYTES", 0)
    code, _, err = run("check", "done", tid, "c1", "--file", "demo.mov")
    assert code == 2 and "at most 25 MB" in err and "Use --url or --note" in err
    assert not (proj / ".orch" / "tickets" / tid / "evidence").exists()


def test_limit_is_25_mb():
    assert tickets.MAX_PROOF_BYTES == 25 * 1024 * 1024


def test_outside_workspace_refused(proj, run, tid, tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}_outside.txt"
    outside.write_text("secret")
    for p in (str(outside), "../" + outside.name, "/etc/hosts"):
        code, _, err = run("check", "done", tid, "c1", "--file", p)
        assert code == 2 and "must be inside this workspace" in err, p
    assert not (proj / ".orch" / "tickets" / tid / "evidence").exists()


def test_symlinks_refused(proj, run, tid, tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}_key"
    outside.write_text("secret")
    try:
        os.symlink(outside, proj / "link.txt")
        (proj / "real").mkdir()
        os.symlink(proj / "real", proj / "linkdir")
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks here")
    (proj / "real" / "ok.txt").write_text("fine")
    assert run("check", "done", tid, "c1", "--file", "link.txt")[0] == 2
    assert run("check", "done", tid, "c1", "--file", "linkdir/ok.txt")[0] == 2
    assert not (proj / ".orch" / "tickets" / tid / "evidence").exists()


def test_secrets_git_dirs_and_missing_refused(proj, run, tid):
    (proj / ".orch" / "secrets").mkdir(parents=True)
    (proj / ".orch" / "secrets" / "k").write_text("k")
    assert run("check", "done", tid, "c1", "--file", ".orch/secrets/k")[0] == 2
    assert run("check", "done", tid, "c1", "--file", "nope.txt")[0] == 2
    assert run("check", "done", tid, "c1", "--file", ".")[0] == 2


def test_windows_safe_name_and_bad_role(proj, run, tid):
    (proj / "x").write_text("1")
    assert run("check", "done", tid, "c1", "--file", "x", "--role", "huge")[0] == 2
    assert tickets._proof_name("con.txt") == "_con.txt"
    assert tickets._proof_name("a:b*c?.csv") == "a_b_c_.csv"


def test_gitignore_line():
    assert ".orch/tickets/*/evidence/" in skills.GITIGNORE_LINES


def test_show_chips_marks_and_finish_line(proj, run, tid):
    (proj / "q3.csv").write_text("x" * 2048)
    run("check", "done", tid, "c1", "--file", "q3.csv", "--title", "Q3 invoices", "--role", "result",
        "--by", "agent:claude-code")  # fmt: skip
    run("check", "done", tid, "c1", "--command", "pytest -q", "--by", "agent:claude-code")
    text = run("ticket", "show", tid)[1]
    assert "Q3 invoices (file, 2 KB)" in text and "○ Agent says" in text
    assert "All done" not in text
    run("check", "done", tid, "c2", "--note", "Looks right", "--by", "human:severin")
    text = run("ticket", "show", tid)[1]
    assert "✓ All done · 2 of 2" in text
    assert "Looks right   ● You" in text
    assert "result  Q3 invoices" in text


def test_chip_shapes(proj, run, tid):
    sha = "3f9a1c2e4b5d6a7f8091"
    run("check", "done", tid, "c1", "--commit", sha, "--pr", "PR #88", "--by", "agent:x")
    run("check", "done", tid, "c2", "--command", "uv run pytest", "--by", "agent:x")
    text = run("ticket", "show", tid)[1]
    assert "3f9a1c2" in text and sha not in text and "PR #88" in text


def test_missing_copy_says_another_computer(proj, run, tid):
    (proj / "q3.csv").write_text("x")
    run("check", "done", tid, "c1", "--file", "q3.csv", "--title", "Q3 invoices")
    ref = read(proj, tid)["checklist"][0]["evidence"][0]["ref"]
    (proj / ref).unlink()
    assert "Q3 invoices (file on another computer)" in run("ticket", "show", tid)[1]


def test_mark_falls_back_to_history_line(proj, run, tid):
    run("check", "done", tid, "c1", "--note", "old style", "--by", "human:severin")

    def strip(t):
        t["checklist"][0]["evidence"][0].pop("by")

    tickets.apply_op(proj, tid, strip)
    assert "● You" in run("ticket", "show", tid)[1]


def test_symlinked_evidence_dir_refused(proj, run, tid, tmp_path):
    target = tmp_path.parent / f"{tmp_path.name}_elsewhere"
    target.mkdir()
    ticket_dir = proj / ".orch" / "tickets" / tid
    ticket_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, ticket_dir / "evidence")
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks here")
    (proj / "f.txt").write_text("x")
    code, _, err = run("check", "done", tid, "c1", "--file", "f.txt")
    assert code == 2 and "is a link" in err
    assert list(target.iterdir()) == []


def test_symlinked_tickets_dir_component_refused(proj, run, tid, tmp_path):
    target = tmp_path.parent / f"{tmp_path.name}_t2"
    target.mkdir()
    try:
        os.symlink(target, proj / ".orch" / "tickets" / tid)
    except (OSError, FileExistsError, NotImplementedError):
        pytest.skip("cannot link")
    (proj / "f.txt").write_text("x")
    assert run("check", "done", tid, "c1", "--file", "f.txt")[0] == 2
    assert list(target.iterdir()) == []
