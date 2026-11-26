import http.client
import json
import threading

import pytest
from conftest import as_helper

KEY = "vouch-key-for-tests-0123456789"


@pytest.fixture
def server(ws):
    from orch_personal.server import make_server

    srv = make_server(ws, 0, vouch=lambda: KEY)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def call(port, method, path, body=None, vouched=True, origin=True, site="same-origin"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Host": f"127.0.0.1:{port}"}
    if vouched:
        h["X-Orch-Person"] = KEY
    if body is not None:
        h["Content-Type"] = "application/json"
        if origin:
            h["Origin"] = f"http://127.0.0.1:{port}"
        if site:
            h["Sec-Fetch-Site"] = site
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
    r = c.getresponse()
    data = r.read()
    return r.status, data


def test_page_and_kit_are_served(server):
    code, body = call(server, "GET", "/", vouched=False)
    assert code == 200 and b"personal.js" in body and b"__P__" not in body
    assert call(server, "GET", "/web/personal.js", vouched=False)[0] == 200
    assert call(server, "GET", "/web/../server.py", vouched=False)[0] == 404


def test_api_needs_the_dashboard(server):
    code, body = call(server, "GET", "/api/today", vouched=False)
    assert code == 403 and b"from the dashboard" in body
    code, _ = call(server, "POST", "/api/act", {"op": "add", "args": {"part": "notes"}}, vouched=False)
    assert code == 403


def test_person_adds_notes_chooses_folder_and_reads(server, vault, ws):
    assert call(server, "POST", "/api/act", {"op": "add", "args": {"part": "notes"}})[0] == 200
    code, body = call(server, "POST", "/api/act", {"op": "folder", "args": {"path": str(vault)}})
    assert code == 200, body
    today = json.loads(call(server, "GET", "/api/today")[1])
    assert today["parts"][0]["status"] == "3 notes"
    notes = json.loads(call(server, "GET", "/api/notes")[1])
    assert len(notes["notes"]) == 3
    note = json.loads(call(server, "GET", "/api/note?id=Projects%2FHelvetia%20Logistik")[1])
    assert note["title"] == "Helvetia Logistik" and note["tickets"] == []
    found = json.loads(call(server, "GET", "/api/find?q=fixpreis")[1])
    assert found["notes"][0]["id"] == "Projects/Preismodell 2027"
    tickets = json.loads(call(server, "GET", "/api/tickets")[1])["tickets"]
    assert tickets[0]["id"] == "t_abc123"
    code, body = call(server, "POST", "/api/act", {"op": "rules", "args": {"read": "all"}})
    assert code == 200 and json.loads(body)["result"]["read"] == "all"


def test_page_is_the_person_even_when_started_by_a_helper(server, vault, monkeypatch):
    as_helper(
        monkeypatch
    )  # the server process may inherit a helper's environment; the vouched click is the person
    assert call(server, "POST", "/api/act", {"op": "add", "args": {"part": "notes"}})[0] == 200


def test_refusals_are_plain_and_unknown_ops_fail(server, tmp_path):
    code, body = call(server, "POST", "/api/act", {"op": "folder", "args": {"path": str(tmp_path / "nope")}})
    assert code == 409 and "does not exist" in json.loads(body)["error"]
    assert call(server, "POST", "/api/act", {"op": "delete", "args": {}})[0] == 400
    assert (
        call(server, "POST", "/api/act", {"op": "add", "args": {"part": "notes"}}, site="cross-site")[0]
        == 403
    )
    assert call(server, "POST", "/api/act", {"op": "add", "args": {"part": "notes"}}, origin=False)[0] == 403
    assert call(server, "DELETE", "/api/act")[0] in (403, 405)


def test_notes_paging_takes_only_plain_numbers(server, vault):
    assert call(server, "POST", "/api/act", {"op": "add", "args": {"part": "notes"}})[0] == 200
    assert call(server, "POST", "/api/act", {"op": "folder", "args": {"path": str(vault)}})[0] == 200
    assert len(json.loads(call(server, "GET", "/api/notes?limit=1")[1])["notes"]) == 1
    for bad in ("%C2%B2", "%EF%BC%92", "-1", "x"):  # ² and a full-width 2 look like digits to str.isdigit
        code, body = call(server, "GET", f"/api/notes?limit={bad}&offset={bad}")
        assert code == 200 and len(json.loads(body)["notes"]) == 3, bad


def test_open_tickets_survive_hand_edited_files(server, ws):
    """Ticket files are plain JSON a person may fix by hand (R1.3): odd values never break Use in a ticket."""
    d = ws / ".orch" / "tickets"
    (d / "t_num00001.json").write_text(json.dumps({"title": 5, "updated_at": 17, "status": "open"}))
    (d / "t_lst00001.json").write_text(json.dumps({"id": ["x"], "key": None, "updated_at": None}))
    (d / "t_bad00001.json").write_text("{not json")
    (d / "t_arr00001.json").write_text("[1]")
    (d / "t_don00001.json").write_text(json.dumps({"status": "done", "title": "finished"}))
    code, body = call(server, "GET", "/api/tickets")
    assert code == 200, body
    rows = {r["id"]: r for r in json.loads(body)["tickets"]}
    assert set(rows) == {"t_abc123", "t_num00001", "t_lst00001"}
    assert rows["t_num00001"]["title"] == "5" and all(isinstance(r["updated"], str) for r in rows.values())


def test_server_edges(server, ws):
    assert call(server, "GET", "/nothing", vouched=False)[0] == 404
    assert call(server, "GET", "/api/nothing")[0] == 404
    assert json.loads(call(server, "GET", "/api/calendar")[1]) == {"on": False}
    rules = json.loads(call(server, "GET", "/api/rules")[1])
    assert rules["notes"] is None and rules["read"] and rules["write"]
    assert call(server, "POST", "/elsewhere", {"op": "add"})[0] in (403, 405)
    code, _ = call(server, "POST", "/api/act", {"op": "add", "args": {"part": "notes"}}, vouched=False)
    assert code == 403
    assert call(server, "POST", "/api/act", {"op": "add", "args": []})[0] == 400
    code, body = call(server, "POST", "/api/act", {"op": "add", "args": {"part": ""}})
    assert code == 409 and "Reload the page" in json.loads(body)["error"]
    code, body = call(server, "POST", "/api/act", {"op": "use", "args": {"ticket": "t_gone0001", "id": "x"}})
    assert code == 409 and "not there any more" in json.loads(body)["error"]
    for args in ({"part": "notes", "way": "w"}, {"part": "mail", "way": "w", "accounts": "all"}):
        code, body = call(server, "POST", "/api/act", {"op": "inbox_source", "args": args})
        assert code == 409 and "Reload the page" in json.loads(body)["error"]
    code, body = call(server, "POST", "/api/act", {"op": "meet_tickets", "args": {"id": "m", "steps": [0]}})
    assert code == 409 and "Reload the page" in json.loads(body)["error"]
