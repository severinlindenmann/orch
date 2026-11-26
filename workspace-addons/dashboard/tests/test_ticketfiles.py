"""The Files tab's reader (ticketfiles): names with spaces and umlauts, a workspace folder with them, size
limits, web pages, and the facts it reads from PDFs, archives and workbooks."""

import io
import unicodedata
import zipfile
from urllib.parse import unquote

import pytest

from orch_dashboard import ticketfiles as tf

TID = "t_abc12345"


@pytest.fixture
def art(tmp_path):
    """A workspace in a folder with a space and an umlaut (a OneDrive-like `C:\\Users\\Jürg\\Mein Büro`)."""
    root = tmp_path / "Mein Büro"
    d = root / ".orch" / "tickets" / TID / "artifacts"
    d.mkdir(parents=True)
    return root, d


def _xlsx(sheet_xml: bytes, strings: bytes | None = None) -> bytes:
    buf = io.BytesIO()
    ns = b'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", b"<workbook " + ns + b'><sheets><sheet name="Q1"/></sheets></workbook>')
        if strings is not None:
            z.writestr("xl/sharedStrings.xml", b"<sst " + ns + b">" + strings + b"</sst>")
        z.writestr(
            "xl/worksheets/sheet1.xml",
            b"<worksheet " + ns + b"><sheetData>" + sheet_xml + b"</sheetData></worksheet>",
        )
    return buf.getvalue()


def test_names_with_spaces_and_umlauts_are_read_in_a_folder_with_them(art):
    root, d = art
    (d / "Bericht März 2026.md").write_text("# Grüße", encoding="utf-8")
    (d / "Ordner mit Leerzeichen").mkdir()
    (d / "Ordner mit Leerzeichen" / "Übersicht.csv").write_text("a,b\n")
    assert tf.read_file(root, TID, "artifacts", "Bericht März 2026.md")[:3] == (
        200,
        "# Grüße".encode(),
        "text/plain; charset=utf-8",
    )
    assert tf.read_file(root, TID, "artifacts", "Ordner mit Leerzeichen/Übersicht.csv")[0] == 200


def test_a_download_keeps_its_real_name_with_umlauts_and_spaces(art):
    """The browser saves under the Content-Disposition name (it wins over the page's `download` attribute):
    "Bericht März 2026.pdf" must not arrive as "Bericht_M_rz_2026.pdf"."""
    root, d = art
    (d / "Bericht März 2026.pdf").write_bytes(b"%PDF-1.4")
    code, body, ctype, extra = tf.read_file(root, TID, "artifacts", "Bericht März 2026.pdf", download=True)
    assert (code, body, ctype) == (200, b"%PDF-1.4", "application/octet-stream")
    cd = extra["Content-Disposition"]
    cd.encode("latin-1")  # a header line: only plain characters on the wire
    assert cd.startswith('attachment; filename="Bericht M_rz 2026.pdf"; ')
    assert unquote(cd.split("filename*=UTF-8''", 1)[1]) == "Bericht März 2026.pdf"


@pytest.mark.parametrize(
    "name, real",
    [
        (unicodedata.normalize("NFD", "Grüße.txt"), "Grüße.txt"),  # macOS writes decomposed umlauts
        ('a"b\\c:d|e?.txt', "a_b_c_d_e_.txt"),  # what Windows refuses in a name, and a broken quote
        ("bad\r\nSet-Cookie: x.txt", "bad__Set-Cookie_ x.txt"),  # never a second header line
        ("...", "file"),
    ],
)
def test_download_names_are_safe_for_every_file_system(name, real):
    cd = tf.download_disposition(name)
    assert "\r" not in cd and "\n" not in cd
    assert unquote(cd.split("filename*=UTF-8''", 1)[1]) == real
    plain = cd.split('filename="', 1)[1].split('"', 1)[0]
    assert plain and all(c.isascii() and c not in '"\\' for c in plain)


def test_too_large_files_get_a_plain_answer_never_a_crash(art, monkeypatch):
    root, d = art
    (d / "notes.txt").write_bytes(b"x" * 11)
    (d / "page.html").write_bytes(b"<p>hi</p>")
    (d / "doc.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(tf, "MAX_BYTES", 10)
    monkeypatch.setattr(tf, "MAX_PHONE", 3)
    assert tf.read_file(root, TID, "artifacts", "notes.txt")[0] == 413
    assert tf.read_page(root, TID, "artifacts", "page.html")[0] == 413
    assert tf.info(root, TID, "artifacts", "doc.pdf") == (413, {"error": "too large"})


def test_missing_files_and_unknown_kinds_are_a_plain_404(art):
    root, _ = art
    assert tf.read_page(root, TID, "artifacts", "gone.html")[0] == 404
    assert tf.read_page(root, TID, "secrets", "x.html")[0] == 404
    assert tf.read_page(root, TID, "artifacts", "x.exe")[0] == 404
    assert tf.info(root, TID, "artifacts", "gone.pdf") == (404, {})
    assert tf.info(root, TID, "artifacts", "notes.txt") == (404, {})


def test_a_page_gets_the_escape_line_before_its_end_or_at_the_end(art):
    root, d = art
    (d / "with end.html").write_bytes(b"<html><body><p>x</p></BODY></html>")
    (d / "no end.htm").write_bytes(b"<p>x</p>")
    (d / "style.css").write_bytes(b"p{}")
    code, body, ctype, extra = tf.read_page(root, TID, "artifacts", "with end.html")
    assert (code, ctype) == (200, "text/html; charset=utf-8")
    assert body == b"<html><body><p>x</p>" + tf.PAGE_ESC + b"</BODY></html>"
    assert extra == {"Cross-Origin-Resource-Policy": "same-origin"}
    assert tf.read_page(root, TID, "artifacts", "no end.htm")[1] == b"<p>x</p>" + tf.PAGE_ESC
    code, body, ctype, extra = tf.read_page(root, TID, "artifacts", "style.css")
    assert (body, extra) == (b"p{}", {"Cross-Origin-Resource-Policy": "cross-origin"})


def test_pdf_pages_and_archive_listing(art):
    root, d = art
    (d / "Vertrag Müller.pdf").write_bytes(b"/Type /Pages /Type /Page x /Type/Page /Type /PageLabel")
    assert tf.info(root, TID, "artifacts", "Vertrag Müller.pdf") == (200, {"pages": 2})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Fotos/", b"")
        z.writestr("Fotos/Bild 1.jpg", b"123")
    (d / "Fotos März.zip").write_bytes(buf.getvalue())
    assert tf.info(root, TID, "artifacts", "Fotos März.zip") == (
        200,
        {"entries": [{"name": "Fotos/Bild 1.jpg", "size": 3}], "count": 1},
    )


@pytest.mark.parametrize("data", [b"not a zip", _xlsx(b"<row><c r='A1'><v>1</v></c>")])
def test_a_broken_archive_or_workbook_is_unreadable_not_a_crash(art, data):
    root, d = art
    (d / "kaputt.xlsx").write_bytes(data)
    assert tf.info(root, TID, "artifacts", "kaputt.xlsx") == (422, {"error": "unreadable"})


def test_a_workbook_with_declarations_is_refused(art):
    root, d = art
    bomb = b'<!DOCTYPE x [<!ENTITY a "aaaa">]><row><c r="A1"><v>&a;</v></c></row>'
    (d / "bomb.xlsx").write_bytes(_xlsx(bomb))
    assert tf.info(root, TID, "artifacts", "bomb.xlsx") == (422, {"error": "unreadable"})


def test_a_workbook_preview_holds_the_first_rows_and_counts_the_rest(art, monkeypatch):
    root, d = art
    monkeypatch.setattr(tf, "PREVIEW_ROWS", 3)
    rows = b"".join(
        b'<row><c r="A%d" t="s"><v>0</v></c><c r="C%d"><v>%d</v></c></row>' % (i, i, i) for i in range(1, 11)
    )
    (d / "Umsätze.xlsx").write_bytes(_xlsx(rows, "<si><t>Grüße</t></si>".encode()))
    code, out = tf.info(root, TID, "artifacts", "Umsätze.xlsx")
    assert code == 200
    assert out["sheets"] == ["Q1"] and out["columns"] == ["Grüße", "", "1"]
    assert len(out["rows"]) == 3 and out["rowCount"] == 9 and out["colCount"] == 3


def test_a_crafted_far_column_never_grows_the_preview(art):
    root, d = art
    (d / "weit.xlsx").write_bytes(_xlsx(b'<row><c r="A1"><v>a</v></c><c r="ZZZZZZZ1"><v>b</v></c></row>'))
    code, out = tf.info(root, TID, "artifacts", "weit.xlsx")
    assert code == 200 and out["columns"] == ["a"] and out["colCount"] == tf.PREVIEW_COLS


def test_the_listing_is_empty_and_unavailable_without_orch(art, monkeypatch):
    root, _ = art
    monkeypatch.setattr(tf, "run_orch", lambda *a, **k: None)
    assert tf.listing(root, None, TID) == {"available": False, "files": []}


def test_the_listing_drops_rows_it_cannot_trust(art, monkeypatch):
    root, _ = art
    rows = [
        {"name": "Bericht März.pdf", "size": 3, "mtime": "2026-11-06T16:05:00Z"},
        {"name": "ohne Zeit.txt", "size": 1, "mtime": 5},
        {"name": "", "size": 1},
        {"name": "a\x00b", "size": 1},
        {"name": "x" * 241, "size": 1},
        {"name": "flag.txt", "size": True},
        "not a row",
    ]
    monkeypatch.setattr(tf, "run_orch", lambda *a, **k: rows)
    assert tf.listing(root, None, TID) == {
        "available": True,
        "files": [
            {"name": "Bericht März.pdf", "size": 3, "mtime": "2026-11-06T16:05:00Z"},
            {"name": "ohne Zeit.txt", "size": 1, "mtime": ""},
        ],
    }
