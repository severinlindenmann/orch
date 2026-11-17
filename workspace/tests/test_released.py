"""ORCH-87: a finished ticket says whether its merged change is in the orch installed here, and the update
notes name the tickets that arrived."""

from __future__ import annotations

import subprocess

import pytest

from orch import addons, init, released, tickets, updateinfo

REPO = "severinlindenmann/orch"
PR = "https://github.com/severinlindenmann/orch/pull/"
HAVE, NEWEST, M1, M2 = "a" * 40, "b" * 40, "c" * 40, "d" * 40


@pytest.fixture(autouse=True)
def _fresh():
    released.forget()
    yield
    released.forget()


def ticket(status="done", refs=(), evidence=()):
    return {
        "status": status,
        "refs": [{"kind": "url", "url": u} for u in refs],
        "checklist": [{"id": "c1", "evidence": [{"type": "pr", "ref": u} for u in evidence]}],
    }


def test_ticket_prs_come_from_references_and_evidence_of_the_install_source_only():
    t = ticket(
        refs=[
            PR + "12",
            "https://github.com/severinlindenmann/orch/issues/11",
            "https://github.com/o/other/pull/9",
        ],
        evidence=[PR + "40#top", "https://GitHub.com/SeverinLindenmann/Orch/pull/12"],
    )
    assert released.ticket_prs(t, REPO) == [12, 40]
    assert released.ticket_prs(t, None) == []
    assert released.ticket_prs({"refs": "x", "checklist": [None]}, REPO) == []


def test_pull_requests_in_commit_messages_merge_and_squash():
    msgs = [
        "Merge pull request #1018 from u/feat/x\n\nSuggest button",
        "Style guide in one place (#1026)\n\nbody (#5)",
        "Merge branch 'develop' into x",
        "plain commit",
    ]
    assert released.prs_in(msgs) == {1018, 1026}


@pytest.fixture
def fake(monkeypatch):
    """A GitHub source with installed HAVE (release 27) and newest NEWEST (release 28)."""
    calls = {"pr": 0, "in": 0}
    merges = {
        12: {"merged": True, "sha": M1},
        13: {"merged": True, "sha": M2},
        14: {"merged": False, "sha": None},
    }
    inside = {(M1, HAVE): True, (M2, HAVE): False, (M1, NEWEST): True, (M2, NEWEST): True}

    def merge_commit(n):
        calls["pr"] += 1
        return merges.get(n)

    def contains(sha, head):
        calls["in"] += 1
        return inside.get((sha, head))

    monkeypatch.setattr(released, "source_repo", lambda: REPO)
    monkeypatch.setattr(released, "_merge_commit", merge_commit)
    monkeypatch.setattr(released, "_contains", contains)
    monkeypatch.setattr(updateinfo, "installed", lambda: {"sha": HAVE, "release": 27})
    monkeypatch.setattr(updateinfo, "info", lambda use_cache=True: {"newest": {"sha": NEWEST, "release": 28}})
    return {"calls": calls, "merges": merges, "inside": inside}


def test_merged_and_installed_says_the_installed_release(fake):
    got = released.ticket_release(ticket(refs=[PR + "12"]))
    assert got == {"state": "installed", "release": 27, "text": "In release 27 (installed here)"}
    released.ticket_release(ticket(refs=[PR + "12"]))
    assert fake["calls"] == {"pr": 1, "in": 1}  # a merged PR and a 'contained' answer are asked once


def test_released_but_not_installed_and_merged_not_released(fake):
    got = released.ticket_release(ticket(status="review", evidence=[PR + "13"]))
    assert got == {"state": "released", "release": 28, "text": "In release 28, not installed here yet"}
    fake["inside"][(M2, NEWEST)] = False
    released.forget()
    got = released.ticket_release(ticket(evidence=[PR + "13"]))
    assert got == {"state": "merged", "release": None, "text": "Merged, not released yet"}


def test_every_merged_pull_request_must_be_in_it(fake):
    got = released.ticket_release(ticket(refs=[PR + "12", PR + "13", PR + "14"]))
    assert got["state"] == "released"  # 12 is installed, 13 is not: not installed as a whole


def test_no_line_when_open_unmerged_unknown_or_not_recorded(fake, monkeypatch):
    assert released.ticket_release(ticket(status="active", refs=[PR + "12"])) is None
    assert released.ticket_release(ticket(refs=[PR + "14"])) is None  # not merged
    assert released.ticket_release(ticket(refs=["https://github.com/o/other/pull/12"])) is None
    assert released.ticket_release(ticket(refs=[PR + "99"])) is None  # could not be read
    fake["inside"].pop((M1, HAVE))
    released.forget()
    assert released.ticket_release(ticket(refs=[PR + "12"])) is None  # GitHub did not answer the compare
    monkeypatch.setattr(updateinfo, "installed", lambda: {"sha": None, "release": None})
    assert released.ticket_release(ticket(refs=[PR + "12"])) is None
    monkeypatch.setattr(updateinfo, "installed", lambda: 1 / 0)
    assert released.ticket_release(ticket(refs=[PR + "12"])) is None  # never an error


def test_development_build_without_release_number(fake, monkeypatch):
    monkeypatch.setattr(updateinfo, "installed", lambda: {"sha": HAVE, "release": None})
    monkeypatch.setattr(
        updateinfo, "info", lambda use_cache=True: {"newest": {"sha": NEWEST, "release": None}}
    )
    assert released.ticket_release(ticket(refs=[PR + "12"]))["text"] == "In the version installed here"
    assert released.ticket_release(ticket(refs=[PR + "13"]))["text"] == "Merged, not installed here yet"


def test_github_answers_are_read(monkeypatch):
    monkeypatch.setattr(addons, "_is_local", lambda r: False)
    answers = {
        "pulls/12": {"merged": True, "merge_commit_sha": M1},
        "pulls/14": {"merged": False, "merge_commit_sha": "not a sha"},
        f"compare/{M1}...{HAVE}": {"status": "ahead"},
        f"compare/{M2}...{HAVE}": {"status": "diverged"},
        f"compare/{M1}...{NEWEST}": {"message": "API rate limit exceeded"},
    }
    monkeypatch.setattr(released, "_github", lambda path: answers[path])
    assert released.merge_commit(12) == {"merged": True, "sha": M1}
    assert released.merge_commit(14) == {"merged": False, "sha": None}
    assert released.merge_commit(15) is None  # KeyError stands in for a network error
    assert released.contains(M1, HAVE) is True
    assert released.contains(M2, HAVE) is False
    assert released.contains(M1, NEWEST) is None
    assert released.contains(M1, M1) is True


def _git(folder, *args):
    subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True)
    out = subprocess.run(["git", "-C", str(folder), "rev-parse", "HEAD"], capture_output=True, text=True)
    return out.stdout.strip()


def test_local_source_uses_git(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    _git(src, "config", "user.email", "t@example.invalid")
    _git(src, "config", "user.name", "t")
    _git(src, "remote", "add", "origin", "git@github.com:SeverinLindenmann/orch.git")
    base = _git(src, "commit", "-q", "--allow-empty", "-m", "start")
    _git(src, "checkout", "-q", "-b", "feat")
    _git(src, "commit", "-q", "--allow-empty", "-m", "work")
    _git(src, "checkout", "-q", "main")
    merged = _git(
        src, "merge", "-q", "--no-ff", "feat", "-m", "Merge pull request #5 from u/feat\n\nThe thing"
    )
    monkeypatch.setattr(addons, "repo", lambda: str(src))
    monkeypatch.setattr(addons, "_is_local", lambda r: True)
    assert released.source_repo() == REPO
    assert released.merge_commit(5) == {"merged": True, "sha": merged}
    assert released.merge_commit(6) == {"merged": False, "sha": None}
    assert released.contains(merged, merged) is True
    assert released.contains(base, merged) is True
    assert released.contains(merged, base) is False


def test_update_notes_name_the_tickets_that_arrived(proj, monkeypatch):
    init.init(proj)
    a = tickets.create(proj, "Suggest button", "human:t")
    b = tickets.create(proj, "Style guide", "human:t")
    tickets.create(proj, "Unrelated", "human:t")
    for t, url in ((a, PR + "1018"), (b, PR + "1026")):
        t = tickets.load(proj, t["id"])
        t["refs"] = [{"kind": "url", "url": url}]
        tickets.save(proj, t)
    monkeypatch.setattr(released, "source_repo", lambda: REPO)
    msgs = [
        "Merge pull request #1018 from u/x\n\nfeat: suggest",
        "Style guide (#1026)",
        "Merge pull request #7 from u/y",
    ]
    monkeypatch.setattr(
        updateinfo, "_fetch_messages", lambda kind, a, b=None: msgs if kind == "between" else []
    )
    _, lines = updateinfo.after_update(HAVE, 27, NEWEST, proj)
    at = lines.index("Tickets that arrived:")
    assert sorted(lines[at + 1 :]) == sorted(
        [f"  - {a['key']} Suggest button", f"  - {b['key']} Style guide"]
    )
    assert (
        "Tickets that arrived:" not in updateinfo.after_update(HAVE, 27, NEWEST)[1]
    )  # no workspace: no list
    monkeypatch.setattr(
        updateinfo,
        "info",
        lambda use_cache=True: {
            "installed": {"label": "orch 27", "sha": HAVE},
            "newest": {"label": "orch 28", "sha": NEWEST},
            "update_available": True,
            "changes": [],
        },
    )
    assert updateinfo.announce_lines(proj)[1:] == [
        "Tickets that come with it:",
        f"  - {a['key']} Suggest button",
        f"  - {b['key']} Style guide",
    ]
