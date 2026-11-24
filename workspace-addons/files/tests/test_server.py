import json
import threading
import urllib.error
import urllib.request

import pytest

from orch_files import preview, server, state


@pytest.fixture
def srv(built):
    s = server.make_server(built, 0, background=False)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield s
    s.shutdown()
    s.server_close()


def get(s, path, headers=None):
    port = s.server_address[1]
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"Host": f"127.0.0.1:{port}", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def post(s, body, headers=None):
    port = s.server_address[1]
    data = json.dumps(body).encode()
    h = {
        "Content-Type": "application/json",
        "Origin": f"http://127.0.0.1:{port}",
        "Sec-Fetch-Site": "same-origin",
        **(headers or {}),
    }
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/act", data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_page_and_kit(srv):
    code, _h, body = get(srv, "/", {"X-Forwarded-Prefix": "/addon/files"})
    assert code == 200 and b'data-prefix="/addon/files"' in body and b"/addon/files/web/files.js" in body
    code, _, body = get(srv, "/", {"X-Forwarded-Prefix": "/evil/../x"})
    assert b'data-prefix=""' in body
    assert get(srv, "/web/files.js")[0] == 200
    assert get(srv, "/kit/results.js")[0] == 200
    assert get(srv, "/kit/../server.py")[0] == 404


def test_reads(srv):
    st = json.loads(get(srv, "/api/status")[2])
    assert st["ready"] and st["total"] >= 10 and st["workspace"] == "Demo"
    tree = json.loads(get(srv, "/api/tree")[2])
    assert any(f["path"] == "Finance" for f in tree["folders"])
    fin = json.loads(get(srv, "/api/folder?p=Finance")[2])
    assert {f["name"] for f in fin["files"]} == {"summary.md", "budget-2027.xlsx"}
    groups = json.loads(get(srv, "/api/tickets")[2])["groups"]
    assert [g["id"] for g in groups] == ["working", "review", "earlier"]
    res = json.loads(get(srv, "/api/search?q=m%C3%BCller")[2])
    assert res["items"][0]["path"] == "Finance/summary.md"


def test_previews_per_kind(srv):
    def pv(p):
        return json.loads(get(srv, "/api/preview?p=" + urllib.request.quote(p, safe=""))[2])

    md = pv("Finance/summary.md")
    assert md["type"] == "md" and "Müller" in md["text"] and md["download"].endswith("dl=1")
    sheet = pv("Finance/budget-2027.xlsx")
    assert (
        sheet["type"] == "table" and sheet["rows"][1] == ["Rent", "54,000"] and sheet["sheets"] == ["Prices"]
    )
    word = pv("Sales/offer.docx")
    assert word["type"] == "md" and "Hotel Seeblick" in word["text"]
    assert word["name"] == "Offer for Hotel Seeblick"  # a Word file's first line is its title
    pic = pv("Marketing/photo.png")
    assert pic["type"] == "picture" and pic["src"].startswith("api/file?p=")
    page = pv("Sales/page.html")
    assert page["type"] == "page" and page["src"]
    env = pv("prod.env")
    assert env["private"] and "text" not in env and env["download"] is None
    assert get(srv, "/api/preview?p=nope.md")[0] == 404


def test_preview_cache_and_cap(built):
    first = preview.build(built, "Finance/budget-2027.xlsx")
    assert list(preview.thumbs_dir(built).glob("*.json"))
    assert preview.build(built, "Finance/budget-2027.xlsx") == first
    assert preview.trim(built, cap=0) >= 1
    assert not list(preview.thumbs_dir(built).glob("*.json"))


def test_files_are_served_sandboxed_and_private_ones_never(srv):
    code, h, _ = get(srv, "/api/file?p=Sales%2Fpage.html")
    assert code == 200 and h["Content-Security-Policy"].startswith("sandbox")
    assert h["X-Content-Type-Options"] == "nosniff"
    code, h, _body = get(srv, "/api/file?p=Finance%2Fsummary.md&dl=1")
    assert (
        code == 200
        and "attachment" in h["Content-Disposition"]
        and h["Content-Type"] == "application/octet-stream"
    )
    assert get(srv, "/api/file?p=prod.env")[0] == 404
    assert get(srv, "/api/file?p=node_modules%2Fpkg%2Findex.js")[0] == 404  # not in the index
    assert get(srv, "/api/file?p=..%2F..%2Fetc%2Fpasswd")[0] == 404


def test_fence_refuses_other_sites(srv):
    port = srv.server_address[1]
    assert get(srv, "/api/status", {"Host": "evil.example"})[0] == 403
    assert get(srv, "/api/status", {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert (
        post(srv, {"op": "star", "args": {"path": "notes.md"}}, {"Origin": "http://evil.example"})[0] == 403
    )
    assert post(srv, {"op": "star", "args": {"path": "notes.md"}}, {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert (
        post(srv, {"op": "star", "args": {"path": "notes.md"}}, {"Origin": f"http://127.0.0.1:{port}"})[0]
        == 200
    )


def test_star_and_unstar(srv, built):
    assert post(srv, {"op": "star", "args": {"path": "notes.md"}}) == (200, {"result": {"stars": 1}})
    starred = json.loads(get(srv, "/api/starred")[2])["files"]
    assert [f["path"] for f in starred] == ["notes.md"]
    assert post(srv, {"op": "unstar", "args": {"path": "notes.md"}}) == (200, {"result": {"stars": 0}})
    assert post(srv, {"op": "star", "args": {"path": "missing.md"}})[0] == 404
    assert post(srv, {"op": "delete", "args": {"path": "notes.md"}})[0] == 400
    assert post(srv, {"op": "star", "args": {"path": "notes.md"}, "x": 1})[0] == 400


def test_show_ignored_switch(srv, built):
    from orch_files import index

    st = json.loads(get(srv, "/api/status")[2])
    assert st["show_ignored"] is False and st["ignored_shown"] is False
    assert post(srv, {"op": "show_ignored", "args": {"on": "yes"}})[0] == 400
    assert post(srv, {"op": "show_ignored", "args": {"on": True}}) == (
        200,
        {"result": {"show_ignored": True}},
    )
    assert state.load(built)["show_ignored"] is True
    st = json.loads(get(srv, "/api/status")[2])
    assert st["show_ignored"] is True and st["ignored_shown"] is False  # not read again yet
    index.refresh(built)
    st = json.loads(get(srv, "/api/status")[2])
    assert st["ignored_shown"] is True
    assert index.one(built, "debug.log") is not None  # a file the .gitignore names
    assert index.one(built, "node_modules/pkg/index.js") is None  # program folders stay out
    post(srv, {"op": "star", "args": {"path": "notes.md"}})
    assert state.load(built)["show_ignored"] is True  # a star keeps the switch
    assert post(srv, {"op": "show_ignored", "args": {"on": False}})[0] == 200
    index.refresh(built)
    assert index.one(built, "debug.log") is None


def test_new_for_you_counts_from_the_last_visit(srv, built):
    state.page_opened(built, now=1_000)
    state.page_opened(built, now=1_790_000_050)  # a later visit: news since 1000
    st = json.loads(get(srv, "/api/status")[2])
    assert st["new"] >= 10
    state.page_opened(built, now=1_790_000_060)  # the same visit: unchanged
    assert state.load(built)["prev_seen"] == 1_000


def test_other_methods_refused(srv):
    port = srv.server_address[1]
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status", method="DELETE")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code in (403, 405)


def test_a_text_the_secret_check_flags_is_never_shown(srv, built, monkeypatch):
    from conftest import write

    from orch_files import index

    write(built, "Finance/notes-for-later.txt", "aws AKIAIOSFODNN7EXAMPLE\n")
    with monkeypatch.context() as m:
        m.setattr(index, "_read_texts", lambda *a, **k: None)
        index.refresh(built)  # listed by name, text not read yet
    pv = json.loads(get(srv, "/api/preview?p=Finance%2Fnotes-for-later.txt")[2])  # not read by the index yet
    assert pv.get("private") and "text" not in pv
    index.refresh(built)
    assert get(srv, "/api/file?p=Finance%2Fnotes-for-later.txt")[0] == 404
    row = index.one(built, "Finance/notes-for-later.txt")
    assert row["private"]


def test_a_file_over_the_limit_offers_no_download(srv, built):
    from orch_files import index

    with open(built / "Marketing" / "tour.mp4", "wb") as f:
        f.truncate(preview.SERVE_LIMIT + 1)
    index.refresh(built)
    pv = json.loads(get(srv, "/api/preview?p=Marketing%2Ftour.mp4")[2])
    assert pv["too_big"] and pv["download"] is None and "src" not in pv
    assert get(srv, "/api/file?p=Marketing%2Ftour.mp4")[0] == 413


def test_office_files_with_a_secret_are_neither_shown_nor_served(srv, built, monkeypatch):
    from conftest import docx, write, xlsx

    from orch_files import index

    write(built, "Sales/keys.docx", docx(["Access", "AKIAIOSFODNN7EXAMPLE"]))
    write(built, "Sales/keys.xlsx", xlsx([["key"], ["AKIAIOSFODNN7EXAMPLE"]]))
    with monkeypatch.context() as m:
        m.setattr(index, "_read_texts", lambda *a, **k: None)
        index.refresh(built)  # listed, text not read yet: the request-time check must hold on its own
    for p in ("Sales%2Fkeys.docx", "Sales%2Fkeys.xlsx"):
        pv = json.loads(get(srv, "/api/preview?p=" + p)[2])
        assert pv.get("private") and pv["download"] is None and "rows" not in pv and "text" not in pv
        assert get(srv, "/api/file?p=" + p)[0] == 404


def _zip_with(extra: dict, base: bytes) -> bytes:
    import io
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base)) as src, zipfile.ZipFile(out, "w") as dst:
        for i in src.infolist():
            dst.writestr(i.filename, src.read(i.filename))
        for name, body in extra.items():
            dst.writestr(name, body)
    return out.getvalue()


def _pdf(content: bytes) -> bytes:
    import zlib

    z = zlib.compress(content)
    return (
        b"%PDF-1.4\n1 0 obj\n<< /Length " + str(len(z)).encode() + b" /Filter /FlateDecode >>\nstream\n"
        + z
        + b"\nendstream\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
    )


def test_every_part_of_office_files_and_pdfs_is_checked(srv, built, monkeypatch):
    from conftest import docx, write, xlsx

    from orch_files import index

    key = "AKIAIOSFODNN7EXAMPLE"
    plain, book = docx(["Hello"]), xlsx([["a"], ["b"]])
    cases = {
        "hdr.docx": _zip_with({"word/header1.xml": f"<w:hdr xmlns:w='x'><w:p><w:t>{key}</w:t></w:p></w:hdr>"}, plain),
        "split.docx": _zip_with({"word/footer1.xml": "<f><t>AKIAIOSF</t><t>ODNN7EXAMPLE</t></f>"}, plain),
        "cmt.docx": _zip_with({"word/comments.xml": f"<c><t>{key}</t></c>"}, plain),
        "sheet2.xlsx": _zip_with({"xl/worksheets/sheet2.xml": f"<worksheet><c><v>{key}</v></c></worksheet>"}, book),
        "shared.xlsx": _zip_with({"xl/sharedStrings.xml": f"<sst><si><t>{key}</t></si></sst>"}, book),
        "doc.pdf": _pdf(f"BT ({key}) Tj ET".encode()),
        "kern.pdf": _pdf(b"BT [(AKIAIOSF)-20(ODNN7EXAMPLE)] TJ ET"),
        "broken.pdf": b"%PDF-1.4\n1 0 obj\n<< /Filter /FlateDecode >>\nstream\nnot zlib\nendstream\n",
        "cut.docx": plain[:40],
    }
    for name, data in cases.items():
        write(built, "Sales/" + name, data)
    with monkeypatch.context() as m:
        m.setattr(index, "_read_texts", lambda *a, **k: None)
        index.refresh(built)
    for name in cases:
        p = "Sales%2F" + name
        assert get(srv, "/api/file?p=" + p)[0] == 404, name
    assert b"could not be checked" in get(srv, "/api/file?p=Sales%2Fbroken.pdf")[2]
    index.refresh(built)
    assert all(index.one(built, "Sales/" + n)["private"] for n in cases)


def test_clean_office_files_and_pdfs_pass(srv, built):
    from conftest import docx, write, xlsx

    from orch_files import index

    write(built, "Sales/ok.docx", _zip_with({"word/header1.xml": "<h><t>Seeblick</t></h>"}, docx(["Hello"])))
    write(built, "Sales/ok.xlsx", xlsx([["a"], ["b"]]))
    write(built, "Sales/ok.pdf", _pdf(b"BT (Breakfast for 60 guests) Tj ET"))
    index.refresh(built)
    for n in ("ok.docx", "ok.xlsx", "ok.pdf"):
        assert get(srv, "/api/file?p=Sales%2F" + n)[0] == 200, n
