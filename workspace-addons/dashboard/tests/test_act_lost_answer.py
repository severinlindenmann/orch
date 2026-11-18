"""ORCH-580: New ticket over the remote address ended in ERR_CONTENT_LENGTH_MISMATCH while the ticket was made, and
every Retry made one more. A click carries an id the page made; a repeat of a done id runs nothing; the page can
ask whether an id went through; a big answer is never cut by the socket timeout."""

import gzip
import http.client
import json
import socket
import sys
import threading
import time

import pytest

from orch_dashboard import server as server_mod


@pytest.fixture
def made_orch(tmp_path, ws):
    """A fake `orch` whose `ticket new` writes a real ticket file (so the state shows it) and answers its id; it
    counts every `ticket new` in made.txt. mode.txt: ok | refuse | slow."""
    d = tmp_path / "madeorch"
    d.mkdir()
    (d / "mode.txt").write_text("ok")
    script = d / "orch"
    tdir = ws / ".orch" / "tickets"
    example = json.loads(
        (tdir / next(p.name for p in tdir.glob("t_*.json") if p.name != "t_broken0001.json")).read_text()
    )
    (d / "example.json").write_text(json.dumps(example))
    script.write_text(f"""#!{sys.executable}
import json, pathlib, sys, time
d = pathlib.Path(__file__).parent
a = sys.argv[1:]
if a[:2] != ["ticket", "new"]:
    sys.exit(2)
mode = (d / "mode.txt").read_text().strip()
if mode == "refuse":
    print(json.dumps({{"error": "Nope, not allowed."}}))
    sys.exit(2)
if mode == "slow":
    time.sleep(0.6)
f = d / "made.txt"
n = int(f.read_text() or 0) + 1 if f.exists() else 1
f.write_text(str(n))
tid = "t_made%04d" % n
t = json.loads((d / "example.json").read_text())
t.update(id=tid, title="Made %d" % n, status="open")
(pathlib.Path({str(tdir)!r}) / (tid + ".json")).write_text(json.dumps(t))
print(json.dumps({{"ok": True, "id": tid}}))
""")
    script.chmod(0o755)
    return script


def made(orch) -> int:
    f = orch.parent / "made.txt"
    return int(f.read_text()) if f.exists() else 0


@pytest.fixture
def big_ws(ws):
    """The state is several MB, like the owner's workspace (about 6 MB)."""
    tdir = ws / ".orch" / "tickets"
    src = json.loads((tdir / "t_weekly01.json").read_text())
    for i in range(40):
        t = dict(src, id=f"t_big{i:05d}", title=f"Big {i}", note="n" * 100_000, status="open")
        (tdir / f"{t['id']}.json").write_text(json.dumps(t))
    return ws


def _serve(ws, orch):
    srv = server_mod.make_server(ws, 0, orch_bin=str(orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def srv(big_ws, made_orch):
    s = _serve(big_ws, made_orch)
    yield s
    s.shutdown()
    s.server_close()


def _headers(port, act_id=None, **extra):
    h = {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
        "X-Orch-Op": "ticket.new",
    }
    if act_id:
        h["X-Orch-Act-Id"] = act_id
    h.update(extra)
    return h


def new_ticket(srv, act_id=None, **extra):
    port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request(
        "POST",
        "/api/act",
        body=json.dumps({"op": "ticket.new", "args": {"title": "One line"}}),
        headers=_headers(port, act_id, **extra),
    )
    r = c.getresponse()
    raw = r.read()
    if r.getheader("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return r.status, raw, dict(r.getheaders())


def status_of(srv, act_id):
    port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/api/act/status?id=" + act_id, headers={"Host": f"127.0.0.1:{port}"})
    r = c.getresponse()
    raw = r.read()
    return r.status, json.loads(raw) if r.status == 200 else raw


def cut_new_ticket(srv, act_id) -> int:
    """Send New ticket and drop the connection after the first bytes of the answer (the answer is lost)."""
    port = srv.server_address[1]
    body = json.dumps({"op": "ticket.new", "args": {"title": "One line"}}).encode()
    s = socket.create_connection(("127.0.0.1", port), timeout=30)
    head = "".join(f"{k}: {v}\r\n" for k, v in _headers(port, act_id).items())
    s.sendall(f"POST /api/act HTTP/1.1\r\n{head}Content-Length: {len(body)}\r\n\r\n".encode() + body)
    got = s.recv(2048)
    s.close()
    return len(got)


def test_cut_answer_then_retry_makes_exactly_one_ticket(srv, made_orch):
    act_id = "page-0123456789abcdef"
    assert cut_new_ticket(srv, act_id) > 0
    for _ in range(50):  # the server finishes the op although the page has gone
        code, st = status_of(srv, act_id)
        if st["state"] == "done":
            break
        time.sleep(0.1)
    assert code == 200 and st["state"] == "done" and st["status"] == 200
    assert st["reply"]["created"] == {"id": "t_made0001"}
    code, raw, _ = new_ticket(srv, act_id)  # Retry with the same id: the first result, nothing made again
    assert code == 200 and json.loads(raw)["created"] == {"id": "t_made0001"}
    assert made(made_orch) == 1


def test_double_click_with_one_id_runs_once(srv, made_orch):
    (made_orch.parent / "mode.txt").write_text("slow")
    out = []
    th = [threading.Thread(target=lambda: out.append(new_ticket(srv, "dbl-0123456789"))) for _ in range(2)]
    for t in th:
        t.start()
    for t in th:
        t.join(30)
    assert [o[0] for o in out] == [200, 200]
    assert {json.loads(o[1])["created"]["id"] for o in out} == {"t_made0001"}
    assert made(made_orch) == 1


def test_a_refused_click_is_not_remembered(srv, made_orch):
    (made_orch.parent / "mode.txt").write_text("refuse")
    assert new_ticket(srv, "ref-0123456789")[0] != 200
    assert status_of(srv, "ref-0123456789")[1] == {"state": "unknown"}
    (made_orch.parent / "mode.txt").write_text("ok")
    assert new_ticket(srv, "ref-0123456789")[0] == 200  # fixed and sent again: it runs now
    assert made(made_orch) == 1


def test_ids_are_separate_and_status_checks_its_input(srv, made_orch):
    assert new_ticket(srv, "a-0123456789")[0] == 200
    assert new_ticket(srv, "b-0123456789")[0] == 200
    assert new_ticket(srv)[0] == 200  # no id (an older page): runs as before
    assert made(made_orch) == 3
    assert status_of(srv, "never-sent-0123")[1] == {"state": "unknown"}
    assert status_of(srv, "bad%20id")[0] == 400


def test_answer_is_a_small_gzipped_delta_when_the_page_holds_a_revision(srv, made_orch):
    port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request("GET", "/api/state", headers={"Host": f"127.0.0.1:{port}"})
    r = c.getresponse()
    full = r.read()
    rev = json.loads(full)["rev"]
    code, raw, hdr = new_ticket(srv, "dlt-0123456789", **{"X-Orch-Have": rev, "Accept-Encoding": "gzip"})
    out = json.loads(raw)
    assert code == 200 and hdr.get("Content-Encoding") == "gzip"
    assert out["delta"] is True and out["base"] == rev
    assert out["set"]["created"] == {"id": "t_made0001"} and "created" in out["keys"]
    assert [row["id"] for row in out.get("upsert", [])] == ["t_made0001"]
    assert len(raw) < len(full) / 20  # not the whole state again


def test_a_slow_reader_gets_the_whole_answer(monkeypatch, srv, made_orch):
    """The socket timeout once bounded the whole write of the answer: a big answer to a slow link was cut while the
    header kept the full length (ERR_CONTENT_LENGTH_MISMATCH). Now it bounds each slice only."""
    monkeypatch.setattr(server_mod.Handler, "timeout", 0.3)
    port = srv.server_address[1]
    body = json.dumps({"op": "ticket.new", "args": {"title": "One line"}}).encode()
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024)
    s.settimeout(30)
    s.connect(("127.0.0.1", port))
    head = "".join(f"{k}: {v}\r\n" for k, v in _headers(port, "slow-0123456789").items())
    s.sendall(
        f"POST /api/act HTTP/1.1\r\n{head}Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
        + body
    )
    data = b""
    started = time.monotonic()
    while True:
        chunk = s.recv(32 * 1024)
        if not chunk:
            break
        data += chunk
        time.sleep(0.01)  # a slow link: steady, but the whole answer takes longer than the timeout
    s.close()
    head, _, rest = data.partition(b"\r\n\r\n")
    length = int(
        next(
            line.split(b":")[1] for line in head.split(b"\r\n") if line.lower().startswith(b"content-length")
        )
    )
    assert length > 3_000_000
    assert time.monotonic() - started > 0.3
    assert len(rest) == length
    assert json.loads(rest)["created"] == {"id": "t_made0001"}


def test_same_id_with_other_contents_is_refused_and_runs_nothing(srv, made_orch):
    port = srv.server_address[1]
    assert new_ticket(srv, "same-0123456789")[0] == 200
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    body = json.dumps({"op": "ticket.new", "args": {"title": "Something else"}})
    c.request("POST", "/api/act", body=body, headers=_headers(port, "same-0123456789"))
    r = c.getresponse()
    assert r.status == 400 and b"already sent with other contents" in r.read()
    assert made(made_orch) == 1


def test_a_click_is_only_told_to_who_sent_it():
    from orch_dashboard.actids import ActIds

    mem = ActIds()
    entry, first = mem.claim("own-0123456789", "ticket.new", (True, None), "h")
    assert first
    mem.finish(entry, (200, "", {"id": "t_x"}), {"created": {"id": "t_x"}})
    assert mem.status("own-0123456789", (True, None))["reply"] == {"created": {"id": "t_x"}}
    assert mem.status("own-0123456789", (False, None)) == {"state": "unknown"}  # watch-only
    assert mem.status("own-0123456789", (True, "sync")) == {"state": "unknown"}  # an add-on page's pass
