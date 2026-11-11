"""Artifacts named by a ticket reach the phone through the safe file reader."""

import hashlib

import pytest
from test_ticket_view import conn  # noqa: F401 (fixture)

from orch import keystore, phone_view, tickets


def artifact(proj, tid, name, data=b"artifact bytes"):
    path = proj / ".orch/tickets" / tid / "artifacts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _chunk(kind: bytes, body: bytes) -> bytes:
    import zlib

    return len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")


def png(*chunks: bytes, tail: bytes = b"") -> bytes:
    """A well-formed PNG: signature, IHDR, the given chunks, IEND, then `tail` (bytes after the end)."""
    ihdr = _chunk(b"IHDR", (1).to_bytes(4, "big") * 2 + bytes([8, 2, 0, 0, 0]))
    return b"\x89PNG\r\n\x1a\n" + ihdr + b"".join(chunks) + _chunk(b"IEND", b"") + tail


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


def test_description_only_sends_ticket_artifacts(proj, new_ticket, conn):  # noqa: F811
    tid = new_ticket("Plan")
    artifact(proj, tid, "plan.md")
    (proj / "notes").mkdir()
    (proj / "notes/x.md").write_bytes(b"workspace file")
    ticket = tickets.load(proj, tid)
    ticket["description"] = "see artifacts/plan.md and notes/x.md"
    tickets.save(proj, ticket)
    assert [a["name"] for a in phone_view.view_for(proj, tid)["attachments"]] == ["plan.md"]
    assert list(conn.blobs.values()) == [b"artifact bytes"]


def test_description_traversal_does_not_name_artifact(proj, new_ticket, conn):  # noqa: F811
    tid = new_ticket("Traversal")
    artifact(proj, tid, "secret.md")
    ticket = tickets.load(proj, tid)
    ticket["description"] = "See ../secret.md"
    tickets.save(proj, ticket)
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
        ("report.pdf", "See `artifacts/report.pdf`.", True),
        ("report.pdf", "See `report.pdf`, then continue.", True),
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


@pytest.mark.parametrize("source", ["summary", "description"])
def test_artifact_matching_evidence_is_not_added(proj, new_ticket, conn, source):  # noqa: F811
    tid = new_ticket("Evidence")
    data = b"same evidence and artifact"
    artifact(proj, tid, "report.txt", data)
    evidence = proj / ".orch/tickets" / tid / "evidence" / "proof.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(data)
    ticket = tickets.load(proj, tid)
    ticket[source] = "report.txt"
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
        ("photo.png", png(), True, None),
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
            png(_chunk(b"tEXt", b"Comment\x00password=hunter2hunter2")),
            False,
            "can't be checked",  # tEXt is not on the PNG allowlist
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


@pytest.mark.parametrize(
    "name,data",
    [
        ("z.png", png(_chunk(b"zTXt", b"Comment\x00\x00x\x9c+.N.J-\x01\x00\x07\xfb\x02\x9c"))),
        ("i.png", png(_chunk(b"iTXt", b"Comment\x00\x01\x00\x00\x00x\x9c+.N.J-\x01\x00"))),
        ("icc.png", png(_chunk(b"iCCP", b"icc\x00\x00x\x9c\x03\x00\x00\x00\x00\x01"))),
        ("tail.png", png(tail=b"password=hunter2 hidden after the end")),
        ("broken.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xfe\x00"),  # no IEND
        ("tail.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\xff\xd9" + b"more after EOI"),
        ("tail.gif", b"GIF89a\x01\x00\x01\x00\x00\x00\x00;" + b"more after trailer"),
        ("size.webp", b"RIFF" + (100).to_bytes(4, "little") + b"WEBPVP8 " + b"\x00" * 8),
    ],
)
def test_images_with_hidden_or_trailing_data_fail_closed(proj, run, new_ticket, conn, name, data):  # noqa: F811
    tid = new_ticket("Hidden")
    artifact(proj, tid, name, data)
    assert run("ask", tid, f"See artifacts/{name}")[0] == 0
    assert phone_view.view_for(proj, tid)["attachments"] == []
    lines = [
        h["text"] for h in tickets.load(proj, tid)["history"] if "was not sent to the phone" in h["text"]
    ]
    assert len(lines) == 1 and "can't be checked" in lines[0]


def test_a_well_formed_png_is_sent(proj, run, new_ticket, conn):  # noqa: F811
    tid = new_ticket("Images")
    artifact(proj, tid, "ok.png", png())
    assert run("ask", tid, "See artifacts/ok.png")[0] == 0
    assert len(phone_view.view_for(proj, tid)["attachments"]) == 1


@pytest.mark.parametrize(
    "name,data",
    [
        ("ok.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\xff\xd9"),
        ("ok.gif", b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"),
        ("ok.webp", b"RIFF" + (12).to_bytes(4, "little") + b"WEBPVP8 " + b"\x00" * 4),
    ],
)
def test_named_jpeg_gif_and_webp_are_not_sent_yet(proj, run, new_ticket, conn, name, data):  # noqa: F811
    """Only a PNG can be walked and checked today; other image types fail closed when only named."""
    tid = new_ticket("Images")
    artifact(proj, tid, name, data)
    assert run("ask", tid, f"See artifacts/{name}")[0] == 0
    assert phone_view.view_for(proj, tid)["attachments"] == []
    lines = [
        h["text"] for h in tickets.load(proj, tid)["history"] if "was not sent to the phone" in h["text"]
    ]
    assert len(lines) == 1 and "can't be checked" in lines[0]


def jpeg(*segments: bytes, tail: bytes = b"") -> bytes:
    """A plain JPEG: SOI, the given (marker, payload) segments, a tiny SOS with entropy data, EOI."""
    out = b"\xff\xd8"
    for marker, payload in segments:
        out += b"\xff" + bytes([marker]) + (len(payload) + 2).to_bytes(2, "big") + payload
    return out + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x12\x34\xff\xd9" + tail


APP0 = (0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
TOKEN = "token = sk-test-ABCDEFGHIJKLMNOPQRSTUV"


def test_a_jpeg_marked_as_evidence_still_goes_to_the_phone(proj, run, new_ticket, conn):  # noqa: F811
    """Evidence the agent marks for the phone keeps its old behaviour; only named artifacts are strict."""
    data = jpeg(APP0, (0xE1, b"Exif\x00\x00camera"))
    tid = new_ticket("Photo proof")
    run("check", "add", tid, "Take the photo")
    src = proj / "photo.jpg"
    src.write_bytes(data)
    code, _, err = run("check", "done", tid, "c1", "--file", str(src), "--role", "result")
    assert code == 0, err
    atts = phone_view.view_for(proj, tid)["attachments"]
    assert len(atts) == 1 and atts[0]["kind"] == "image"


def test_the_png_chunk_walk_is_bounded(monkeypatch):
    monkeypatch.setattr(phone_view, "PNG_MAX_CHUNKS", 3)
    many = png(*[_chunk(b"tEXt", b"a\x00b")] * 5)
    assert phone_view._image_clean(many) is False
    assert phone_view._image_clean(png()) is True


@pytest.mark.parametrize(
    "name,data,sent",
    [
        ("ok.png", png(_chunk(b"gAMA", b"\x00\x00\xb1\x8f"), _chunk(b"pHYs", b"\x00" * 9)), True),
        ("text.png", png(_chunk(b"tEXt", b"Comment\x00hello")), False),
        ("exif.png", png(_chunk(b"eXIf", b"MM\x00*")), False),
        ("odd.png", png(_chunk(b"prVt", b"anything")), False),
    ],
)
def test_png_allows_only_known_harmless_chunks(proj, run, new_ticket, conn, name, data, sent):  # noqa: F811
    tid = new_ticket("Chunks")
    artifact(proj, tid, name, data)
    assert run("ask", tid, f"See artifacts/{name}")[0] == 0
    assert bool(phone_view.view_for(proj, tid)["attachments"]) is sent


@pytest.mark.parametrize(
    "name,data",
    [
        ("notes.md", b"# Notes\nsee the attached %PDF-1.4 dump\n"),
        ("pic.png", png(_chunk(b"IDAT", b"PK\x03\x04 inside the image data"))),
        ("pic.gif", b"GIF89a\x01\x00\x01\x00\xd0\xcf\x11\xe0\x00;"),
    ],
)
def test_packed_magic_anywhere_fails_closed(proj, run, new_ticket, conn, name, data):  # noqa: F811
    tid = new_ticket("Packed inside")
    artifact(proj, tid, name, data)
    assert run("ask", tid, f"See artifacts/{name}")[0] == 0
    assert phone_view.view_for(proj, tid)["attachments"] == []


def test_a_page_and_its_picture_are_one_entry(proj, run, new_ticket, conn):  # noqa: F811
    tid = new_ticket("Report")
    artifact(proj, tid, "report.png", png())
    artifact(proj, tid, "report.html", b"<h1>Report</h1>")
    artifact(proj, tid, "other.png", png(_chunk(b"tRNS", b"\x00\x00")))
    assert run("ask", tid, "See artifacts/report.png, artifacts/report.html and artifacts/other.png")[0] == 0
    atts = phone_view.view_for(proj, tid)["attachments"]
    names = [a["name"] for a in atts]
    page, pic = atts[names.index("report.html")], atts[names.index("report.png")]
    assert page["preview"] == pic["id"]
    assert names.index("report.png") == names.index("report.html") + 1  # the picture follows its page
    assert "preview" not in pic and "preview" not in atts[names.index("other.png")]


def test_a_picture_that_was_not_sent_is_never_a_preview(proj, run, new_ticket, conn):  # noqa: F811
    tid = new_ticket("Report")
    artifact(proj, tid, "report.png", png(_chunk(b"tEXt", b"key\x00hidden")))  # fails the PNG check
    artifact(proj, tid, "report.html", b"<h1>Report</h1>")
    assert run("ask", tid, "See artifacts/report.png and artifacts/report.html")[0] == 0
    atts = phone_view.view_for(proj, tid)["attachments"]
    assert [a["name"] for a in atts] == ["report.html"] and "preview" not in atts[0]


def _att(kind, name, at, aid):
    blob = "b_0123456789abcdef"
    return {
        "kind": kind, "title": name, "name": name, "blob_id": blob, "size": 1, "at": at, "id": aid,
        "rev": "r",
    }  # fmt: skip


def test_pairing_with_a_newer_picture_has_no_duplicates():
    page = _att("file", "r.html", "2026-11-06T09:00:00Z", "a_000000000001")
    pic = _att("image", "r.png", "2026-11-06T09:05:00Z", "a_000000000002")
    out = phone_view.pair_previews([pic, page])  # newest first: the picture is before the page
    assert [a["id"] for a in out] == ["a_000000000001", "a_000000000002"]
    assert out[0]["preview"] == "a_000000000002"


def test_two_pages_share_one_picture_only_once():
    p1 = _att("file", "r.html", "2026-11-06T09:00:00Z", "a_000000000001")
    p2 = _att("file", "r.htm", "2026-11-06T08:00:00Z", "a_000000000003")
    pic = _att("image", "r.png", "2026-11-06T09:05:00Z", "a_000000000002")
    out = phone_view.pair_previews([pic, p1, p2])
    ids = [a["id"] for a in out]
    assert sorted(ids) == ["a_000000000001", "a_000000000002", "a_000000000003"] and len(set(ids)) == 3
    assert sum("preview" in a for a in out) == 1


def test_preview_never_points_outside_the_list(monkeypatch):
    monkeypatch.setattr(phone_view, "ATTACHMENTS", 1)
    page = _att("file", "r.html", "2026-11-06T09:05:00Z", "a_000000000001")
    pic = _att("image", "r.png", "2026-11-06T09:00:00Z", "a_000000000002")
    # the real code cuts first; mimic it: the picture is cut off, so the page has no preview
    out = phone_view.pair_previews([page, pic][: phone_view.ATTACHMENTS])
    assert out == [page] and "preview" not in page


@pytest.mark.parametrize(
    ("name", "data", "sent"),
    [
        ("notes.txt", b"api_key = sk-test-ABCDEFGHIJKLMNOPQRSTUV", False),
        ("notes.txt", b"password = ordinary", False),
        ("report.pdf", b"%PDF-1.4 hello", False),  # can't be checked: not sent
        ("shot.jpg", jpeg(APP0, (0xE1, b"Exif\x00\x00" + TOKEN.encode())), False),
        ("clean.txt", b"nothing secret here\n", True),
        ("x.jpg", b"PK\x03\x04 not a picture", False),  # an archive renamed to .jpg
        ("x.jpg", jpeg(APP0, tail=b" appended data"), False),  # data after the end
        ("x.jpg", jpeg(APP0, tail=b"PK\x03\x04zip\xff\xd9"), False),  # archive behind an extra EOI
        ("x.jpg", jpeg(APP0, (0xFE, b"a comment segment")), False),  # COM can hide anything
        ("x.jpg", jpeg(APP0, (0xE3, b"APP3 vendor blob")), False),
        ("x.jpg", jpeg(APP0, (0xE1, b"Exif\x00\x00" + TOKEN.encode("utf-16-le"))), False),
        ("x.jpg", jpeg(APP0, (0xE1, b"Exif\x00\x00x" + TOKEN.encode("utf-16-be"))), False),
        (
            "x.png",
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"PK\x03\x04",
            False,
        ),  # no PNG shortcut under photo_ok
        ("x.jpg", jpeg(APP0, (0xDB, TOKEN.encode("utf-16-le"))), False),  # small tables still hold no text
        ("x.jpg", jpeg(APP0, *[(0xC4, b"z" * 6000)] * 2), False),  # payload spread over table segments
        ("x.jpg", jpeg(APP0, tail=b"\x00\x00"), True),  # camera NUL padding is fine
    ],
)
def test_evidence_files_go_through_the_same_secret_gate(proj, run, new_ticket, conn, name, data, sent):  # noqa: F811
    """A proof file (evidence, type file) is scanned like a named artifact: a token in it is never uploaded
    and is marked once in the ticket log and in state; a clean file still goes."""
    tid = new_ticket("Proof with a secret")
    run("check", "add", tid, "Attach the proof")
    src = proj / name
    src.write_bytes(data)
    code, _, err = run("check", "done", tid, "c1", "--file", str(src), "--role", "result")
    assert code == 0, err
    for _ in range(2):
        atts = phone_view.view_for(proj, tid)["attachments"]
        assert bool(atts) is sent
    assert bool(conn.blobs) is sent
    marks = [
        h["text"] for h in tickets.load(proj, tid)["history"] if "was not sent to the phone" in h["text"]
    ]
    assert len(marks) == (0 if sent else 1) and all(name in m for m in marks)
    assert len(phone_view.load_state(proj).get("secret_skipped", [])) == (0 if sent else 1)


def test_no_upload_without_the_gate(proj, run, new_ticket, conn, monkeypatch):  # noqa: F811
    """Every attachment kind goes through _gate: with the gate closed nothing reaches the relay."""
    tid = new_ticket("Gate closed")
    artifact(proj, tid, "a.txt", b"fine text")
    run("check", "add", tid, "Attach")
    src = proj / "p.txt"
    src.write_bytes(b"fine proof")
    assert run("check", "done", tid, "c1", "--file", str(src), "--role", "result")[0] == 0
    monkeypatch.setattr(phone_view, "_gate", lambda *a, **k: False)
    ticket = tickets.load(proj, tid)
    ticket["description"] = "See artifacts/a.txt"
    assert phone_view.attachments(proj, ticket, phone_view.load_state(proj)) == []
    assert not conn.blobs


@pytest.mark.parametrize("how", ["artifact", "evidence"])
def test_a_stored_key_value_is_never_uploaded_whatever_the_label(proj, run, new_ticket, conn, how):  # noqa: F811
    """Needle check: a file that holds the exact value of a key saved in the keystore (no label, no pattern)
    is not sent and is marked, as named artifact and as proof file alike."""
    value = "Xk93-pq7Lm-aa21-zQ"
    keystore.add(proj, "db-cred", "token", value)
    tid = new_ticket("Needle")
    body = f"The new one is {value}, rotate it.\n".encode()
    if how == "artifact":
        artifact(proj, tid, "notes.txt", body)
        assert run("ask", tid, "See artifacts/notes.txt")[0] == 0
    else:
        run("check", "add", tid, "Attach")
        src = proj / "notes.txt"
        src.write_bytes(body)
        assert run("check", "done", tid, "c1", "--file", str(src), "--role", "result")[0] == 0
    assert phone_view.view_for(proj, tid)["attachments"] == []
    assert not conn.blobs
    assert [h for h in tickets.load(proj, tid)["history"] if "was not sent to the phone" in h["text"]]


def test_a_file_without_a_stored_value_still_goes(proj, run, new_ticket, conn):  # noqa: F811
    keystore.add(proj, "db-cred", "token", "Xk93-pq7Lm-aa21-zQ")
    tid = new_ticket("No needle")
    artifact(proj, tid, "notes.txt", b"nothing secret here\n")
    assert run("ask", tid, "See artifacts/notes.txt")[0] == 0
    assert len(phone_view.view_for(proj, tid)["attachments"]) == 1


def test_an_unbuildable_value_hider_fails_closed(proj, new_ticket, monkeypatch):
    tid = new_ticket("No hider")
    assert phone_view._gate(proj, tid, b"nothing secret here\n", "notes.txt", None) is True
    monkeypatch.setattr(phone_view.phone_results, "value_hider", lambda root: None)
    assert phone_view._gate(proj, tid, b"nothing secret here\n", "notes.txt", None) is False
