"""T0 settings: the view, the widening rule, and the H1 fence of POST /api/act (human-only clicks)."""

import http.client
import json
import re
from importlib import resources

import pytest
from conftest import SETTINGS, TICKETS, FakeSession, calls
from test_overview import request

from orch_insights import actions
from orch_insights.settings import ERROR, PERSON, TICKETS_ERROR, build_settings, needs_person

PACKAGE = resources.files("orch_insights")
WRITES = (["config", "set"], ["record", "delete-detail"])
FORBIDDEN_FLAGS = ("--by", "--from", "--as", "--dev")
WIDENING = [
    ("insights.share_names", "on"),
    ("insights.keep_days", "365"),
    ("insights.max_mb", "4096"),
    ("insights.share_counts", "on"),
]
NARROWING = [("insights.keep_days", "30"), ("insights.share_names", "off"), ("insights.max_mb", "512")]


def post(server, body, headers=None, cookie=False, path="/api/act"):
    port = server.server_address[1]
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    base = {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
        "Content-Length": str(len(raw)),
    }
    if cookie:
        base["Cookie"] = "orch_page=good-cookie-value"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", path, body=raw, headers={**base, **(headers or {})})
    response = conn.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    conn.close()
    return result


def setting(key, value):
    return {"op": "settings.set", "args": {"key": key, "value": value}}


def delete(ticket="t_abc123"):
    return {"op": "record.delete_detail", "args": {"ticket": ticket}}


def writes(fake):
    return [c for c in calls(fake) if any(c["args"][:2] == w for w in WRITES)]


def strings(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from strings(value)
    elif isinstance(node, str):
        yield node


def options(row):
    return {o["value"]: o for o in row["options"]}


# -- the pure parts -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key,value,current,expected",
    [
        ("insights.keep_days", "365", "90", True),
        ("insights.keep_days", "90", "90", False),
        ("insights.keep_days", "30", "90", False),
        ("insights.keep_days", "30", "12", True),
        ("insights.max_mb", "4096", "2048", True),
        ("insights.max_mb", "512", "2048", False),
        ("insights.share_counts", "on", "off", True),
        ("insights.share_counts", "off", "on", False),
        ("insights.share_names", "on", "on", True),
        ("insights.share_names", "off", "off", False),
        ("insights.keep_days", "30", None, True),
        ("insights.share_names", "off", None, True),
    ],
)
def test_needs_person(key, value, current, expected):
    assert needs_person(key, value, current) is expected


def test_build_settings_rows_and_widening_flags(answer):
    view = build_settings(SETTINGS, answer, TICKETS, True)
    assert view["can_act"] is True
    keep = options(view["keep"])
    assert list(keep) == ["30", "90", "365"]
    assert [keep[v]["needs_person"] for v in keep] == [False, False, True]
    assert keep["90"]["selected"] and not keep["30"]["selected"]
    assert view["keep"]["note"] == "up to 2048 MB, oldest detail first. Counts are kept."
    size = options(view["size"])
    assert [size[v]["label"] for v in size] == ["512 MB", "1 GB", "2 GB", "4 GB"]
    assert [size[v]["needs_person"] for v in size] == [False, False, False, True]
    share = options(view["share_counts"])
    assert share["on"]["needs_person"] and not share["off"]["needs_person"] and share["off"]["selected"]
    assert options(view["share_names"])["on"]["needs_person"]
    assert not any(
        o["disabled"] for row in ("keep", "size", "share_counts", "share_names") for o in view[row]["options"]
    )
    assert view["usage"] == "Using 120 MB (detail 100 MB) in 23 runs"
    assert view["narrow_note"] == "Takes effect at the next cleanup; nothing is deleted now."
    assert view["recorded"]["since"] == answer["since"]
    assert view["recorded"]["what"].startswith("Everything agents do")
    assert view["share_names"]["note"] == "Your own skill, connection and key names are sent too."


def test_build_settings_without_person_disables_widening(answer):
    view = build_settings({**SETTINGS, "share_counts": True}, answer, TICKETS, False)
    assert view["can_act"] is False
    keep = options(view["keep"])
    assert keep["365"]["disabled"] and not keep["30"]["disabled"] and not keep["90"]["disabled"]
    assert view["keep"]["person_note"] == PERSON
    share = options(view["share_counts"])
    assert not share["on"]["disabled"] and not share["off"]["disabled"]  # on is already the value
    assert view["share_counts"]["person_note"] is None
    assert options(view["share_names"])["on"]["disabled"]
    assert build_settings(SETTINGS, answer, TICKETS, "yes")["can_act"] is False


@pytest.mark.parametrize(
    "state,locked,reason",
    [
        ("off_by_admin", True, "Switched off by your admin"),
        ("not_connected", True, "Not connected to an admin"),
        ("on", False, None),
        ("off", False, None),
    ],
)
def test_admin_lock_states(answer, state, locked, reason):
    answer["sharing"]["counts"] = state
    row = build_settings(SETTINGS, answer, TICKETS, True)["share_counts"]
    assert row["locked"] is locked and row["reason"] == reason
    assert (row["options"] == []) is locked
    assert "on" not in options(row) or not locked


def test_unreadable_counts_lock_sharing(answer):
    view = build_settings(SETTINGS, None, TICKETS, True)
    assert view["share_counts"]["locked"] and view["share_counts"]["options"] == []
    assert view["recorded"]["since"] is None
    assert options(view["keep"])["365"]["disabled"] is False


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {"status": "unavailable", "reason": "io", "message": "x"},
        {**SETTINGS, "keep_days": None},
        {**SETTINGS, "max_mb": "2048"},
        {**SETTINGS, "share_names": "no"},
        {**SETTINGS, "keep_days": True},
    ],
)
def test_unavailable_settings_fail_closed(answer, bad):
    assert build_settings(bad, answer, TICKETS, True) == {"error": ERROR}


def test_no_numbers_when_absent_and_no_forbidden_words(answer):
    partial = {k: v for k, v in SETTINGS.items() if k not in ("record_mb", "runs")}
    view = build_settings(partial, answer, TICKETS, False)
    assert view["usage"] is None
    assert build_settings({**SETTINGS, "detail_mb": None}, answer, TICKETS, True)["usage"] is None
    for state in ("on", "off", "off_by_admin", "not_connected"):
        answer["sharing"]["counts"] = state
        for can_act in (True, False):
            text = " ".join(strings(build_settings(SETTINGS, answer, TICKETS, can_act))).lower()
            for word in ("hub", "netbird", "vpn"):
                assert word not in text


def test_tickets_titles_as_data_and_failure(answer):
    view = build_settings(SETTINGS, answer, [*TICKETS, {"id": "../x", "title": "bad"}, "junk"], True)
    assert view["tickets"]["error"] is None
    assert view["tickets"]["rows"] == [
        {"ticket": "t_abc123", "title": "Invoice export"},
        {"ticket": "t_def456", "title": "<img src=x onerror=alert(1)>"},
    ]
    assert build_settings(SETTINGS, answer, None, True)["tickets"] == {"rows": [], "error": TICKETS_ERROR}


# -- H1: nothing a person must do runs without the person ----------------------------------------------------


@pytest.mark.parametrize("body", [setting(*w) for w in WIDENING] + [delete()])
def test_widening_and_delete_without_session_refused(start_server, fake_orch, fake_session, body):
    for srv in (start_server(), start_server(session=fake_session)):
        code, _, text = post(srv, body)
        assert code == 403
        assert text.decode() == "Open Insights from the dashboard on this computer to do this."
    assert writes(fake_orch) == []
    assert fake_session.minted == []


SMUGGLED = [
    {**setting("insights.share_names", "on"), "by": "human:anna"},
    {"op": "settings.set", "args": {"key": "insights.share_names", "value": "on", "by": "human:anna"}},
    {"op": "settings.set", "args": {"key": "insights.share_names", "value": "on", "proof": "hp1.x"}},
    {
        "op": "settings.set",
        "args": {"key": "insights.share_names", "value": "on", "flags": ["--by", "human:x"]},
    },
    {**setting("insights.share_names", "on"), "--proof-stdin": True},
    {**setting("insights.share_names", "on"), "from": "local-page"},
    {"op": "settings.set", "args": {"key": "insights.keep_days", "value": "365", "widen": False}},
    {"op": "settings.set", "args": {"key": "insights.keep_days", "value": "365", "narrow": True}},
    {**setting("insights.keep_days", "365"), "widen": False},
    {"op": "record.delete_detail", "args": {"ticket": "t_abc123", "confirmed": True}},
    {"op": "settings.set", "args": {"key": "workspace.agent", "value": "x"}},
    {"op": "settings.set", "args": {"key": "insights.keep_days", "value": "12"}},
    {"op": "settings.set", "args": {"key": "insights.keep_days", "value": 30}},
    {"op": "settings.set", "args": {"key": "insights.share_names", "value": "on --by human:x"}},
    {"op": "config.set", "args": {"key": "insights.keep_days", "value": "30"}},
    {"op": "settings.set", "args": ["insights.keep_days", "30"]},
    ["settings.set"],
]


@pytest.mark.parametrize("body", SMUGGLED)
def test_smuggled_fields_rejected(start_server, fake_orch, fake_session, body):
    srv = start_server(session=fake_session)
    code, _, _ = post(srv, body, cookie=True)
    assert code == 400
    assert calls(fake_orch) == []
    assert fake_session.minted == []


@pytest.mark.parametrize(
    "ticket", ["../x", "t_ABC123", "t_abc", "t_" + "a" * 40, "", None, 7, "t_abc123 --by"]
)
def test_delete_detail_ticket_regex(start_server, fake_orch, fake_session, ticket):
    srv = start_server(session=fake_session)
    assert post(srv, delete(ticket), cookie=True)[0] == 400
    assert calls(fake_orch) == [] and fake_session.minted == []


def test_agent_env_never_reaches_the_child(start_server, fake_orch, fake_session, monkeypatch):
    for name, value in {
        "ORCH_AGENT": "x",
        "CLAUDECODE": "1",
        "ORCH_RUN": "r_x",
        "ORCH_TICKET": "t_x",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("ORCH_DEV", "1")
    srv = start_server(session=fake_session)
    assert post(srv, setting("insights.share_names", "on"), cookie=True)[0] == 200
    assert post(srv, setting("insights.keep_days", "30"), cookie=True)[0] == 200
    assert post(srv, delete(), cookie=True)[0] == 200
    done = writes(fake_orch)
    assert len(done) == 3
    for call in done:
        for name in ("ORCH_AGENT", "CLAUDECODE", "ORCH_RUN", "ORCH_TICKET", "ORCH_DEV"):
            assert name not in call["env"]
        assert not set(call["args"]) & set(FORBIDDEN_FLAGS)
        assert not any(a.startswith(FORBIDDEN_FLAGS) for a in call["args"])
        assert call["env"]["ORCH_ROOT"] == call["root"]


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Forwarded-For": "10.0.0.1"},
        {"Forwarded": "for=10.0.0.1"},
        {"Host": "localhost:1", "Origin": "http://localhost:1"},
        {"Cookie": "orch_page=wrong"},
        {"Cookie": ""},
    ],
)
def test_no_mint_without_a_clean_session(start_server, fake_orch, fake_session, headers):
    srv = start_server(session=fake_session)
    for key, value in WIDENING:
        assert post(srv, setting(key, value), headers=headers, cookie=True)[0] == 403
    assert post(srv, delete(), headers=headers, cookie=True)[0] == 403
    assert writes(fake_orch) == [] and fake_session.minted == []
    for key, value in NARROWING:
        code, _, body = post(srv, setting(key, value), headers=headers, cookie=True)
        assert code == 200 and json.loads(body) == {"result": {"key": key, "value": value}}
    done = writes(fake_orch)
    assert [c["args"] for c in done] == [["config", "set", k, v, "--json"] for k, v in NARROWING]
    assert all(c["stdin"] == "" for c in done)
    assert fake_session.minted == []


def test_widening_hands_the_proof_on_stdin_only(start_server, fake_orch, fake_session):
    srv = start_server(session=fake_session)
    code, _, body = post(srv, setting("insights.keep_days", "365"), cookie=True)
    assert code == 200 and json.loads(body) == {"result": {"key": "insights.keep_days", "value": "365"}}
    assert fake_session.minted == [("insights.settings", "insights.keep_days")]
    (call,) = writes(fake_orch)
    assert call["args"] == ["config", "set", "insights.keep_days", "365", "--json", "--proof-stdin"]
    proof = call["stdin"].splitlines()[0]
    assert proof == "hp1.fakeproof1.mac"
    assert not any(proof in a for a in call["args"])
    assert not any(proof in v for v in call["env"].values())
    reads = [c["args"] for c in calls(fake_orch) if c not in writes(fake_orch)]
    assert reads == [["record", "settings", "--json"]]  # the server decided from a fresh read
    assert post(srv, setting("insights.share_counts", "off"), cookie=True)[0] == 200
    assert writes(fake_orch)[-1]["stdin"] == "" and "--proof-stdin" not in writes(fake_orch)[-1]["args"]
    assert len(fake_session.minted) == 1


def test_current_value_read_failure_counts_as_widening(start_server, fake_orch, fake_session):
    (fake_orch.parent / "settings_exit").touch()
    srv = start_server(session=fake_session)
    assert post(srv, setting("insights.keep_days", "30"))[0] == 403
    assert writes(fake_orch) == []
    assert post(srv, setting("insights.keep_days", "30"), cookie=True)[0] == 200
    assert fake_session.minted == [("insights.settings", "insights.keep_days")]
    assert writes(fake_orch)[0]["stdin"].splitlines()[0] == "hp1.fakeproof1.mac"


def test_delete_detail_one_call_with_proof(start_server, fake_orch, fake_session):
    srv = start_server(session=fake_session)
    code, _, body = post(srv, delete("t_abc123"), cookie=True)
    assert code == 200 and json.loads(body) == {"result": {"deleted": 3}}
    assert fake_session.minted == [("record.delete_detail", "t_abc123")]
    assert [c["args"] for c in calls(fake_orch)] == [
        ["record", "delete-detail", "t_abc123", "--json", "--proof-stdin"]
    ]
    assert calls(fake_orch)[0]["stdin"] == "hp1.fakeproof1.mac\n"


@pytest.mark.parametrize(
    "refusal,status,text",
    [
        ({"error": "Do this in the dashboard on this computer.", "code": "needs_person"}, 403, None),
        ({"error": "That ticket does not exist.\nsecond line", "code": "not_found"}, 422, None),
        ({"error": "x" * 900, "code": "invalid"}, 422, "x" * 300),
    ],
)
def test_core_refusals_mapped(start_server, fake_orch, fake_session, refusal, status, text):
    (fake_orch.parent / "refuse.json").write_text(json.dumps(refusal))
    srv = start_server(session=fake_session)
    code, _, body = post(srv, delete(), cookie=True)
    assert code == status
    assert body.decode() == (text or refusal["error"].splitlines()[0])
    assert len(writes(fake_orch)) == 1


def test_fence_on_post(start_server, fake_orch, fake_session):
    srv = start_server(session=fake_session)
    body = setting("insights.keep_days", "30")
    assert post(srv, body, headers={"Origin": "http://evil.example"})[0] == 403
    assert post(srv, body, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert post(srv, body, headers={"Content-Type": "text/plain"})[0] == 415
    assert post(srv, b"x" * 5000)[0] == 400
    assert post(srv, b"not json")[0] == 400
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    raw = json.dumps(body).encode()
    conn.request(
        "POST",
        "/api/act",
        body=raw,
        headers={"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"},
    )
    assert conn.getresponse().status == 403  # no Origin on a POST
    conn.close()
    assert post(srv, body, path="/api/settings")[0] == 405
    assert calls(fake_orch) == []


def test_gets_never_write(server, fake_orch):
    for path in ("/api/overview", "/api/list/skills", "/api/settings", "/api/settings?x=1"):
        assert request(server, path)[0] == 200
    seen = [c["args"] for c in calls(fake_orch)]
    assert writes(fake_orch) == []
    assert {tuple(a) for a in seen} == {
        ("record", "counts", "--days", "30", "--json"),
        ("record", "settings", "--json"),
        ("ticket", "list", "--all", "--json"),
    }


def test_get_settings_view(start_server, fake_orch, fake_session):
    srv = start_server(session=fake_session)
    code, headers, body = request(srv, "/api/settings")
    view = json.loads(body)
    assert code == 200 and headers["Content-Type"] == "application/json"
    assert view["can_act"] is False and view["share_counts"]["locked"] is False
    assert view["tickets"]["rows"][1]["title"] == "<img src=x onerror=alert(1)>"
    view = json.loads(request(srv, "/api/settings", headers={"Cookie": "orch_page=good-cookie-value"})[2])
    assert view["can_act"] is True
    (fake_orch.parent / "tickets_exit").touch()
    assert json.loads(request(srv, "/api/settings")[2])["tickets"]["error"] == TICKETS_ERROR
    (fake_orch.parent / "settings_exit").touch()
    assert json.loads(request(srv, "/api/settings")[2]) == {"error": ERROR}
    assert request(srv, "/api/settings", headers={"Host": "evil.example:1"})[0] == 403


def test_session_post(start_server, fake_session):
    token = {"token": FakeSession.token}
    plain = start_server()
    assert post(plain, token, path="/session")[0] == 403
    srv = start_server(session=fake_session)
    assert post(srv, {"token": "wrong-token-abcdefghijkl"}, path="/session")[0] == 403
    assert post(srv, token, path="/session", headers={"X-Forwarded-For": "1.2.3.4"})[0] == 403
    code, headers, _ = post(srv, token, path="/session")
    assert code == 204
    assert headers["Set-Cookie"] == "orch_page=good-cookie-value; HttpOnly; SameSite=Strict; Path=/"


def test_no_insights_page_server_in_core_is_watch_only(start_server, fake_orch, monkeypatch):
    import orch.pageproof

    monkeypatch.setattr(orch.pageproof, "SERVERS", ("focus", "dashboard"))
    srv = start_server(orch_bin=None)
    assert srv.session is None
    assert request(srv, "/")[0] == 200
    code, _, text = post(srv, delete(), cookie=True)
    assert code == 403 and text.decode() == "Open Insights from the dashboard on this computer to do this."
    assert post(srv, {"token": FakeSession.token}, path="/session")[0] == 403
    assert calls(fake_orch) == []


def test_run_op_fake_bin_still_needs_a_mint(ws, fake_orch):
    with pytest.raises(actions.NeedsPerson):
        actions.run_op(ws, str(fake_orch), "record.delete_detail", {"ticket": "t_abc123"})
    with pytest.raises(actions.NeedsPerson):
        actions.run_op(ws, str(fake_orch), "settings.set", {"key": "insights.keep_days", "value": "30"})
    assert calls(fake_orch) == []


def test_human_env_refuses_without_the_list(ws, monkeypatch):
    import orch.adapters

    def broken(environ):
        raise OSError("bad adapter")

    monkeypatch.setattr(orch.adapters, "human_environ", broken)
    with pytest.raises(actions.Unavailable):
        actions.human_env(ws, "/x/orch")


# -- the page --------------------------------------------------------------------------------------------------


def test_frontend_text_only_and_plain_words():
    js = PACKAGE.joinpath("web", "settings.js").read_text()
    html = PACKAGE.joinpath("web", "index.html").read_text()
    for text in (js, PACKAGE.joinpath("web", "insights.js").read_text()):
        assert "innerHTML" not in text and "insertAdjacentHTML" not in text and "outerHTML" not in text
    for text in (js, html):
        for word in ("hub", "netbird", "vpn"):
            assert word not in text.lower()
    assert "textContent" in js
    assert "/api/act" in js and "/api/settings" in js and "record.delete_detail" in js
    assert "Delete the full detail of this ticket's runs? The counts stay. This cannot be undone." in html
    assert re.search(r'id="settings-link"[^>]*>Settings<', html)
    assert "settings.js" in html
    # the ticket id goes in the POST body only, never on screen
    assert "entry.ticket" in js and not re.search(r"node\([^)]*entry\.ticket", js)
    assert "confirm" not in json.dumps(delete())


def test_settings_js_served(server):
    code, headers, body = request(server, "/web/settings.js")
    assert code == 200 and headers["Content-Type"] == "text/javascript"
    assert body == PACKAGE.joinpath("web", "settings.js").read_bytes()
