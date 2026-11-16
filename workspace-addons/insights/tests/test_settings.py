from pathlib import Path

"""T0 settings: the view, the widening rule, and the H1 fence of POST /api/act (human-only clicks)."""

import http.client
import json
import re
import threading
from importlib import resources

import pytest
from conftest import SETTINGS, TICKETS, FakeSession, calls
from test_overview import request

from orch_insights import actions
from orch_insights.settings import ERROR, PERSON, TICKETS_ERROR, build_settings

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


def post(server, body, headers=None, cookie=False, path="/api/act", secret=None):
    port = server.server_address[1]
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    base = {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
        "Content-Length": str(len(raw)),
        "Sec-Fetch-Site": "same-origin",  # a browser always sends it; tests of its absence use post_bare
    }
    if cookie:
        base["Cookie"] = f"orch_page_insights_{port}=good-cookie-value"
    if secret is not None:
        base["X-Orch-Page"] = secret
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", path, body=raw, headers={**base, **(headers or {})})
    response = conn.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    conn.close()
    return result


def post_bare(server, body, path="/api/act"):
    """A POST with NO Sec-Fetch-Site header (a script or old client) but otherwise a valid-looking request."""
    port = server.server_address[1]
    raw = json.dumps(body).encode()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(
        "POST",
        path,
        body=raw,
        headers={
            "Host": f"127.0.0.1:{port}",
            "Origin": f"http://127.0.0.1:{port}",
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
            "Cookie": f"orch_page_insights_{port}=good-cookie-value",
        },
    )
    status = conn.getresponse().status
    conn.close()
    return status


def link(server, token=FakeSession.token):
    """Spend the launch token like the page does; returns the page secret of this server."""
    site = {"Sec-Fetch-Site": "same-origin"}
    code, _, body = post(server, {"token": token}, path="/session", headers=site)
    assert code == 200
    return json.loads(body)["secret"]


def person(server, body, headers=None):
    """A click with the person: session cookie and this server's page secret."""
    return post(server, body, headers=headers, cookie=True, secret=link(server))


def setting(key, value):
    return {"op": "settings.set", "args": {"key": key, "value": value}}


def delete(ticket="t_abc123"):
    return {"op": "record.delete_detail", "args": {"ticket": ticket}}


def writes(fake):
    return [c for c in calls(fake) if any(c["args"][:2] == w for w in WRITES)]


def stored(fake):
    return json.loads((fake.parent / "settings.json").read_text())


def set_argv(key, value, current):
    return ["config", "set", key, value, f"--if-current={current}", "--json"]


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


def test_build_settings_rows(answer):
    view = build_settings(SETTINGS, answer, TICKETS, True)
    assert view["can_act"] is True
    keep = options(view["keep"])
    assert list(keep) == ["30", "90", "365"]
    assert keep["90"]["selected"] and not keep["30"]["selected"]
    assert view["keep"]["note"] == "up to 2048 MB, oldest detail first. Counts are kept."
    size = options(view["size"])
    assert [size[v]["label"] for v in size] == ["512 MB", "1 GB", "2 GB", "4 GB"]
    share = options(view["share_counts"])
    assert share["off"]["selected"]
    assert not any(
        o["disabled"] for row in ("keep", "size", "share_counts", "share_names") for o in view[row]["options"]
    )
    assert view["usage"] == "Using 120 MB (detail 100 MB) in 23 runs"
    assert view["narrow_note"] == "Takes effect at the next cleanup; nothing is deleted now."
    assert view["recorded"]["since"] == answer["since"]
    assert view["recorded"]["what"].startswith("Everything agents do")
    assert view["share_names"]["note"] == "Your own skill, connection and key names are sent too."


def test_build_settings_without_person_disables_changes(answer):
    view = build_settings({**SETTINGS, "share_counts": True}, answer, TICKETS, False)
    assert view["can_act"] is False
    keep = options(view["keep"])
    assert (
        keep["365"]["disabled"] and keep["30"]["disabled"] and not keep["90"]["disabled"]
    )  # 90 is the value
    assert view["keep"]["person_note"] == PERSON
    share = options(view["share_counts"])
    assert not share["on"]["disabled"] and share["off"]["disabled"]  # on is already the value
    assert view["share_counts"]["person_note"] == PERSON
    assert options(view["share_names"])["on"]["disabled"]
    assert build_settings(SETTINGS, answer, TICKETS, "yes")["can_act"] is False


@pytest.mark.parametrize(
    "state,locked,reason",
    [
        ("off_by_admin", True, "Switched off by your admin"),
        ("not_connected", True, "Not connected to an admin, so nothing is shared"),
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
    # unknown / unreadable: a neutral line that claims nothing about what is shared (not "nothing is shared")
    assert view["share_counts"]["reason"] == "Sharing status isn't available right now."
    assert (
        "nothing is shared" not in view["share_counts"]["reason"]
        and "could not" not in view["share_counts"]["reason"]
    )
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


# -- a change needs the page session; it runs once, as the person ---------------------------------------------


@pytest.mark.parametrize(
    "body", [setting(*w) for w in WIDENING] + [setting(*w) for w in NARROWING] + [delete()]
)
def test_a_change_without_session_is_refused_and_runs_nothing(start_server, fake_orch, fake_session, body):
    for srv in (start_server(), start_server(session=fake_session)):
        code, _, text = post(srv, body)
        assert code == 403
        assert text.decode() == "Open Insights from the dashboard on this computer to do this."
    assert writes(fake_orch) == []
    assert stored(fake_orch) == SETTINGS


SMUGGLED = [
    {**setting("insights.share_names", "on"), "by": "human:anna"},
    {"op": "settings.set", "args": {"key": "insights.share_names", "value": "on", "by": "human:anna"}},
    {
        "op": "settings.set",
        "args": {"key": "insights.share_names", "value": "on", "flags": ["--by", "human:x"]},
    },
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
    code, _, _ = person(srv, body)  # incl. client fields claiming widen/narrow: 400, never trusted
    assert code == 400
    assert calls(fake_orch) == []


@pytest.mark.parametrize(
    "ticket", ["../x", "t_ABC123", "t_abc", "t_" + "a" * 40, "", None, 7, "t_abc123 --by"]
)
def test_delete_detail_ticket_regex(start_server, fake_orch, fake_session, ticket):
    srv = start_server(session=fake_session)
    assert person(srv, delete(ticket))[0] == 400
    assert calls(fake_orch) == []


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
def test_no_change_without_a_clean_session(start_server, fake_orch, fake_session, headers):
    srv = start_server(session=fake_session)
    secret = link(srv)
    for key, value in WIDENING:
        assert post(srv, setting(key, value), headers=headers, cookie=True, secret=secret)[0] == 403
    assert post(srv, delete(), headers=headers, cookie=True, secret=secret)[0] == 403
    assert writes(fake_orch) == []
    assert stored(fake_orch) == SETTINGS


def test_narrowing_and_same_value_run_plainly(start_server, fake_orch, fake_session):
    srv = start_server(session=fake_session)
    for key, value in [*NARROWING, ("insights.max_mb", "512"), ("insights.share_counts", "off")]:
        assert person(srv, setting(key, value))[0] == 200
    same = json.loads(person(srv, setting("insights.keep_days", "30"))[2])
    assert same == {"result": {"insights.keep_days": "30", "changed": False, "widened": False}}
    assert all(c["stdin"] == "" for c in writes(fake_orch))  # nothing on stdin
    assert stored(fake_orch) == {**SETTINGS, "keep_days": 30, "max_mb": 512}


def test_current_value_read_failure_runs_without_a_guard(start_server, fake_orch, fake_session):
    (fake_orch.parent / "settings_exit").touch()
    srv = start_server(session=fake_session)
    assert post(srv, setting("insights.keep_days", "30"))[0] == 403  # no person: nothing runs
    assert writes(fake_orch) == []
    assert person(srv, setting("insights.keep_days", "30"))[0] == 200  # no --if-current: nothing observed
    argv = ["config", "set", "insights.keep_days", "30", "--json"]
    assert [c["args"] for c in writes(fake_orch)] == [argv]


def test_settings_read_env_is_the_human_env(start_server, fake_orch, fake_session, monkeypatch):
    for name in ("ORCH_DEV", "ORCH_AGENT", "CLAUDECODE"):
        monkeypatch.setenv(name, "1")
    srv = start_server(session=fake_session)
    assert person(srv, setting("insights.keep_days", "30"))[0] == 200
    reads = [c for c in calls(fake_orch) if c["args"] == ["record", "settings", "--json"]]
    assert reads
    for call in reads:
        assert not {"ORCH_DEV", "ORCH_AGENT", "CLAUDECODE"} & set(call["env"])


def test_read_fails_closed_without_human_env(start_server, fake_orch, fake_session, monkeypatch):
    def broken(root, orch_bin):
        raise actions.Unavailable("x")

    srv = start_server(session=fake_session)
    monkeypatch.setattr(actions, "human_env", broken)
    assert person(srv, setting("insights.keep_days", "30"))[0] == 503  # the read failed: nothing runs
    assert not writes(fake_orch)


@pytest.mark.parametrize(
    "code,status,text",
    [
        ("not_found", 422, "That ticket was not found."),
        ("not_available", 422, "The record could not be read. Nothing was deleted."),
        ("unavailable", 422, "The record could not be read. Nothing was deleted."),
        ("tampered", 422, "The record could not be read. Nothing was deleted."),
        ("invalid", 422, "That value is not allowed."),
        ("not_allowed", 422, "This was refused."),
        ("weird", 422, "That did not work."),
        (None, 422, "That did not work."),
    ],
)
def test_core_refusals_mapped(start_server, fake_orch, fake_session, code, status, text):
    refusal = {"error": "That ticket does not exist at /home/anna/.orch\nsecond line", "code": code}
    (fake_orch.parent / "refuse.json").write_text(json.dumps(refusal))
    srv = start_server(session=fake_session)
    answer, _, body = person(srv, delete())
    assert answer == status
    assert body.decode() == text
    assert len(writes(fake_orch)) == 1


def test_no_child_stderr_or_core_text_in_answers(start_server, fake_orch, fake_session):
    leak = 'Traceback (most recent call last):\n  File "/Users/anna/orch/x.py"\nhp1.secretproof.mac\n'
    (fake_orch.parent / "stderr.txt").write_text(leak)
    (fake_orch.parent / "refuse.json").write_text(
        json.dumps({"error": "boom at /Users/anna/x hp1.xxx", "code": "exploded"})
    )
    srv = start_server(session=fake_session)
    for body in (delete(), setting("insights.keep_days", "30")):
        code, _, text = person(srv, body)
        assert code == 422 and text.decode() == "That did not work."
    (fake_orch.parent / "refuse.json").write_text("not json at /Users/anna")
    code, _, text = person(srv, delete())
    assert code == 422 and text.decode() == "That did not work."


def test_timeout_after_a_write(start_server, fake_orch, fake_session, monkeypatch):
    # 504 without any claim about the outcome (L8)
    monkeypatch.setattr(actions, "WRITE_TIMEOUT", 1)
    (fake_orch.parent / "pause").write_text("3")
    srv = start_server(session=fake_session)
    code, _, text = person(srv, setting("insights.keep_days", "30"))
    assert code == 504 and text.decode() == "That took too long. Reload to see the current setting."


def test_external_change_in_between_is_changed(start_server, fake_orch, fake_session):
    (fake_orch.parent / "external.json").write_text(json.dumps({"keep_days": 30}))
    srv = start_server(session=fake_session)
    code, _, text = person(srv, setting("insights.keep_days", "365"))
    assert code == 409 and text.decode() == "This changed in the meantime. Reloaded."
    assert stored(fake_orch)["keep_days"] == 30


def test_concurrent_posts_are_serialized(start_server, fake_orch, fake_session):
    (fake_orch.parent / "pause").write_text("0.4")
    srv = start_server(session=fake_session)
    secret = link(srv)
    results = []

    def click(key, value):
        results.append(post(srv, setting(key, value), cookie=True, secret=secret)[0])

    threads = [
        threading.Thread(target=click, args=("insights.keep_days", "30")),
        threading.Thread(target=click, args=("insights.max_mb", "512")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert results == [200, 200]
    order = [c["args"][:2] for c in calls(fake_orch)]
    read, write = ["record", "settings"], ["config", "set"]
    assert order == [read, write, read, write]  # one click's read and write never interleave
    assert stored(fake_orch) == {**SETTINGS, "keep_days": 30, "max_mb": 512}


@pytest.mark.parametrize("state", ["off_by_admin", "not_connected", None])
def test_admin_lock_refuses_sharing_on(start_server, fake_orch, fake_session, answer, state):
    if state is None:
        (fake_orch.parent / "exit").touch()
    else:
        answer["sharing"]["counts"] = state
        (fake_orch.parent / "answer.json").write_text(json.dumps(answer))
    srv = start_server(session=fake_session)
    code, _, text = person(srv, setting("insights.share_counts", "on"))
    assert code == 409
    expected = {"off_by_admin": "Switched off by your admin.", "not_connected": "Not connected to an admin."}
    assert text.decode() == expected.get(state, "Sharing could not be read. Nothing was changed.")
    assert writes(fake_orch) == []
    assert person(srv, setting("insights.share_counts", "off"))[0] == 200  # turning it off stays possible


def test_act_and_session_both_refuse_a_missing_sec_fetch_site(start_server, fake_orch, fake_session):
    """One shared rule (_site_refusal): an absent Sec-Fetch-Site is refused on /api/act like on /session."""
    srv = start_server(session=fake_session)
    secret = link(srv)
    assert post_bare(srv, setting("insights.keep_days", "30")) == 403
    assert post_bare(srv, {"token": FakeSession.token}, path="/session") == 403
    assert writes(fake_orch) == []
    assert post(srv, setting("insights.share_counts", "off"), cookie=True, secret=secret)[0] == 200


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
    cookie = {"Cookie": f"orch_page_insights_{srv.server_address[1]}=good-cookie-value"}
    assert json.loads(request(srv, "/api/settings", headers=cookie)[2])["can_act"] is False  # cookie alone
    view = json.loads(request(srv, "/api/settings", headers={**cookie, "X-Orch-Page": link(srv)})[2])
    assert view["can_act"] is True
    (fake_orch.parent / "tickets_exit").touch()
    assert json.loads(request(srv, "/api/settings")[2])["tickets"]["error"] == TICKETS_ERROR
    (fake_orch.parent / "settings_exit").touch()
    assert json.loads(request(srv, "/api/settings")[2]) == {"error": ERROR}
    assert request(srv, "/api/settings", headers={"Host": "evil.example:1"})[0] == 403


SAME_SITE = {"Sec-Fetch-Site": "same-origin"}


def test_session_post(start_server, fake_session):
    token = {"token": FakeSession.token}
    plain = start_server()
    assert post(plain, token, path="/session", headers=SAME_SITE)[0] == 403
    srv = start_server(session=fake_session)
    assert post(srv, {"token": "wrong-token-abcdefghijkl"}, path="/session", headers=SAME_SITE)[0] == 403
    forwarded = {**SAME_SITE, "X-Forwarded-For": "1.2.3.4"}
    assert post(srv, token, path="/session", headers=forwarded)[0] == 403
    assert srv.page_secret is None  # no secret before a launch token was spent
    code, headers, body = post(srv, token, path="/session", headers=SAME_SITE)
    assert code == 200 and headers["Content-Type"] == "application/json"
    assert headers["Set-Cookie"] == (
        f"orch_page_insights_{srv.server_address[1]}=good-cookie-value; HttpOnly; SameSite=Strict; Path=/"
    )
    secret = json.loads(body)["secret"]
    assert secret == srv.page_secret and len(secret) >= 40
    assert post(srv, token, path="/session", headers={"Sec-Fetch-Site": "none"})[0] == 200


@pytest.mark.parametrize(
    "headers",
    [
        {
            "Sec-Fetch-Site": ""
        },  # empty/absent: refused too (truly absent: test_act_and_session_both_refuse...)
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Sec-Fetch-Site": "same-origin", "Content-Type": "text/plain"},
        {"Sec-Fetch-Site": "same-origin", "Content-Type": "application/x-www-form-urlencoded"},
        {"Sec-Fetch-Site": "same-origin", "Origin": "http://evil.example"},
    ],
)
def test_session_post_needs_same_origin_and_json(start_server, fake_session, headers):
    srv = start_server(session=fake_session)
    code, response, body = post(srv, {"token": FakeSession.token}, path="/session", headers=headers)
    assert code == 403 and "Set-Cookie" not in response
    assert srv.page_secret is None and b"secret" not in body


def test_session_post_without_origin_refused(start_server, fake_session):
    srv = start_server(session=fake_session)
    port = srv.server_address[1]
    raw = json.dumps({"token": FakeSession.token}).encode()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json", **SAME_SITE}
    conn.request("POST", "/session", body=raw, headers=headers)
    response = conn.getresponse()
    assert response.status == 403 and response.getheader("Set-Cookie") is None
    conn.close()
    assert srv.page_secret is None


def test_settings_target_is_the_core_form_byte_identical():
    from orch.config import insights_target

    from orch_insights.settings import KEYS

    for key, (_, allowed) in KEYS.items():
        for value in allowed:
            assert insights_target(key, value) == f"{key}={value}"


def test_no_insights_page_server_in_core_is_watch_only(start_server, fake_orch, monkeypatch):
    import subprocess

    import orch.pagesession

    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs.get("input"), kwargs.get("stdin")))
        return subprocess.CompletedProcess(argv, 2, "{}", "")

    monkeypatch.setattr(orch.pagesession, "SERVERS", ("focus", "dashboard"))
    monkeypatch.setattr(actions, "_run", run)
    srv = start_server(orch_bin=None)
    assert srv.session is None
    assert request(srv, "/")[0] == 200
    code, _, text = post(srv, delete(), cookie=True)
    assert code == 403 and text.decode() == "Open Insights from the dashboard on this computer to do this."
    assert seen == []  # no page session: nothing ran
    assert post(srv, {"token": FakeSession.token}, path="/session", headers=SAME_SITE)[0] == 403
    assert calls(fake_orch) == []


def test_run_op_without_the_session_runs_nothing_and_with_it_runs_once(ws, fake_orch):
    with pytest.raises(actions.NeedsPerson):
        actions.run_op(ws, str(fake_orch), "record.delete_detail", {"ticket": "t_abc123"})
    with pytest.raises(actions.NeedsPerson):
        actions.run_op(ws, str(fake_orch), "settings.set", {"key": "insights.keep_days", "value": "30"})
    assert calls(fake_orch) == []
    code, _, _ = actions.run_op(
        ws, str(fake_orch), "record.delete_detail", {"ticket": "t_abc123"}, session=True
    )
    assert code == 200
    assert [c["args"] for c in calls(fake_orch)] == [["record", "delete-detail", "t_abc123", "--json"]]
    assert calls(fake_orch)[0]["stdin"] == ""  # a plain person action: nothing on stdin


def test_human_env_refuses_without_the_list(ws, monkeypatch):
    import orch.adapters

    def broken(environ):
        raise OSError("bad adapter")

    monkeypatch.setattr(orch.adapters, "human_environ", broken)
    with pytest.raises(actions.Unavailable):
        actions.human_env(ws, "/x/orch")


# -- the real core page session (L10): the fake must not be kinder than PageSession ----------------------------


@pytest.fixture
def real_session(ws):
    pagesession = pytest.importorskip("orch.pagesession")
    try:
        session = pagesession.PageSession(ws, "insights")
    except ValueError:  # this core has no Insights page server yet: the same class, for Focus (test only)
        session = pagesession.PageSession(ws, "focus")
    session.active = True  # a test run inside an agent tool would make it watch-only
    session.cookie = "real-cookie-value-abcdefghijklmnopqrstuvwxyz"
    return session


def cookie_headers(port, cookie, **extra):
    return {"Host": f"127.0.0.1:{port}", "Cookie": cookie, "X-Orch-Page": SESSION_SECRET[0], **extra}


SESSION_SECRET = [
    ""
]  # the page secret of the session under test (set by test_cookie_parsing_matches_the_core)


@pytest.mark.parametrize("session_kind", ["real", "fake"])
def test_cookie_parsing_matches_the_core(real_session, session_kind):
    session = real_session if session_kind == "real" else FakeSession()
    SESSION_SECRET[0] = session.secret
    value = session.cookie
    name = session.cookie_name(8431)
    good = [f"{name}={value}", f"a=b; {name}={value}", f'{name}="{value}"; x=y']
    bad = [
        f"x{name}={value}",
        f"{name}_x={value}",
        f"a={name}={value}",
        f"{name}={value}x",
        f"orch_page={value}",  # the old shared name is no session any more
        f"{session.cookie_name(8432)}={value}",  # another port's cookie
        f"{name}=wrong",
        "",
    ]
    for cookie in good:
        assert session.can_act(cookie_headers(8431, cookie), 8431), cookie
    for cookie in bad:
        assert not session.can_act(cookie_headers(8431, cookie), 8431), cookie
    good_cookie = f"{name}={value}"
    assert not session.can_act(cookie_headers(8432, good_cookie), 8431)  # wrong Host port
    assert not session.can_act({"Host": "evil.example:8431", "Cookie": good_cookie}, 8431)
    for proxy in ({"X-Forwarded-For": "10.0.0.1"}, {"X-Forwarded-Host": "x"}, {"Forwarded": "for=x"}):
        assert not session.can_act(cookie_headers(8431, good_cookie, **proxy), 8431)


def test_real_session_cookie_alone_cannot_act(start_server, fake_orch, real_session):
    srv = start_server(session=real_session)
    srv.page_secret = "s" * 43  # as if /session succeeded; the request below does not send it
    cookie = {"Cookie": f"{real_session.cookie_name(srv.server_address[1])}={real_session.cookie}"}
    for body in (setting("insights.keep_days", "365"), delete()):
        code, _, text = post(srv, body, headers=cookie)
        assert code == 403 and text.decode() == actions.PERSON
    assert writes(fake_orch) == [] and stored(fake_orch) == SETTINGS


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
    assert re.search(r'id="settings-link"[^>]*>.*?<span id="settings-label">Settings<', html, re.DOTALL)
    assert "settings.js" in html
    # the ticket id goes in the POST body only, never on screen
    assert "entry.ticket" in js and not re.search(r"node\([^)]*entry\.ticket", js)
    assert "confirm" not in json.dumps(delete())


def test_page_secret_memory_only_and_unlinked_message():
    js = PACKAGE.joinpath("web", "settings.js").read_text()
    html = PACKAGE.joinpath("web", "index.html").read_text()
    message = "This page could not be linked to your session. Open Insights again from the dashboard on this computer."
    assert message in js and 'id="session-note"' in html
    assert "note.textContent = UNLINKED" in js and "innerHTML" not in js
    assert "response.status !== 200" in js
    for store in ("localStorage", "sessionStorage", "document.cookie", "location.hash =", "searchParams"):
        assert store not in js
    assert "'X-Orch-Page': pageSecret" in js
    # every act and the settings read carry the header; after any refusal the settings are read again
    assert js.count("headers: headers(") == 2
    assert js.count("await load();") >= 3


def test_settings_js_served(server):
    code, headers, body = request(server, "/web/settings.js")
    assert code == 200 and headers["Content-Type"] == "text/javascript"
    assert body == PACKAGE.joinpath("web", "settings.js").read_bytes()


def test_success_answer_is_built_from_parsed_fields_only():
    from orch_insights.actions import _clean_success

    out = _clean_success(
        {
            "insights.keep_days": 90,
            "changed": True,
            "widened": False,
            "note": "/Users/x/secret",
            "evil": {"a": 1},
        }
    )
    assert out == {"insights.keep_days": 90, "changed": True, "widened": False}
    assert _clean_success({"deleted": 2, "ticket": "../x"}) == {"deleted": 2}
    assert _clean_success("text") is None


def test_lock_wait_gives_busy(monkeypatch):
    from orch_insights import actions

    monkeypatch.setattr(actions, "LOCK_WAIT", 0.05)
    actions._LOCK.acquire()
    try:
        code, text, _ = actions.run_op(
            Path("/nonexistent"),
            None,
            "settings.set",
            {"key": "insights.keep_days", "value": "30"},
            session=True,
        )
    finally:
        actions._LOCK.release()
    assert code == 503 and text == actions.BUSY


def test_deadline_stops_a_late_child():
    from orch_insights import actions

    code, _, _ = actions.orch(Path("/nonexistent"), "/bin/true", ["x"], deadline=0)
    assert code == 124


# ---- #539: /session cannot be used by another local page; no CORS; the secret never leaks ----------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"Origin": "http://127.0.0.1:1"},  # another loopback port
        {"Origin": "http://localhost:1"},
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Host": "evil.example:1"},
        {"Host": "127.0.0.1:1"},
    ],
    ids=lambda e: ",".join(f"{k}={v}" for k, v in e.items()),
)
def test_session_refused_for_foreign_origin_or_wrong_host(start_server, fake_session, extra):
    srv = start_server(session=fake_session)
    token = {"token": FakeSession.token}
    code, headers, body = post(srv, token, path="/session", headers={**SAME_SITE, **extra})
    # a request without Origin is covered below; here Origin is the server's own unless overridden
    assert code == 403 and b"secret" not in body and "Set-Cookie" not in headers
    assert not any(k.lower().startswith("access-control-") for k in headers)
    assert srv.page_secret is None


def test_session_refused_without_origin_and_never_cors(start_server, fake_session):
    srv = start_server(session=fake_session)
    port = srv.server_address[1]
    raw = json.dumps({"token": FakeSession.token}).encode()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(
        "POST",
        "/session",
        body=raw,
        headers={"Host": f"127.0.0.1:{port}", "Content-Type": "application/json", **SAME_SITE},
    )
    response = conn.getresponse()
    response.read()
    assert response.status == 403
    assert not any(k.lower().startswith("access-control-") for k, _ in response.getheaders())
    secret = link(srv)
    for path in ("/", "/api/settings", "/api/overview"):
        for method in ("GET", "OPTIONS"):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request(
                method,
                path,
                headers={
                    "Host": f"127.0.0.1:{port}",
                    "Origin": "https://evil.example",
                    "X-Orch-Page": secret,
                },
            )
            response = conn.getresponse()
            data = response.read()
            assert secret.encode() not in data and response.getheader("Location") is None
            assert not any(k.lower().startswith("access-control-") for k, _ in response.getheaders())
