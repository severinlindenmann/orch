"""Artifacts named by a ticket reach the phone through the safe file reader."""

import hashlib

import pytest
from test_ticket_view import conn  # noqa: F401 (fixture)

from orch import phone_view, tickets


def artifact(proj, tid, name, data=b"artifact bytes"):
    path = proj / ".orch/tickets" / tid / "artifacts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_question_artifact_reaches_phone(proj, run, new_ticket, conn):  # noqa: F811
    tid = new_ticket("Choose a shortlist")
    artifact(proj, tid, "shortlist.md")
    assert run("ask", tid, "See artifacts/shortlist.md")[0] == 0
    view = phone_view.view_for(proj, tid)
    (attachment,) = view["attachments"]
    assert attachment == {
        "kind": "file",
        "title": "shortlist.md",
        "blob_id": attachment["blob_id"],
        "name": "shortlist.md",
        "size": len(b"artifact bytes"),
        "at": tickets.artifacts_list(proj, tid)[0]["mtime"],
        "id": phone_view.artifact_id("file", f".orch/tickets/{tid}/artifacts/shortlist.md"),
        "rev": hashlib.sha256(b"artifact bytes").hexdigest(),
    }
    assert conn.blobs[attachment["blob_id"]] == b"artifact bytes"


def test_summary_only_sends_named_files(proj, run, new_ticket, conn):  # noqa: F811
    tid = new_ticket("Agenda")
    artifact(proj, tid, "agenda.pdf")
    artifact(proj, tid, "unmentioned.md", b"private")
    assert run("ticket", "summary", tid, "Draft is in agenda.pdf")[0] == 0
    view = phone_view.view_for(proj, tid)
    assert [a["name"] for a in view["attachments"]] == ["agenda.pdf"]
    assert list(conn.blobs.values()) == [b"artifact bytes"]


def test_longer_word_does_not_name_artifact(proj, run, new_ticket, conn):  # noqa: F811
    tid = new_ticket("List")
    artifact(proj, tid, "list.md")
    assert run("ask", tid, "See shortlist.md")[0] == 0
    assert phone_view.view_for(proj, tid)["attachments"] == []
    assert not conn.blobs


def test_symlink_is_never_uploaded(proj, run, new_ticket, conn):  # noqa: F811
    tid = new_ticket("Linked file")
    outside = proj / "outside.md"
    outside.write_bytes(b"private")
    path = artifact(proj, tid, "linked.md")
    path.unlink()
    path.symlink_to(outside)
    assert run("ask", tid, "See artifacts/linked.md")[0] == 0
    assert phone_view.view_for(proj, tid)["attachments"] == []
    assert not conn.blobs


@pytest.mark.parametrize("answered", [False, True])
def test_nested_artifact_in_question_option(proj, new_ticket, conn, answered):  # noqa: F811
    tid = new_ticket("Options")
    artifact(proj, tid, "draft/chart.PNG")
    ticket = tickets.load(proj, tid)
    ticket["questions"] = [
        {
            "text": "Choose",
            "options": ["Use artifacts/draft/chart.PNG"],
            "answer": "yes" if answered else None,
        }
    ]
    tickets.save(proj, ticket)
    assert phone_view.named_artifacts(proj, ticket) == ["draft/chart.PNG"]
    (attachment,) = phone_view.view_for(proj, tid)["attachments"]
    assert attachment["title"] == "draft/chart.PNG"
    assert attachment["name"] == "chart.PNG"
    assert attachment["kind"] == "image"
    assert conn.blobs[attachment["blob_id"]] == b"artifact bytes"


def test_named_artifacts_cap_and_order(proj, new_ticket):
    tid = new_ticket("Many artifacts")
    names = [f"file{i:02}.md" for i in range(25)]
    for name in reversed(names):
        artifact(proj, tid, name)
    ticket = tickets.load(proj, tid)
    ticket["summary"] = " ".join(reversed(names))
    assert phone_view.named_artifacts(proj, ticket) == names[:20]


@pytest.mark.parametrize("upload, state", [(False, {"blobs": {}}), (True, None)])
def test_disabled_upload(proj, new_ticket, conn, upload, state):  # noqa: F811
    tid = new_ticket("No upload")
    artifact(proj, tid, "draft.md")
    ticket = tickets.load(proj, tid)
    ticket["summary"] = "draft.md"
    assert phone_view.attachments(proj, ticket, state, upload=upload) == []
    assert not conn.blobs


def test_oversized_artifact_is_skipped(proj, new_ticket, conn, monkeypatch):  # noqa: F811
    tid = new_ticket("Too large")
    artifact(proj, tid, "draft.md")
    ticket = tickets.load(proj, tid)
    ticket["summary"] = "draft.md"
    tickets.save(proj, ticket)
    monkeypatch.setattr(tickets, "MAX_PROOF_BYTES", 1)
    assert phone_view.view_for(proj, tid)["attachments"] == []
    assert not conn.blobs
