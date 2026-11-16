"""R4.1 banned-word diff check: planted samples in a throwaway git repo."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_banned_words as cbw  # noqa: E402


def git(repo, *a):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *a], check=True, capture_output=True)


def make_repo(tmp_path, base_text, new_text, name="doc.md"):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / name).write_text(base_text)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-qb", "pr")
    (tmp_path / name).write_text(new_text)
    git(tmp_path, "commit", "-qam", "pr")


def run(tmp_path, labels="", capsys=None):
    return cbw.main(["--base", "main", "--repo", str(tmp_path), "--labels", labels])


def test_added_word_fails(tmp_path, capsys):
    make_repo(tmp_path, "hello\n", "hello\nPlease sign the request\n")
    assert run(tmp_path) == 1
    out = capsys.readouterr().out
    assert "doc.md:2: sign" in out and "owner-approved" in out


def test_each_word_fails(tmp_path):
    for w in ["signing", "Signature", "Signed", "signs", "certificate", "keypair", "approval", "GATE"]:
        assert cbw.find_hits(f"+++ b/x\n@@ -0,0 +1 @@\n+a {w} b\n", []), w


def test_deleted_word_passes(tmp_path):
    make_repo(tmp_path, "a signature here\nkeep\n", "keep\n")
    assert run(tmp_path) == 0


def test_label_passes(tmp_path):
    make_repo(tmp_path, "hello\n", "hello\ncertificate\n")
    assert run(tmp_path, labels="docs, owner-approved") == 0


def test_false_positives_pass(tmp_path):
    text = "design signal assign navigate aggregate delegate designate gateway resign consign\n"
    make_repo(tmp_path, "x\n", "x\n" + text)
    assert run(tmp_path) == 0


def test_login_words_pass():
    for w in ["Sign in", "sign-in", "signed in", "Sign out", "sign up", "sign_in"]:
        assert cbw.find_hits(f"+++ b/x\n@@ -0,0 +1 @@\n+{w} to the page\n", []) == [], w
    assert cbw.find_hits("+++ b/x\n@@ -0,0 +1 @@\n+sign it, then sign in\n", []) != []


def test_allowlisted_path_passes(tmp_path):
    diff = "+++ b/brand/tests/test_banned_words.py\n@@ -0,0 +1 @@\n+sign\n"
    assert cbw.find_hits(diff, ["brand/tests/test_banned_words.py"]) == []
    assert cbw.find_hits(diff, []) != []


def test_line_numbers_follow_hunks():
    diff = "+++ b/f\n@@ -1,2 +10,3 @@\n+ok\n+gate\n+ok\n"
    assert cbw.find_hits(diff, []) == [("f", 11, "gate")]


def test_checker_own_files_are_allowlisted():
    allow = cbw.allow_patterns()
    for f in ["scripts/check_banned_words.py", "brand/tests/test_banned_words.py"]:
        assert any(__import__("fnmatch").fnmatch(f, p) for p in allow)


def test_word_already_on_a_changed_line_passes(tmp_path):
    # one-line mockup pages: changing a link re-adds words that were already there
    make_repo(tmp_path, '<link href="a.css"><p>Open the gate</p>\n', '<link href="b.css"><p>Open the gate</p>\n')
    assert run(tmp_path) == 0


def test_extra_copy_of_a_word_still_fails(tmp_path, capsys):
    make_repo(tmp_path, "<p>Open the gate</p>\n", "<p>Open the gate, then the other gate</p>\n")
    assert run(tmp_path) == 1
    assert "doc.md:1: gate" in capsys.readouterr().out


def test_word_removed_in_another_file_does_not_cancel(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.md").write_text("the gate\n")
    (tmp_path / "b.md").write_text("x\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-qb", "pr")
    (tmp_path / "a.md").write_text("x\n")
    (tmp_path / "b.md").write_text("x\nthe gate\n")
    git(tmp_path, "commit", "-qam", "pr")
    assert run(tmp_path) == 1


def test_removed_line_starting_with_dashes_is_not_a_header():
    diff = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1 +1 @@\n--- gate here\n+++ gate here\n"
    assert cbw.find_hits(diff, []) == []
