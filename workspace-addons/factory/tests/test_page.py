"""The read-only Factory page server: API shapes, fences, file route, kit fallback, service url."""

import http.client
import json
import os
import sys
import threading
import time

import pytest
from test_flow import (
    ask_stop,
    autopilot_order,
    core,
    finish_crew,
    started,
    waiting_stop,
)

from orch_factory import pageapi, runfiles, server, service
from orch_factory.store import Store

PNG = b"\x89PNG\r\n\x1a\nfake"


def request(srv, path, method="GET", headers=None, host=None):
    port = srv.server_address[1]
    h = {"Host": host or f"127.0.0.1:{port}", **(headers or {})}
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, headers=h)
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body, r


def get(srv, path, **kw):
    status, body, r = request(srv, path, **kw)
    ctype = r.getheader("Content-Type") or ""
    return status, (json.loads(body) if ctype.startswith("application/json") else body), r


@pytest.fixture
def srv(ws):
    s = server.make_server(ws)
    server.serve_in_thread(s)
    yield s
    s.shutdown()
    s.server_close()


def put_file(ws, rel, data=PNG):
    p = Store(ws).base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


# ---- API shapes ---------------------------------------------------------------------------------------------

ORDER_KEYS = {"id", "title", "kind", "phase", "stage", "line", "budget", "eta", "due", "open", "owner_min"}


def test_home_lists_orders_in_every_phase(ws, run, srv, proposal):
    draft = run("idea", "Just an idea")["order"]
    proposed = run("idea", "Proposed one")["order"]
    run("propose", proposed, "--file", "-", data=proposal)
    order, _ = started(ws, run)
    code, home, r = get(srv, "/api/home")
    assert code == 200 and r.getheader("Cache-Control") == "no-store"
    assert set(home) == {"generated_at", "orders", "autopilot", "watcher"}
    assert home["autopilot"] is None and home["watcher"] is False
    by = {o["id"]: o for o in home["orders"]}
    assert all(ORDER_KEYS <= set(o) for o in by.values())
    assert by[draft]["phase"] == "draft" and by[draft]["open"] is None and by[draft]["line"] == []
    p = by[proposed]
    assert (
        p["phase"] == "proposed"
        and p["open"]["kind"] == "start"
        and p["open"]["options"]
        == [
            "Start",
            "Edit",
            "Not now",
        ]
    )
    assert p["title"] == "Online booking page" and p["due"] == "2026-11-20" and p["owner_min"] == 3
    assert p["eta"] == "2026-11-13T19:30:00Z" and p["budget"] == {"used": 0, "cap": 150, "warn": False}
    assert [x["state"] for x in p["line"]] == ["todo", "todo", "todo"]
    assert by[order]["phase"] == "started" and by[order]["stage"] == "build" and by[order]["open"] is None


def test_line_label_comes_from_the_proposal(run, srv, proposal):
    import json

    data = json.loads(proposal)
    data["line"][0]["label"] = "Build the booking page"
    order = run("idea", "Labelled line")["order"]
    run("propose", order, "--file", "-", data=json.dumps(data).encode())
    _, o, _ = get(srv, f"/api/order/{order}")
    assert [x.get("label") for x in o["line"]] == ["Build the booking page", None, None]


def test_order_detail_shape(ws, run, srv):
    order, q = waiting_stop(ws, run, {"title": "Button colour", "tag": "taste"})
    run("tiny", order, "--minutes", "5", "--what", "Fix a typo")
    code, o, _ = get(srv, f"/api/order/{order}")
    assert code == 200
    assert ORDER_KEYS <= set(o) and {
        "proposal",
        "drafts",
        "crew",
        "changes",
        "tiny",
        "stops",
        "activity",
    } <= set(o)
    assert o["phase"] == "started" and o["stage"] == "build"
    assert o["open"] == {
        "q": q,
        "kind": "stop",
        "text": o["open"]["text"],
        "options": ["Continue", "Send back"],
        "data": o["open"]["data"],  # the structured stop: the page titles the card from it
    }
    assert o["open"]["data"]["stage"] == "build" and "before" not in o["open"]["text"]
    assert [x["state"] for x in o["line"]] == ["waiting", "todo"]
    assert o["proposal"]["kind"] == "run" and o["tiny"] == [{"what": "Fix a typo", "minutes": 5}]
    assert [(c["title"], c["role"], c["agent"], c["status"]) for c in o["crew"]] == [
        ("Booking form", "builder", "codex", "done"),
        ("Prepare the release", "builder", "codex", "todo"),
    ]
    assert o["crew"][1]["ticket"] is None and o["crew"][0]["ticket"].startswith("t_")
    stop = o["stops"][0]
    assert (stop["n"], stop["stage"], stop["state"], stop["answer"], stop["by"]) == (
        1,
        "build",
        "open",
        None,
        None,
    )
    assert stop["data"]["items"][0]["title"] == "Button colour"
    assert o["drafts"] == [{"v": 1, "at": o["drafts"][0]["at"]}] and o["drafts"][0]["at"].endswith("Z")
    assert o["changes"] == []


def test_stop_answered_and_change_states(ws, run, srv):
    order, q = waiting_stop(ws, run)
    core(ws, "answer", order, q, "Continue", "--by", "human:anna")
    change = json.loads(
        (__import__("conftest").CONTRACTS / "examples/factory-proposal/valid-change.json").read_text()
    )
    change["lands_in"] = "ship"
    change.pop("adds_tasks", None)
    run("change", order, "--file", "-", data=json.dumps(change).encode())
    o = get(srv, f"/api/order/{order}")[1]
    assert o["stops"][0]["state"] == "answered" and o["stops"][0]["answer"] == "Continue"
    assert o["stops"][0]["by"] == "human:anna"
    assert [c["state"] for c in o["changes"]] == ["open"] and o["open"]["kind"] == "change"
    cq = core(ws, "ticket", "show", order)["questions"][-1]["id"]
    core(ws, "answer", order, cq, "Accept", "--by", "human:anna")
    o = get(srv, f"/api/order/{order}")[1]
    assert [c["state"] for c in o["changes"]] == ["accepted"]
    assert o["changes"][0]["adds_min"] == change["adds_min"]


def test_unknown_or_bad_order_is_404(ws, run, srv):
    assert get(srv, "/api/order/t_zzzzzz")[0] == 404
    assert get(srv, "/api/order/not-an-id")[0] == 404
    assert get(srv, "/api/order/t_zzzzzz/draft/1")[0] == 404


def test_draft_route(ws, run, srv):
    order = run("idea", "Idea", "--file", "-", data=b"# Hello <b>x</b>")["order"]
    code, body, _ = get(srv, f"/api/order/{order}/draft/1")
    assert code == 200 and body == {"v": 1, "text": "# Hello <b>x</b>"}
    assert get(srv, f"/api/order/{order}/draft/2")[0] == 404
    assert get(srv, f"/api/order/{order}/draft/0")[0] == 404
    assert get(srv, f"/api/order/{order}/draft/1x")[0] == 404
    put_file(ws, f"drafts/{order}/v7.md", b"a" * (pageapi.MAX_DRAFT + 10))
    body = get(srv, f"/api/order/{order}/draft/7")[1]
    assert len(body["text"]) == pageapi.MAX_DRAFT and body["truncated"] is True


def test_autopilot_route_and_home_block(ws, run, srv):
    assert get(srv, "/api/autopilot")[1] == {"grants": [], "decisions": []}
    autopilot_order(ws, run)
    order, _ = started(ws, run)
    run("next", order)
    finish_crew(ws, run, order, "booking-form")
    q = ask_stop(ws, run, order, "build", {"title": "Wording", "tag": "routine"})
    run("decide", order, q, "--answer", "Continue", "--why", "Routine wording")
    code, a, _ = get(srv, "/api/autopilot")
    assert code == 200 and len(a["grants"]) == 1
    g = a["grants"][0]
    assert set(g) == {"order", "until", "may", "limits", "live"} and g["live"] is True
    assert g["may"] == ["routine", "taste"] and g["limits"]["days"] == 3
    assert [(d["order"], d["q"], d["answer"], d["why"]) for d in a["decisions"]] == [
        (order, q, "Continue", "Routine wording")
    ]
    home = get(srv, "/api/home")[1]
    assert home["autopilot"] == {"on": True, "until": g["until"], "decided_today": 1}
    o = get(srv, f"/api/order/{order}")[1]
    assert o["stops"][0]["state"] == "decided" and o["stops"][0]["by"] == "agent:factory"
    assert any(x["text"].startswith("Decided by agent:factory") for x in o["activity"])


def test_autopilot_order_summary(ws, run, srv):
    a, _ = autopilot_order(ws, run)
    o = get(srv, f"/api/order/{a}")[1]
    assert o["kind"] == "autopilot" and o["phase"] == "started" and o["crew"] == [] and o["stops"] == []
    assert o["proposal"]["kind"] == "autopilot"


def test_agent_start_never_reports_started(ws, run, srv):
    order, _ = started(ws, run, by="agent:worker")
    o = get(srv, f"/api/order/{order}")[1]
    assert o["phase"] == "proposed" and o["stage"] is None
    assert o["open"] is None or o["open"]["kind"] == "start"
    home = get(srv, "/api/home")[1]
    assert [x["phase"] for x in home["orders"]] == ["proposed"]
    assert o["crew"] == [] and o["stops"] == []


def test_agent_autopilot_start_never_reports_started(ws, run, srv):
    a, _ = autopilot_order(ws, run, by="agent:worker")
    assert get(srv, f"/api/order/{a}")[1]["phase"] == "proposed"
    assert get(srv, "/api/autopilot")[1]["grants"] == []
    assert get(srv, "/api/home")[1]["autopilot"] is None


def test_shipped_and_parked_phases(ws, run, srv, proposal):
    order, _ = started(ws, run)
    parked = run("idea", "Parked")["order"]
    q = run("propose", parked, "--file", "-", data=proposal)["question"]
    core(ws, "answer", parked, q, "Not now", "--by", "human:anna")
    by = {o["id"]: o["phase"] for o in get(srv, "/api/home")[1]["orders"]}
    assert by == {order: "started", parked: "parked"}


def test_broken_order_does_not_hide_the_others(ws, run, srv, proposal):
    good, _ = started(ws, run)
    bad = run("idea", "Bad")["order"]
    q = run("propose", bad, "--file", "-", data=proposal)["question"]
    t = json.loads((ws / "fake-tickets" / f"{bad}.json").read_text())
    t["questions"][0]["action"]["hash"] = "0" * 64
    (ws / "fake-tickets" / f"{bad}.json").write_text(json.dumps(t))
    by = {o["id"]: o for o in get(srv, "/api/home")[1]["orders"]}
    assert by[good]["phase"] == "started" and by[bad]["phase"] == "broken" and by[bad]["problem"]
    assert q


def test_reads_do_not_write(ws, run, srv):
    order, _ = waiting_stop(ws, run)
    store = Store(ws)
    snap = lambda: {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in store.base.rglob("*") if p.is_file()}
    calls = (ws / "calls.jsonl").read_text().count('"by": "agent:factory"')
    before = snap()
    for path in ("/api/home", f"/api/order/{order}", "/api/autopilot", "/"):
        get(srv, path)
    assert snap() == before
    assert (ws / "calls.jsonl").read_text().count('"by": "agent:factory"') == calls  # no write call to orch


# ---- stale answers ------------------------------------------------------------------------------------------


def test_slow_orch_returns_last_good_answer_stale(ws, run, monkeypatch):
    started(ws, run)
    s = server.make_server(ws, budget=0.3)
    server.serve_in_thread(s)
    try:
        good = get(s, "/api/home")[1]
        assert "stale" not in good
        real = pageapi.orchcli.tickets
        monkeypatch.setattr(pageapi.orchcli, "tickets", lambda root: (time.sleep(1.2), real(root))[1])
        t0 = time.time()
        code, body, _ = get(s, "/api/home")
        assert code == 200 and body["stale"] is True and body["orders"] == good["orders"]
        assert time.time() - t0 < 1.0
    finally:
        s.shutdown()
        s.server_close()


def test_slow_orch_without_any_good_answer_is_503(ws, run, monkeypatch):
    started(ws, run)
    monkeypatch.setattr(pageapi.orchcli, "tickets", lambda root: time.sleep(1.0))
    s = server.make_server(ws, budget=0.2)
    server.serve_in_thread(s)
    try:
        code, body, _ = get(s, "/api/home")
        assert code == 503 and body["stale"] is True and body["error"]
    finally:
        s.shutdown()
        s.server_close()


# ---- fences ---------------------------------------------------------------------------------------------------


def test_bad_host_is_403(srv):
    for host in ("evil.example", "127.0.0.1", "evil.example:80", "127.0.0.1.evil.example:80", "[::1]:80"):
        assert request(srv, "/api/home", host=host)[0] == 403, host
        assert request(srv, "/", host=host)[0] in (200, 403)  # pages follow the shared rule; api never passes
    assert request(srv, "/api/home", host=f"localhost:{srv.server_address[1]}")[0] == 200


def test_cross_site_api_read_is_403(srv):
    assert request(srv, "/api/home", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert request(srv, "/api/home", headers={"Sec-Fetch-Site": "same-origin"})[0] == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def test_only_get(srv, method):
    assert request(srv, "/api/home", method=method)[0] == 405
    assert request(srv, "/", method=method)[0] == 405


def test_write_methods_with_foreign_origin_are_403(srv):
    port = srv.server_address[1]
    assert request(srv, "/api/home", method="POST", headers={"Origin": "http://evil.example"})[0] == 403
    assert request(srv, "/api/home", method="POST", headers={"Origin": f"http://127.0.0.1:{port}"})[0] == 405


def test_no_cors_headers_and_security_headers(srv):
    _, _, r = request(srv, "/api/home")
    names = {k.lower() for k, _ in r.getheaders()}
    assert not any(n.startswith("access-control-") for n in names)
    assert r.getheader("Content-Security-Policy").startswith("default-src 'self'")
    assert r.getheader("Cross-Origin-Resource-Policy") == "same-origin"
    assert r.getheader("X-Content-Type-Options") == "nosniff" and r.getheader("Cache-Control") == "no-store"


def test_fallback_fence_matches_shared_rules(monkeypatch, srv):
    monkeypatch.setitem(sys.modules, "orch_ui", None)
    monkeypatch.setitem(sys.modules, "orch_ui.origin", None)
    assert request(srv, "/api/home", host="evil.example:80")[0] == 403
    assert request(srv, "/api/home", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert request(srv, "/api/home", method="POST")[0] == 405
    assert request(srv, "/api/home")[0] == 200


def test_unknown_paths_are_404(srv):
    for path in (
        "/nope",
        "/api/",
        "/api/order",
        "/web/../index.html",
        "/web/secret.py",
        "/kit/other.css",
        "/ready",
    ):
        assert request(srv, path)[0] == 404, path


# ---- index, prefix, assets ------------------------------------------------------------------------------------


def test_index_prefix_replacement(srv):
    code, plain, r = get(srv, "/")
    assert code == 200 and r.getheader("Content-Type").startswith("text/html") and b"__P__" not in plain
    code, body, _ = get(srv, "/", headers={"X-Forwarded-Prefix": "/addon/factory"})
    assert b"/addon/factory/web/factory.js" in body and b"__P__" not in body
    for bad in ("/addon/factory/../x", "//evil.example", "/addon/Factory", 'x"><script>', "/addon/factory/"):
        body = get(srv, "/", headers={"X-Forwarded-Prefix": bad})[1]
        assert b"__P__" not in body and bad.encode() not in body, bad


def test_web_files_from_a_fixed_list(srv):
    for name, ctype in (
        ("factory.css", "text/css"),
        ("factory.js", "text/javascript"),
        ("index.html", "text/html"),
    ):
        code, body, r = get(srv, f"/web/{name}")
        assert code == 200 and body and r.getheader("Content-Type").startswith(ctype), name
    assert get(srv, "/web/__init__.py")[0] == 404 and get(srv, "/web/")[0] == 404


def test_kit_fallback_to_the_dashboard_copy(srv, monkeypatch, tmp_path):
    kit = tmp_path / "pkgs" / "orch_dashboard" / "web" / "kit"
    kit.mkdir(parents=True)
    (kit.parents[1] / "__init__.py").write_text("")
    (kit / "tokens.css").write_bytes(b":root{}")
    monkeypatch.setitem(sys.modules, "orch_ui", None)  # orch_ui gone
    monkeypatch.delitem(sys.modules, "orch_dashboard", raising=False)
    monkeypatch.syspath_prepend(str(tmp_path / "pkgs"))
    code, body, r = get(srv, "/kit/tokens.css")
    assert (code, body) == (200, b":root{}") and r.getheader("Content-Type").startswith("text/css")
    assert get(srv, "/kit/icons.js")[0] == 404  # not in the copy
    assert get(srv, "/kit/server.py")[0] == 404


def test_kit_missing_everywhere_is_404(srv, monkeypatch):
    monkeypatch.setitem(sys.modules, "orch_ui", None)
    monkeypatch.setitem(sys.modules, "orch_dashboard", None)
    assert get(srv, "/kit/tokens.css")[:2] == (404, b"not found")
    assert get(srv, "/web/factory.css")[0] == 200


def test_kit_from_orch_ui(srv, monkeypatch, tmp_path):
    static = tmp_path / "ui" / "static"
    static.mkdir(parents=True)
    (static / "components.js").write_bytes(b"1")
    fake = type(sys)("orch_ui")
    fake.__file__ = str(tmp_path / "ui" / "__init__.py")
    monkeypatch.setitem(sys.modules, "orch_ui", fake)
    monkeypatch.setitem(sys.modules, "orch_ui.origin", None)
    code, body, r = get(srv, "/kit/components.js")
    assert (code, body) == (200, b"1") and r.getheader("Content-Type").startswith("text/javascript")


# ---- image route ----------------------------------------------------------------------------------------------


def test_file_route_serves_stop_images(ws, run, srv):
    order, _ = waiting_stop(ws, run)
    put_file(ws, f"stops/{order}/before.png")
    put_file(ws, f"stops/{order}/s1/after.webp", b"RIFFxxxxWEBP")
    put_file(ws, f"stops/{order}/shot.jpg", b"\xff\xd8\xff")
    code, body, r = get(srv, f"/api/order/{order}/file/before.png")
    assert (code, body) == (200, PNG) and r.getheader("Content-Type") == "image/png"
    code, body, r = get(srv, f"/api/order/{order}/file/s1/after.webp")
    assert code == 200 and r.getheader("Content-Type") == "image/webp"
    assert get(srv, f"/api/order/{order}/file/s1%2Fafter.webp")[0] == 200  # as the page sends it
    assert get(srv, f"/api/order/{order}/file/shot.jpg")[2].getheader("Content-Type") == "image/jpeg"
    assert get(srv, f"/api/order/{order}/file/missing.png")[0] == 404


def test_file_route_refuses_everything_else(ws, run, srv, tmp_path):
    a, _ = waiting_stop(ws, run)
    b, _ = started(ws, run)
    put_file(ws, f"stops/{b}/secret.png", b"other order")
    put_file(ws, f"stops/{a}/notes.txt", b"text")
    put_file(ws, f"stops/{a}/page.svg", b"<svg/>")
    put_file(ws, f"stops/{a}/s1/deep/x.png")
    put_file(ws, f"stops/{a}/.hidden", b"x")
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    (Store(ws).base / "stops" / a / "link.png").symlink_to(outside)
    (Store(ws).base / "stops" / a / "s2").symlink_to(tmp_path, target_is_directory=True)
    (tmp_path / "x.png").write_bytes(PNG)
    bad = [
        "notes.txt",
        "page.svg",
        ".hidden",
        "link.png",
        "s2/x.png",
        "s1/deep/x.png",
        f"../{b}/secret.png",
        f"..%2F{b}%2Fsecret.png",
        f"s1/../../{b}/secret.png",
        f"%2e%2e/{b}/secret.png",
        "..",
        "..%2f..%2fjournal.jsonl",
        "journal.jsonl",
        "before.png%00.txt",
        "a" * 90 + ".png",
        "s1/",
        "/etc/passwd",
        "S1/x.png",
        "x.png/",
    ]
    for name in bad:
        code, *_ = get(srv, f"/api/order/{a}/file/{name}")
        assert code == 404, name
    # another order's file only through its own id
    assert get(srv, f"/api/order/{b}/file/secret.png")[0] == 200
    assert get(srv, f"/api/order/{a}/file/secret.png")[0] == 404


def test_file_route_size_cap(ws, run, srv, monkeypatch):
    order, _ = waiting_stop(ws, run)
    monkeypatch.setattr(pageapi, "MAX_IMAGE", 100)
    put_file(ws, f"stops/{order}/ok.png", b"x" * 100)
    put_file(ws, f"stops/{order}/big.png", b"x" * 101)
    assert get(srv, f"/api/order/{order}/file/ok.png")[0] == 200
    assert get(srv, f"/api/order/{order}/file/big.png")[0] == 404


def test_file_route_refuses_a_fifo_and_a_linked_folder(ws, run, srv, tmp_path):
    order, _ = waiting_stop(ws, run)
    fifo = Store(ws).base / "stops" / order / "pipe.png"
    os.mkfifo(fifo)
    assert pageapi.image(ws, order, "pipe.png") is None  # never opened for reading (it would block)
    other = tmp_path / "other"
    other.mkdir()
    (other / "z.png").write_bytes(PNG)
    folder = Store(ws).base / "stops" / "t_linked1"
    folder.symlink_to(other, target_is_directory=True)
    assert get(srv, "/api/order/t_linked1/file/z.png")[0] == 404


# ---- service ----------------------------------------------------------------------------------------------------


def test_status_and_start_return_the_page_url(ws, run, monkeypatch):
    out = run("start")
    try:
        assert out["running"] is True and out["url"].startswith("http://127.0.0.1:")
        status = run("status")
        assert status["url"] == out["url"] and status["pid"] == out["pid"]
        assert service.page_url(ws) == out["url"]
        code, home, _ = http_get(out["url"], "/api/home")
        assert code == 200 and home["watcher"] is True
        view = run("view")
        assert any(
            b.get("title") == "Factory page" and b["items"][0]["link"] == "addon:" for b in view["blocks"]
        )
    finally:
        run("stop")
    assert run("status", code=1) == {"running": False}
    assert service.page_url(ws) is None
    assert not any(b.get("title") == "Factory page" for b in run("view")["blocks"])


def http_get(url, path):
    host = url.removeprefix("http://")
    c = http.client.HTTPConnection(host, timeout=10)
    c.request("GET", path, headers={"Host": host})
    r = c.getresponse()
    return r.status, json.loads(r.read()), r


def test_page_url_needs_a_verified_watcher(ws):
    d = runfiles.run_dir(ws, "factory")
    runfiles.write_json(
        d / "factory.json", {"pid": os.getpid(), "nonce": "0" * 32, "started": "x", "port": 8431}
    )
    assert service.page_url(ws) is None  # a record that is not our watcher gives no address
    runfiles.write_json(d / "factory.json", {"pid": 1, "nonce": "0" * 32, "started": "x", "port": "8431"})
    assert service.page_url(ws, clean=False) is None


def test_server_binds_loopback_on_a_free_port(ws):
    a, b = server.make_server(ws), server.make_server(ws)
    try:
        assert a.server_address[0] == "127.0.0.1" and a.server_address[1] != b.server_address[1]
    finally:
        a.server_close()
        b.server_close()


def test_manifest_has_the_page():
    import tomllib
    from pathlib import Path

    import orch_factory

    m = tomllib.loads((Path(orch_factory.__file__).parent / "orch-addon.toml").read_text())
    assert m["page"] == {"path": "/", "label": "Open Factory"} and m["background"] is True


def test_threads_do_not_block_each_other(ws, run, srv):
    started(ws, run)
    results = []
    threads = [threading.Thread(target=lambda: results.append(get(srv, "/api/home")[0])) for _ in range(5)]
    [t.start() for t in threads]
    [t.join(20) for t in threads]
    assert results == [200] * 5


def test_page_script_never_writes_html():
    """API text reaches the DOM only as text; links stay inside the allowlist (static check of web/factory.js)."""
    import re
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src/orch_factory/web/factory.js").read_text(encoding="utf-8")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacent|document\.write|srcdoc|eval\(|new Function", js)
    for target in re.findall(r"""['"](/#[a-z]+)""", js):
        assert target in ("/#ticket", "/#chat"), target
