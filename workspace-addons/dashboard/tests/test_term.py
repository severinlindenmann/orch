"""fb17: the live helper session in the browser. A real tmux on a private socket stands in for the helper."""

import functools
import json
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from orch_dashboard import termsession
from orch_dashboard.server import make_server

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="needs tmux")

SOCK, TID = (
    "orch-0badf00d",
    "t_term0001",
)  # SOCK is made new for each test (parallel workers must not share a tmux server)


def tm(*args):
    return subprocess.run(["tmux", "-L", SOCK, *args], capture_output=True, text=True, check=False)


@pytest.fixture
def helper(tmp_path):
    """A 'helper': a shell loop in a tmux session on a private socket, plus a fake `orch` that names it."""
    global SOCK
    SOCK = "orch-" + secrets.token_hex(4)
    tm(
        "new-session",
        "-d",
        "-x",
        "80",
        "-y",
        "24",
        "-s",
        TID,
        "--",
        "sh",
        "-c",
        "echo hello-from-helper; cat",
    )
    state = tmp_path / "status.json"
    state.write_text(
        json.dumps({"running": True, "claim": {"run": "r_1", "tmux": {"socket": SOCK, "session": TID}}})
    )
    orch = tmp_path / "orch"
    orch.write_text(
        f"#!{sys.executable}\nimport sys\nprint(open({str(state)!r}).read()) if sys.argv[1:3] == ['run', 'status'] else sys.exit(2)\n"
    )
    orch.chmod(0o755)
    time.sleep(0.4)
    yield str(orch), state
    tm("kill-server")


def screen(root, orch, tid=TID):
    return termsession.snapshot(root, orch, tid)


def test_snapshot_shows_the_live_screen(helper, tmp_path):
    orch, _ = helper
    snap = screen(tmp_path, orch)
    assert snap["state"] == "live" and "hello-from-helper" in snap["screen"]
    assert (snap["cols"], snap["rows"]) == (80, 24) and snap["scrolled"] is False


def test_no_session_says_why(helper, tmp_path):
    orch, state = helper
    state.write_text(json.dumps({"running": True, "claim": {"run": "r_1"}}))
    assert screen(tmp_path, orch)["state"] == "oneshot"
    state.write_text(json.dumps({"running": False}))
    assert screen(tmp_path, orch)["state"] == "none"
    assert screen(tmp_path, orch, "../etc")["state"] == "none"


def test_names_come_from_the_core_claim_and_must_have_core_shape(helper, tmp_path):
    orch, state = helper
    state.write_text(
        json.dumps({"running": True, "claim": {"tmux": {"socket": "../../tmp/evil", "session": TID}}})
    )
    assert screen(tmp_path, orch)["state"] == "none"
    state.write_text(
        json.dumps({"running": True, "claim": {"tmux": {"socket": SOCK, "session": "t_other0002"}}})
    )
    assert screen(tmp_path, orch)["state"] == "none"


def test_typing_reaches_the_session(helper, tmp_path):
    orch, _ = helper
    assert termsession.keys(tmp_path, orch, TID, [{"t": "-typed words"}, {"k": "Enter"}]) == (200, "{}")
    time.sleep(0.4)
    assert "-typed words" in screen(tmp_path, orch)["screen"]


@pytest.mark.parametrize(
    "items",
    [
        [],
        "x",
        [{"k": "F12"}],
        [{"t": ""}],
        [{"t": "a" * 2001}],
        [{"t": "a", "k": "Enter"}],
        [{"k": "Enter"}] * 41,
        [{"k": "C-b"}],
        [{"t": "a\x00"}],
    ],
)
def test_typing_refuses_what_is_not_on_the_list(helper, tmp_path, items):
    orch, _ = helper
    assert termsession.keys(tmp_path, orch, TID, items)[0] == 400


def test_typing_without_a_live_session_is_refused(helper, tmp_path):
    orch, state = helper
    state.write_text(json.dumps({"running": False}))
    assert termsession.keys(tmp_path, orch, TID, [{"k": "Enter"}])[0] == 409


class Person:
    """The person's dashboard session (cookie + page secret): the real check is PageSession.can_act."""

    def __init__(self, ok):
        self.ok = ok

    def can_act(self, headers, port):
        return self.ok and headers.get("X-Orch-Page") == "secret"

    def authed(self, headers, port):
        return self.can_act(headers, port)


def typing_on(tmp_path, on=True):
    """[focus] session_typing in the workspace's config file (a plain setting; off by default)."""
    (tmp_path / ".orch").mkdir(exist_ok=True)
    (tmp_path / ".orch" / "config.toml").write_text(f"[focus]\nsession_typing = {str(on).lower()}\n")


def serve(tmp_path, orch, session):
    srv = make_server(tmp_path, 0, orch_bin=orch)
    srv.RequestHandlerClass = functools.partial(srv.RequestHandlerClass, session=session)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def call(url, body=None, headers=None):
    req = urllib.request.Request(
        url, data=body, headers=headers or {}, method="POST" if body is not None else "GET"
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def post(base, items, secret="secret"):
    h = {"Content-Type": "application/json", "Origin": base, "X-Orch-Page": secret}
    return call(base + "/api/term/keys", json.dumps({"ticket": TID, "items": items}).encode(), h)


def test_the_screen_is_served_read_only_and_typing_needs_the_persons_session(helper, tmp_path):
    orch, _ = helper
    (tmp_path / ".orch" / "tickets").mkdir(parents=True)
    typing_on(tmp_path)
    srv, base = serve(tmp_path, orch, Person(True))
    try:
        code, body = call(base + "/api/term?ticket=" + TID)
        assert code == 200 and "hello-from-helper" in json.loads(body)["screen"]
        assert json.loads(body)["typing_allowed"] is True
        assert post(base, [{"t": "ok"}, {"k": "Enter"}])[0] == 200
        assert post(base, [{"t": "no"}], secret="wrong")[0] == 403  # a script without the page secret
        code, _ = call(
            base + "/api/term/keys",
            json.dumps({"ticket": TID, "items": [{"k": "Enter"}]}).encode(),
            {"Content-Type": "application/json"},
        )
        assert code == 403  # no Origin: not a page
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_watch_only_server_never_types(helper, tmp_path):
    orch, _ = helper
    (tmp_path / ".orch" / "tickets").mkdir(parents=True)
    srv, base = serve(tmp_path, orch, None)
    try:
        assert post(base, [{"k": "Enter"}])[0] == 403
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("text", ["a;", ";", "a\\;", "x;y"])
def test_a_semicolon_stays_literal(helper, tmp_path, text):
    orch, _ = helper
    assert termsession.keys(tmp_path, orch, TID, [{"t": text}])[0] == 200
    time.sleep(0.4)
    assert text in screen(tmp_path, orch)["screen"]


@pytest.mark.parametrize("text", ["a\x1b[31m", "x\x07", "y\x9b", "z\x7f"])
def test_control_characters_are_refused_but_tab_and_newline_are_not(helper, tmp_path, text):
    orch, _ = helper
    assert termsession.keys(tmp_path, orch, TID, [{"t": text}])[0] == 400
    assert termsession.keys(tmp_path, orch, TID, [{"t": "a\tb\n"}])[0] == 200


def test_waiting_input_needs_a_quiet_screen_and_a_question():
    k = ("orch-0badf00d", "t_wait0001")
    ask = "working\nDo you want to proceed? (y/n)"
    assert termsession.waiting_input(k, ask, 100.0) is False  # first sight
    assert termsession.waiting_input(k, ask, 110.0) is False  # not quiet long enough
    assert termsession.waiting_input(k, ask, 125.0) is True
    assert termsession.waiting_input(k, ask + "!", 130.0) is False  # the screen changed
    k2 = ("orch-0badf00d", "t_wait0002")
    termsession.waiting_input(k2, "building...", 1.0)
    assert termsession.waiting_input(k2, "building...", 60.0) is False  # quiet but not a question


def test_the_screen_route_is_same_origin_and_not_cached(helper, tmp_path):
    orch, _ = helper
    (tmp_path / ".orch" / "tickets").mkdir(parents=True)
    srv, base = serve(tmp_path, orch, Person(True))
    try:
        req = urllib.request.Request(base + "/api/term?ticket=" + TID)
        with urllib.request.urlopen(req) as r:
            assert r.headers["Cache-Control"] == "no-store"
        req = urllib.request.Request(
            base + "/api/term?ticket=" + TID, headers={"Sec-Fetch-Site": "cross-site"}
        )
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 403
    finally:
        srv.shutdown()
        srv.server_close()


def test_typing_is_refused_server_side_when_the_setting_is_off(helper, tmp_path):
    orch, _ = helper
    (tmp_path / ".orch" / "tickets").mkdir(parents=True)
    srv, base = serve(tmp_path, orch, Person(True))  # no config: session_typing is off
    try:
        code, body = call(base + "/api/term?ticket=" + TID)
        assert code == 200 and json.loads(body)["typing_allowed"] is False
        code, text = post(base, [{"t": "nope"}, {"k": "Enter"}])
        assert code == 403
        assert (
            text.decode()
            == "Typing into the helper's screen is off. Turn on 'Let me type' in Settings to allow it."
        )
        typing_on(tmp_path, False)
        assert post(base, [{"k": "Enter"}])[0] == 403
        typing_on(tmp_path)  # turned on: the same call goes through, and the answer says so
        assert json.loads(call(base + "/api/term?ticket=" + TID)[1])["typing_allowed"] is True
        assert post(base, [{"k": "Enter"}])[0] == 200
    finally:
        srv.shutdown()
        srv.server_close()
