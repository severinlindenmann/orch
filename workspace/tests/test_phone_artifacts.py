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


@pytest.mark.parametrize(
    "name, text, matched",
    [
        ("out.md", "See artifacts/out.md", True),
        ("out.md", "See out.md", False),
        ("report", "See report", False),
        ("report", "See artifacts/report", True),
        ("report.pdf", "See report.pdf.bak", False),
        ("report.pdf", "See artifacts/report.pdf.bak", False),
        ("report.pdf", "See report.pdf.", True),
        ("report.pdf", "See /report.pdf", False),
    ],
)
def test_name_matching(proj, new_ticket, name, text, matched):
    tid = new_ticket("Names")
    artifact(proj, tid, name)
    ticket = tickets.load(proj, tid)
    ticket["summary"] = text
    assert phone_view.named_artifacts(proj, ticket) == ([name] if matched else [])


def test_secret_artifact_is_logged_once(proj, run, new_ticket, conn):  # noqa: F811
    tid = new_ticket("Secret")
    artifact(proj, tid, "config.txt", b"api_key = sk-test-ABCDEFGHIJKLMNOPQRSTUV")
    assert run("ask", tid, "See artifacts/config.txt")[0] == 0
    for _ in range(2):
        assert phone_view.view_for(proj, tid)["attachments"] == []
    assert not conn.blobs
    lines = [
        h["text"] for h in tickets.load(proj, tid)["history"] if "was not sent to the phone" in h["text"]
    ]
    assert lines == ["config.txt was not sent to the phone: it looks like it holds a password or key."]
    assert len(phone_view.load_state(proj)["secret_skipped"]) == 1


@pytest.mark.parametrize("data", [b"password = ordinary", b"\xffsk-test-ABCDEFGHIJKLMNOPQRSTUV"])
def test_secret_scan(data):
    assert phone_view._has_secret(data)
    assert not phone_view._has_secret(b"ordinary artifact contents\xff")


def test_hard_link_is_never_uploaded(proj, run, new_ticket, conn):  # noqa: F811
    tid = new_ticket("Hard link")
    outside = proj / "outside.md"
    outside.write_bytes(b"private")
    path = artifact(proj, tid, "linked.md")
    path.unlink()
    path.hardlink_to(outside)
    assert run("ask", tid, "See artifacts/linked.md")[0] == 0
    assert phone_view.view_for(proj, tid)["attachments"] == []
    assert not conn.blobs


def test_aggregate_artifact_cap(proj, new_ticket, conn, monkeypatch):  # noqa: F811
    tid = new_ticket("Aggregate")
    names = [f"file{i}.txt" for i in range(3)]
    for i, name in enumerate(names):
        artifact(proj, tid, name, bytes([65 + i]) * 9 * 1024)
    ticket = tickets.load(proj, tid)
    ticket["summary"] = " ".join(names)
    tickets.save(proj, ticket)
    monkeypatch.setattr(phone_view, "ARTIFACT_BYTES", 20 * 1024)
    atts = phone_view.view_for(proj, tid)["attachments"]
    assert len(atts) == len(conn.blobs) == 2
    assert sum(a["size"] for a in atts) == 18 * 1024


def test_artifacts_leave_room_for_refs(proj, new_ticket, conn):  # noqa: F811
    tid = new_ticket("Refs")
    for name in ("first.md", "second.md"):
        artifact(proj, tid, name, name.encode())
    ticket = tickets.load(proj, tid)
    ticket["summary"] = "first.md second.md"
    ticket["refs"] = [{"url": f"https://a.co/{i}", "title": str(i)} for i in range(49)]
    tickets.save(proj, ticket)
    atts = phone_view.view_for(proj, tid)["attachments"]
    assert {a["url"] for a in atts if "url" in a} == {r["url"] for r in ticket["refs"]}
    assert len(atts) == 50
    assert len(conn.blobs) == 1


def test_artifact_matching_evidence_is_not_added(proj, new_ticket, conn):  # noqa: F811
    tid = new_ticket("Evidence")
    data = b"same evidence and artifact"
    artifact(proj, tid, "report.txt", data)
    evidence = proj / ".orch/tickets" / tid / "evidence" / "proof.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(data)
    ticket = tickets.load(proj, tid)
    ticket["summary"] = "report.txt"
    ticket["checklist"] = [
        {
            "text": "Proof",
            "evidence": [
                {"type": "file", "role": "result", "ref": f".orch/tickets/{tid}/evidence/proof.txt"}
            ],
        }
    ]
    tickets.save(proj, ticket)
    (attachment,) = phone_view.view_for(proj, tid)["attachments"]
    assert attachment["name"] == "proof.txt"
    assert len(conn.blobs) == 1


def test_listing_is_reused_and_bounded(proj, new_ticket, conn, monkeypatch):  # noqa: F811
    tid = new_ticket("Bounded listing")
    artifact(proj, tid, "report.txt")
    ticket = tickets.load(proj, tid)
    ticket["summary"] = "report.txt"
    calls = []

    def listing(root, ticket_id):
        calls.append(ticket_id)
        return [{"name": f"unused{i}.txt"} for i in range(200)] + [{"name": "report.txt"}]

    monkeypatch.setattr(tickets, "artifacts_list", listing)
    assert phone_view.attachments(proj, ticket, {"blobs": {}}) == []
    assert calls == [tid]
    assert not conn.blobs


@pytest.mark.parametrize(
    "name,data,sent,said",
    [
        (
            "offer.pdf",
            b"%PDF-1.7\n1 0 obj << /Filter /FlateDecode >> stream\n\x78\x9c\xff\xfe\x00\x01",
            False,
            "can't be checked",
        ),
        ("sheet.xlsx", b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00\xff\xfe", False, "can't be checked"),
        ("notes.txt", "token = sk-test-ABCDEFGHIJKLMNOPQRSTUV\n".encode("utf-16"), False, "password or key"),
        ("clean.txt", "nothing secret here\n".encode("utf-16"), True, None),
        ("photo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xfe\x00", True, None),
    ],
)
def test_files_that_can_not_be_checked_are_not_sent(proj, run, new_ticket, conn, name, data, sent, said):  # noqa: F811
    """Delta #309: the scan reads text (UTF-8, UTF-16 with BOM); packed or binary files fail closed."""
    tid = new_ticket("Files")
    artifact(proj, tid, name, data)
    assert run("ask", tid, f"See artifacts/{name}")[0] == 0
    phone_view.view_for(proj, tid)
    view = phone_view.view_for(proj, tid)
    assert bool(view["attachments"]) is sent
    lines = [
        h["text"] for h in tickets.load(proj, tid)["history"] if "was not sent to the phone" in h["text"]
    ]
    assert len(lines) == (0 if said is None else 1) and all(said in ln for ln in lines)


def test_a_file_over_the_cap_is_never_loaded(proj, run, new_ticket, conn, monkeypatch):  # noqa: F811
    from orch import safefile

    monkeypatch.setattr(phone_view, "ARTIFACT_BYTES", 100)
    asked = []
    real = safefile.read_ticket_file

    def spy(root, tid, folder, name, max_bytes):
        asked.append(max_bytes)
        return real(root, tid, folder, name, max_bytes)

    monkeypatch.setattr(safefile, "read_ticket_file", spy)
    tid = new_ticket("Big")
    artifact(proj, tid, "big.txt", b"x" * 500)
    assert run("ask", tid, "See artifacts/big.txt")[0] == 0
    assert phone_view.view_for(proj, tid)["attachments"] == []
    assert asked == [100]  # the reader got the room left; it checks the open file's size before reading


def test_two_artifacts_with_the_same_content_are_sent_once(proj, run, new_ticket, conn):  # noqa: F811
    tid = new_ticket("Twins")
    artifact(proj, tid, "first.md", b"same")
    artifact(proj, tid, "second.md", b"same")
    assert run("ask", tid, "See artifacts/first.md and artifacts/second.md")[0] == 0
    assert len(phone_view.view_for(proj, tid)["attachments"]) == 1


@pytest.mark.parametrize(
    "name,data,sent,said",
    [
        # a real png that hides a key in a text chunk: its raw bytes are still scanned
        (
            "shot.png",
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0ctEXtpassword=hunter2hunter2\xff\xfe",
            False,
            "password or key",
        ),
        # png bytes under a .txt name: not an image, and not text either -> not sent
        ("notes.txt", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xfe\x00", False, "can't be checked"),
        # UTF-32 with a secret, read as UTF-32 (not as UTF-16)
        ("u32.txt", "token = sk-test-ABCDEFGHIJKLMNOPQRSTUV\n".encode("utf-32"), False, "password or key"),
        ("u32ok.txt", "plain words\n".encode("utf-32"), True, None),
        # text that decodes with NULs in it fails closed
        ("nul.txt", "a\x00b".encode("utf-16"), False, "can't be checked"),
    ],
)
def test_images_are_still_scanned_and_utf32_is_read(proj, run, new_ticket, conn, name, data, sent, said):  # noqa: F811
    tid = new_ticket("More files")
    artifact(proj, tid, name, data)
    assert run("ask", tid, f"See artifacts/{name}")[0] == 0
    view = phone_view.view_for(proj, tid)
    assert bool(view["attachments"]) is sent
    lines = [
        h["text"] for h in tickets.load(proj, tid)["history"] if "was not sent to the phone" in h["text"]
    ]
    assert len(lines) == (0 if said is None else 1) and all(said in ln for ln in lines)


@pytest.mark.parametrize(
    "name,data",
    [
        (
            "plain.pdf",
            b"%PDF-1.4\n1 0 obj\n<< /Length 20 >>\nstream\nBT (hello) Tj ET\nendstream\nendobj\n%%EOF\n",
        ),
        ("hex.pdf", b"%PDF-1.4\n<< /Filter /ASCIIHexDecode >>\nstream\n48656c6c6f>\nendstream\n%%EOF\n"),
        ("doc.docx", b"PK\x03\x04plain-ascii-looking-zip-header"),
        ("old.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
    ],
)
def test_pdf_zip_and_ole_files_are_never_sent_even_when_ascii(proj, run, new_ticket, conn, name, data):  # noqa: F811
    tid = new_ticket("Packed")
    artifact(proj, tid, name, data)
    assert run("ask", tid, f"See artifacts/{name}")[0] == 0
    assert phone_view.view_for(proj, tid)["attachments"] == []
    lines = [
        h["text"] for h in tickets.load(proj, tid)["history"] if "was not sent to the phone" in h["text"]
    ]
    assert len(lines) == 1 and "can't be checked" in lines[0]
