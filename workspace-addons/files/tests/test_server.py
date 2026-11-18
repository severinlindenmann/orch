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
        f"http://127.0.0.1:{port}{path}", headers={"Host": f"127.0.0.1:{port}", **(headers or {})}
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
    pic = pv("Marketing/photo.png")
    assert pic["type"] == "picture" and pic["src"].startswith("api/file?p=")
    page = pv("Sales/page.html")
    assert page["type"] == "page" and page["src"]
    env = pv(".env")
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
    assert get(srv, "/api/file?p=.env")[0] == 404
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
