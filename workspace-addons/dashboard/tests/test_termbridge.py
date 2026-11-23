"""ORCH-743: the terminal bridge. A real tmux on a private socket stands in for the helper, as in test_term.py."""

import base64
import functools
import http.client
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time

import pytest

from orch_dashboard import termbridge, termsession
from orch_dashboard.server import make_server

pytestmark = [
    pytest.mark.skipif(shutil.which("tmux") is None, reason="needs tmux"),
    # the clock CI job runs every add-on suite under libfaketime, where a real tmux server hangs (as test_term.py)
    pytest.mark.skipif(
        "faketime" in os.environ.get("LD_PRELOAD", ""),
        reason="a real tmux hangs under libfaketime; runs in addons.yml",
    ),
]

TID = "t_term0001"
SOCK = ["orch-00000000"]


def tm(*args):
    return subprocess.run(["tmux", "-L", SOCK[0], *args], capture_output=True, text=True, check=False)


def fake_orch(tmp_path, status: dict, sessions: dict | None = None) -> str:
    """A fake `orch`: `run status` answers the claim, `session list` the sessions without a ticket."""
    (tmp_path / "status.json").write_text(json.dumps(status))
    (tmp_path / "sessions.json").write_text(json.dumps(sessions or {"sessions": []}))
    orch = tmp_path / "orch"
    orch.write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        f"st = json.load(open({str(tmp_path / 'status.json')!r}))\n"
        f"se = json.load(open({str(tmp_path / 'sessions.json')!r}))\n"
        "a = sys.argv[1:3]\n"
        "print(json.dumps(st)) if a == ['run', 'status'] else print(json.dumps(se)) if a == ['session', 'list'] "
        "else sys.exit(2)\n"
    )
    orch.chmod(0o755)
    return str(orch)


@pytest.fixture
def helper(tmp_path, monkeypatch):
    """A 'helper' (a shell that prints what it gets) in a tmux session on a private socket."""
    SOCK[0] = "orch-" + secrets.token_hex(4)
    monkeypatch.setattr(termbridge, "LINGER", 0.3)
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
        "echo hello-from-helper; cat -v",
    )
    orch = fake_orch(tmp_path, {"running": True, "claim": {"tmux": {"socket": SOCK[0], "session": TID}}})
    (tmp_path / ".orch" / "tickets").mkdir(parents=True)
    time.sleep(0.4)
    yield orch
    for w in list(termbridge._WATCHES.values()):
        w.close()
    tm("kill-server")


class Person:
    def __init__(self, ok=True):
        self.ok = ok

    def can_act(self, headers, port):
        return self.ok and headers.get("X-Orch-Page") == "secret"

    def authed(self, headers, port):
        return self.can_act(headers, port)

    def cookie_ok(self, headers, port):
        return self.ok

    revoked = False


def typing_on(root, on=True):
    (root / ".orch").mkdir(exist_ok=True)
    (root / ".orch" / "config.toml").write_text(f"[focus]\nsession_typing = {str(on).lower()}\n")


@pytest.fixture
def server(tmp_path, helper):
    made = []

    def start(person=None, remote=False):
        srv = make_server(tmp_path, 0, orch_bin=helper, remote=("127.0.0.1", 0) if remote else None)
        srv.RequestHandlerClass = functools.partial(srv.RequestHandlerClass, session=person or Person())
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        if srv.remote_server is not None:
            srv.remote_server.RequestHandlerClass = srv.RequestHandlerClass
            threading.Thread(target=srv.remote_server.serve_forever, daemon=True).start()
        made.append(srv)
        return srv

    yield start
    for srv in made:
        if srv.remote_server is not None:
            srv.remote_server.shutdown()
        srv.shutdown()
        srv.server_close()


class Stream:
    """One page watching: the events of GET /api/term/stream, read in the background."""

    def __init__(self, port, tid=TID, host=None):
        self.conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        self.conn.request(
            "GET", f"/api/term/stream?ticket={tid}", headers={"Host": host or f"127.0.0.1:{port}"}
        )
        self.sock = self.conn.sock  # the response takes it over (HTTP/1.0: the server closes the connection)
        self.resp = self.conn.getresponse()
        self.events: queue.Queue = queue.Queue()
        self.seen = b""
        if self.resp.status == 200:
            threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        name = None
        try:
            for raw in iter(self.resp.readline, b""):
                line = raw.decode().rstrip("\n")
                if line.startswith("event: "):
                    name = line[7:]
                elif line.startswith("data: ") and name:
                    self.events.put((name, line[6:]))
                    name = None
        except OSError:
            pass

    def next(self, kind=None, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                name, data = self.events.get(timeout=max(0.01, end - time.monotonic()))
            except queue.Empty:
                break
            if name == "out":
                self.seen += base64.b64decode(data)
            if kind is None or name == kind:
                return name, data
        raise AssertionError(f"no {kind} event")

    def until(self, text: bytes, timeout=5.0) -> bool:
        end = time.monotonic() + timeout
        while text not in self.seen and time.monotonic() < end:
            try:
                self.next("out", timeout=max(0.05, end - time.monotonic()))
            except AssertionError:
                break
        return text in self.seen

    def close(self):
        import socket

        try:
            self.sock.shutdown(socket.SHUT_RDWR)  # as a closed tab
        except (OSError, AttributeError):
            pass
        self.conn.close()


def post(port, path, body, secret="secret", origin=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {
        "Content-Type": "application/json",
        "Origin": origin or f"http://127.0.0.1:{port}",
        "X-Orch-Page": secret,
    }
    if host:
        h["Host"] = host
    conn.request("POST", path, json.dumps(body).encode(), h)
    r = conn.getresponse()
    out = (r.status, r.read())
    conn.close()
    return out


def _tmux_version() -> tuple[int, int]:
    out = subprocess.run(["tmux", "-V"], check=False, capture_output=True, text=True).stdout
    m = re.search(r"(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.05)
    return cond()


def clients():
    return [ln for ln in tm("list-clients", "-F", "#{client_flags}").stdout.splitlines() if ln]


def test_unescape_turns_tmux_octal_back_into_bytes():
    assert termbridge._unescape(rb"a\033[1mb\134c\015\012") == b"a\x1b[1mb\\c\r\n"
    assert termbridge._unescape("ä€".encode()) == "ä€".encode()


def test_a_flag_an_older_tmux_does_not_know_reads_0(helper):
    # bracket_paste_flag came in tmux 3.7; CI's Ubuntu ships 3.4, where a bare unknown flag reads nothing
    out = tm(
        "display-message", "-p", "-t", f"={TID}:", termbridge._META.replace("bracket_paste", "no_such")
    ).stdout
    assert termbridge.draw(b"x\n", out.strip().encode()) is not None


def test_a_notice_inside_an_answer_block_is_output_not_screen():
    w = termbridge.Watch("s", "t")
    w.pane = "%1"
    assert w._notice(b"%output %1 hi\\015") and w.chunks[-1][1:] == ("out", b"hi\r")
    assert not w._notice(b"plain line from capture-pane")


def test_a_page_gets_the_screen_then_every_byte_and_typing_reaches_the_helper(helper, server, tmp_path):
    typing_on(tmp_path)
    port = server().server_address[1]
    s = Stream(port)
    assert s.resp.status == 200 and s.resp.getheader("Content-Type") == "text/event-stream"
    hello = json.loads(s.next("hello")[1])
    assert (
        hello["typing_allowed"] is True
        and len(hello["page"]) >= 16
        and set(hello) == {"typing_allowed", "page"}
    )
    snap = json.loads(s.next("screen")[1])
    assert (snap["cols"], snap["rows"]) == (80, 24)
    assert b"hello-from-helper" in base64.b64decode(snap["data"])
    # raw terminal input: text, a semicolon at the end, an arrow key, Ctrl+C is not sent (cat would end)
    assert post(port, "/api/term/input", {"ticket": TID, "data": "typed äb;\x1b[A\r"}) == (200, b"{}")
    assert s.until(b"typed \xc3\xa4b;^[[A")
    assert "typed äb;^[[A" in tm("capture-pane", "-p", "-t", f"={TID}:").stdout
    s.close()


def test_opening_a_watch_never_changes_the_helpers_size_and_two_pages_share_one_client(helper, server):
    port = server().server_address[1]
    a, b = Stream(port), Stream(port)
    a.next("screen"), b.next("screen")
    assert len(clients()) == 1 and "control-mode" in clients()[0] and "ignore-size" in clients()[0]
    assert "read-only" not in clients()[0]  # a read-only client would make orch's own send-keys fail
    assert (
        tm("display-message", "-p", "-t", f"={TID}:", "#{window_width}x#{window_height}").stdout.strip()
        == "80x24"
    )
    tm("send-keys", "-t", f"={TID}:", "-l", "for both")  # orch's own typing still works while pages watch
    tm("send-keys", "-t", f"={TID}:", "Enter")
    assert a.until(b"for both") and b.until(b"for both")
    a.close(), b.close()


def test_the_watch_closes_a_while_after_the_last_page_left(helper, server):
    port = server().server_address[1]
    s = Stream(port)
    s.next("screen")
    assert wait(lambda: len(clients()) == 1)
    s.close()
    assert wait(lambda: not clients() and not termbridge._WATCHES, timeout=8)
    assert termbridge._PAGES[0] == 0


def test_resize_changes_the_window_and_every_page_hears_it(helper, server, tmp_path):
    typing_on(tmp_path)
    port = server().server_address[1]
    s = Stream(port)
    s.next("screen")
    assert post(port, "/api/term/size", {"ticket": TID, "cols": 100, "rows": 30}) == (200, b"{}")
    assert json.loads(s.next("size")[1]) == {"cols": 100, "rows": 30}
    assert (
        tm("display-message", "-p", "-t", f"={TID}:", "#{window_width}x#{window_height}").stdout.strip()
        == "100x30"
    )
    assert (
        "manual" not in tm("show-window-options", "-t", f"={TID}:", "window-size").stdout
    )  # back to tmux's rule
    for bad in (
        {"cols": 5, "rows": 30},
        {"cols": 100, "rows": 9999},
        {"cols": "100", "rows": 30},
        {"cols": True, "rows": 30},
    ):
        assert post(port, "/api/term/size", {"ticket": TID, **bad})[0] == 400
    s.close()


def test_typing_needs_the_person_the_setting_and_a_page_that_watches(helper, server, tmp_path):
    port = server().server_address[1]
    s = Stream(port)
    assert json.loads(s.next("hello")[1])["typing_allowed"] is False  # watching only by default
    s.next("screen")
    code, body = post(port, "/api/term/input", {"ticket": TID, "data": "x"})
    assert code == 403 and b"Typing into the helper's screen is off" in body
    typing_on(tmp_path)
    assert post(port, "/api/term/input", {"ticket": TID, "data": "x"}, secret="wrong")[0] == 403  # a script
    assert post(port, "/api/term/input", {"ticket": TID, "data": "x"}, origin="http://evil.example")[0] == 403
    assert (
        post(port, "/api/term/input", {"ticket": "t_other0002", "data": "x"})[0] == 409
    )  # nobody watches it
    assert post(port, "/api/term/input", {"ticket": TID, "data": ""})[0] == 400
    assert post(port, "/api/term/input", {"ticket": TID, "data": "x", "more": 1})[0] == 400
    assert post(port, "/api/term/input", {"ticket": TID, "data": "x" * (termbridge.MAX_INPUT + 1)})[0] == 400
    s.close()
    assert wait(lambda: not termbridge._WATCHES, timeout=8)
    assert post(port, "/api/term/input", {"ticket": TID, "data": "x"})[0] == 409  # the page left


def test_the_sign_in_is_the_only_check_also_from_another_computer(helper, server, tmp_path):
    """R4.1a (owner's answer on ORCH-743): no check of this computer; the port for other computers works
    after the sign-in, and is refused without it."""
    typing_on(tmp_path)
    srv = server(remote=True)
    other = srv.remote_server.server_address[1]
    s = Stream(other, host="my-machine.example:80")
    assert s.resp.status == 200
    s.next("screen")
    far = "my-machine.example:80"
    assert (
        post(other, "/api/term/input", {"ticket": TID, "data": "far\r"}, origin="http://" + far, host=far)[0]
        == 200
    )
    assert wait(lambda: "far" in tm("capture-pane", "-p", "-t", f"={TID}:").stdout)
    s.close()
    srv2 = server(Person(False), remote=True)
    out = Stream(srv2.remote_server.server_address[1], host="my-machine.example:80")
    assert out.resp.status in (401, 403)
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", f"/api/term/stream?ticket={TID}", headers={"Sec-Fetch-Site": "cross-site"})
    assert conn.getresponse().status == 403  # another website's page


def test_a_session_that_is_not_there_says_why_and_one_that_ends_says_so(helper, server, tmp_path):
    port = server().server_address[1]
    s = Stream(port, tid="../etc")
    s.next("hello")
    assert json.loads(s.next("end")[1]) == {"state": "none"}
    s = Stream(port)
    s.next("screen")
    tm("kill-session", "-t", f"={TID}:")
    assert json.loads(s.next("end")[1]) == {"state": "none"}
    assert wait(lambda: not termbridge._WATCHES)


def test_too_many_pages_are_refused(helper, server, monkeypatch):
    monkeypatch.setattr(termbridge, "MAX_PAGES", 1)
    port = server().server_address[1]
    a = Stream(port)
    a.next("screen")
    b = Stream(port)
    assert b.resp.status == 503
    a.close()


def test_a_long_paste_goes_in_parts_and_nul_is_ctrl_space(helper, monkeypatch):
    sent = []
    w = termbridge.Watch(SOCK[0], TID)
    w.pages, w.pane = 1, "%0"
    termbridge._WATCHES[(SOCK[0], TID)] = w
    monkeypatch.setattr(
        termbridge, "_tmux", lambda sock, *a, **k: sent.append(a) or subprocess.CompletedProcess(a, 0)
    )
    assert termbridge.type_text(TID, "a" * (termbridge.PART * 2 + 1) + "\x00;") == (200, "{}")
    keys = [a[3:] for a in sent]
    assert [len(k[-1]) for k in keys[:3]] == [termbridge.PART, termbridge.PART, 1]
    assert keys[3] == ("C-@",) and keys[4] == ("-l", "--", "\\;")
    del termbridge._WATCHES[(SOCK[0], TID)]


def test_the_plain_terminal_is_found_by_its_session(tmp_path):
    SOCK[0] = "orch-" + secrets.token_hex(4)
    sid = "t_plain0001"
    try:
        tm("new-session", "-d", "-x", "80", "-y", "24", "-s", sid, "--", "sh", "-c", "echo plain-shell; cat")
        orch = fake_orch(
            tmp_path,
            {"running": False},
            {
                "sessions": [
                    {"id": sid, "kind": "terminal", "open": True, "tmux": {"socket": SOCK[0], "session": sid}}
                ]
            },
        )
        assert termsession.ref(tmp_path, orch, sid, plain=True) == (SOCK[0], sid)
        assert termsession.ref(tmp_path, orch, sid) == "none"  # the old screen and keys routes: helpers only
        assert termsession.ref(tmp_path, orch, "t_other0002", plain=True) == "none"
        fake_orch(tmp_path, {"running": False}, {"sessions": [{"id": sid, "kind": "terminal", "open": True}]})
        assert termsession.ref(tmp_path, orch, sid, plain=True) == "none"  # its shell does not run
        fake_orch(
            tmp_path,
            {"running": False},
            {
                "sessions": [
                    {"id": sid, "kind": "terminal", "open": True, "tmux": {"socket": "../x", "session": sid}}
                ]
            },
        )
        assert termsession.ref(tmp_path, orch, sid, plain=True) == "none"  # names must have core's shape
    finally:
        tm("kill-server")


def test_watching_needs_the_sign_in(helper, server):
    port = server(Person(False)).server_address[1]
    s = Stream(port)
    # 401: no sign-in reaches no data at all (ORCH-481); 403: the bridge itself refuses
    assert s.resp.status in (401, 403) and not termbridge._WATCHES


def test_a_page_that_joins_gets_the_modes_the_program_turned_on(helper, server):
    tm(
        "respawn-pane",
        "-k",
        "-t",
        f"={TID}:",
        "sh",
        "-c",
        "printf '\\033[?2004h\\033[?1h\\033[?1000hready'; cat",
    )
    # wait on the screen, not on bracket_paste_flag: that flag came in tmux 3.7 and CI's Ubuntu ships 3.4
    assert wait(lambda: "ready" in tm("capture-pane", "-p", "-t", f"={TID}:").stdout)
    port = server().server_address[1]
    s = Stream(port)
    data = base64.b64decode(json.loads(s.next("screen")[1])["data"])
    assert b"ready" in data and b"\x1b[?1h" in data and b"\x1b[?1000h" in data
    if _tmux_version() >= (3, 7):  # an older tmux cannot tell whether bracketed paste is on
        assert b"\x1b[?2004h" in data
    assert b"\x1b[?1003h" not in data  # only what is on
    s.close()


def test_joining_while_output_flows_shows_every_line_once(helper, server):
    tm(
        "respawn-pane",
        "-k",
        "-t",
        f"={TID}:",
        "sh",
        "-c",
        "i=0; while [ $i -lt 400 ]; do i=$((i+1)); echo n$i; sleep 0.005; done; cat",
    )
    time.sleep(0.3)  # it is printing now
    port = server().server_address[1]
    s = Stream(port)
    shown = base64.b64decode(json.loads(s.next("screen")[1])["data"])
    assert s.until(b"n400\r\n", timeout=15)
    import re

    nums = [int(x) for x in re.findall(rb"n([0-9]+)\r", shown + s.seen)]
    assert nums == list(range(nums[0], 401))  # the capture and the stream meet exactly: no line twice or lost
    s.close()


def test_typing_stays_on_the_pane_the_page_shows(helper, server, tmp_path):
    typing_on(tmp_path)
    port = server().server_address[1]
    s = Stream(port)
    s.next("screen")
    first = termbridge.watching(TID).pane
    tm("split-window", "-t", f"={TID}:", "--", "sh", "-c", "cat")  # a second pane, now the active one
    assert post(port, "/api/term/input", {"ticket": TID, "data": "pinned\r"}) == (200, b"{}")
    assert wait(lambda: "pinned" in tm("capture-pane", "-p", "-t", first).stdout)
    s.close()


def test_two_typing_requests_never_mix(helper, monkeypatch):
    w = termbridge.Watch(SOCK[0], TID)
    w.pages, w.pane = 1, "%0"
    termbridge._WATCHES[(SOCK[0], TID)] = w
    sent = []

    def slow(sock, *a, **k):
        sent.append(a[-1][:1])
        time.sleep(0.002)
        return subprocess.CompletedProcess(a, 0)

    monkeypatch.setattr(termbridge, "_tmux", slow)
    ts = [threading.Thread(target=termbridge.type_text, args=(TID, c * termbridge.PART * 5)) for c in "ab"]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert "".join(sent) in ("aaaaabbbbb", "bbbbbaaaaa")
    del termbridge._WATCHES[(SOCK[0], TID)]


def test_a_late_answer_goes_to_its_own_read_not_the_next():
    """A screen read that timed out stays owed: its late blocks are taken by it, the next read gets its own."""
    import io

    w = termbridge.Watch("orch-00000000", TID)
    w.pane = "%0"
    old = {"done": threading.Event(), "at": None, "blocks": [], "open": 0}
    new = {"done": threading.Event(), "at": None, "blocks": [], "open": 0}
    w._owed = [old, new]
    meta = b"@@orch 0 0 80 24 0 1 1" + b" 0" * len(termbridge._FLAGS)

    class Proc:
        stdin = io.BytesIO()
        stdout = io.BytesIO(
            b"%begin 1 10 0\n%end 1 10 0\n"  # attach's own block: nobody's
            b"%begin 1 11 1\nOLD SCREEN\n%end 1 11 1\n%begin 1 12 1\n" + meta + b"\n%end 1 12 1\n"
            b"%output %0 between\\015\\012\n"
            b"%begin 1 13 1\nNEW SCREEN\n%end 1 13 1\n%begin 1 14 1\n" + meta + b"\n%end 1 14 1\n"
        )

        def wait(self, timeout=None):
            return 0

    w.proc = Proc()
    w._read()
    assert old["blocks"][0] == (True, b"OLD SCREEN") and old["at"] == 0
    assert new["blocks"][0] == (True, b"NEW SCREEN") and new["at"] == 1  # after the output it must not repeat
    assert new["done"].is_set() and w._owed == []
    assert termbridge.draw(b"x", b"@@orch 1 2") is None  # reads it cannot understand: no screen


def test_a_revoked_sign_in_ends_the_stream_also_while_output_flows(helper, server):
    """ORCH-745 M1: the sign-in is asked again on every turn of the stream, not only when it opens."""
    person = Person()
    port = server(person).server_address[1]
    s = Stream(port)
    s.next("screen")
    assert wait(lambda: termbridge._PAGES[0] == 1)
    person.ok = False  # Sign out everywhere: the cookie this page holds is no longer the server's
    stop = threading.Event()

    def flow():  # the helper keeps writing, so the stream is never idle
        while not stop.is_set():
            tm("send-keys", "-t", f"={TID}:", "-l", "x")
            time.sleep(0.05)

    threading.Thread(target=flow, daemon=True).start()
    try:
        assert wait(lambda: termbridge._PAGES[0] == 0, timeout=5.0)
    finally:
        stop.set()
        s.close()


def test_too_many_ctrl_space_keys_in_one_request_are_refused(helper, monkeypatch):
    """ORCH-745: every NUL is its own tmux call; one request may not start thousands of them."""
    sent = []
    w = termbridge.Watch(SOCK[0], TID)
    w.pages, w.pane = 1, "%0"
    termbridge._WATCHES[(SOCK[0], TID)] = w
    monkeypatch.setattr(
        termbridge, "_tmux", lambda sock, *a, **k: sent.append(a) or subprocess.CompletedProcess(a, 0)
    )
    try:
        assert termbridge.type_text(TID, "\x00" * (termbridge.MAX_NUL + 1))[0] == 400
        assert sent == []
        assert termbridge.type_text(TID, "\x00" * termbridge.MAX_NUL) == (200, "{}")
    finally:
        del termbridge._WATCHES[(SOCK[0], TID)]


def test_a_page_that_leaves_before_the_headers_gives_its_place_back(helper, server, monkeypatch):
    """ORCH-745: a stream slot is given back also when writing the headers fails."""
    from orch_dashboard import server as srvmod

    def broken(self):
        raise BrokenPipeError

    monkeypatch.setattr(srvmod.Handler, "end_headers", broken)
    port = server().server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", f"/api/term/stream?ticket={TID}", headers={"Host": f"127.0.0.1:{port}"})
    try:
        conn.getresponse()
    except (OSError, http.client.HTTPException):
        pass
    conn.close()
    assert wait(lambda: termbridge._PAGES[0] == 0)


def test_no_add_on_frame_may_watch_or_type_into_the_terminal():
    """ORCH-745: a sandboxed add-on page's pass (some may act) never reaches the terminal bridge, so it can never
    read or type into the plain terminal's shell. Adding these routes to FRAME_ROOT needs a security review."""
    from orch_dashboard import framepass

    assert not framepass.ALL_ROOT_PATHS & {"/api/term/stream", "/api/term/input", "/api/term/size"}


def size_now() -> str:
    return tm("display-message", "-p", "-t", f"={TID}:", "#{window_width}x#{window_height}").stdout.strip()


def test_one_page_types_at_a_time_and_the_other_hears_it(helper, server, tmp_path):
    """ORCH-883: two tabs on one session; turning typing on in B stops A, and A's keys no longer go in."""
    typing_on(tmp_path)
    port = server().server_address[1]
    a, b = Stream(port), Stream(port)
    pa, pb = (json.loads(x.next("hello")[1])["page"] for x in (a, b))
    a.next("screen"), b.next("screen")
    assert pa != pb
    assert post(port, "/api/term/typing", {"ticket": TID, "page": pa, "on": True}) == (200, b"{}")
    assert json.loads(a.next("typing")[1]) == {"by": "you"} and json.loads(b.next("typing")[1]) == {
        "by": "other"
    }
    assert post(port, "/api/term/input", {"ticket": TID, "data": "from-a\r", "page": pa}) == (200, b"{}")
    assert post(port, "/api/term/input", {"ticket": TID, "data": "x", "page": pb})[0] == 409
    assert (
        post(port, "/api/term/input", {"ticket": TID, "data": "x"})[0] == 409
    )  # no page: not the one typing
    assert post(port, "/api/term/size", {"ticket": TID, "cols": 90, "rows": 20, "page": pb})[0] == 409
    assert post(port, "/api/term/typing", {"ticket": TID, "page": pb, "on": True}) == (200, b"{}")
    assert json.loads(a.next("typing")[1]) == {"by": "other"} and json.loads(b.next("typing")[1]) == {
        "by": "you"
    }
    code, body = post(port, "/api/term/input", {"ticket": TID, "data": "late-a", "page": pa})
    assert code == 409 and b"Another page is typing" in body
    assert post(port, "/api/term/input", {"ticket": TID, "data": "from-b\r", "page": pb}) == (200, b"{}")
    assert a.until(b"from-b") and b"late-a" not in a.seen
    c = Stream(port)  # a page that joins now hears who types
    c.next("screen")
    assert json.loads(c.next("typing")[1]) == {"by": "other"}
    c.close()
    assert (
        post(port, "/api/term/typing", {"ticket": TID, "page": "made-up", "on": True})[0] == 409
    )  # no such stream
    # B leaves: nobody types, A may take it again
    b.close()
    assert json.loads(a.next("typing", timeout=8)[1]) == {"by": "none"}
    assert post(port, "/api/term/input", {"ticket": TID, "data": "again-a\r", "page": pa}) == (200, b"{}")
    for bad in ({"page": "", "on": True}, {"page": pa, "on": 1}, {"page": pa}, {"page": 5, "on": True}):
        assert post(port, "/api/term/typing", {"ticket": TID, **bad})[0] == 400
    assert post(port, "/api/term/typing", {"ticket": "t_other0002", "page": pa, "on": True})[0] == 409
    a.close()


def test_a_watching_page_sizes_the_window_and_the_own_size_comes_back_when_the_pages_leave(helper, server, tmp_path):
    """ORCH-1758 (owner): with nobody typing, a watching page sizes the helper's window to its box too; turning
    typing off keeps the page's size (it still watches); the own size comes back when the last page left."""
    typing_on(tmp_path)
    port = server().server_address[1]
    a, b = Stream(port), Stream(port)
    pa, pb = (json.loads(x.next("hello")[1])["page"] for x in (a, b))
    a.next("screen"), b.next("screen")
    assert post(port, "/api/term/size", {"ticket": TID, "cols": 60, "rows": 8, "page": pa}) == (200, b"{}")
    assert size_now() == "60x8"
    assert post(port, "/api/term/size", {"ticket": TID, "cols": 70, "rows": 9, "page": pb}) == (200, b"{}")
    assert size_now() == "70x9"  # the last page that sized it wins; both hear the size
    assert json.loads(a.next("size")[1]) == {"cols": 60, "rows": 8}
    assert json.loads(a.next("size")[1]) == {"cols": 70, "rows": 9}
    assert post(port, "/api/term/typing", {"ticket": TID, "page": pa, "on": True})[0] == 200
    assert post(port, "/api/term/size", {"ticket": TID, "cols": 90, "rows": 20, "page": pb})[0] == 409  # A types
    assert post(port, "/api/term/size", {"ticket": TID, "cols": 50, "rows": 6, "page": pa}) == (200, b"{}")
    assert post(port, "/api/term/typing", {"ticket": TID, "page": pa, "on": False}) == (200, b"{}")
    assert size_now() == "50x6"  # A still watches: its size stays, no jump to the own size and back
    typing_on(tmp_path, False)
    assert post(port, "/api/term/size", {"ticket": TID, "cols": 90, "rows": 20, "page": pb})[0] == 403  # setting off
    typing_on(tmp_path)
    a.close(), b.close()
    assert wait(lambda: size_now() == "80x24", timeout=8)


def test_the_helpers_window_gets_its_own_size_back_when_the_typing_page_leaves(helper, server, tmp_path):
    """ORCH-881: a page that typed in a small pane resized the helper to 60x8; typing off keeps the size while the
    page still watches (ORCH-1758); leaving gives back 80x24."""
    typing_on(tmp_path)
    port = server().server_address[1]
    s = Stream(port)
    page = json.loads(s.next("hello")[1])["page"]
    s.next("screen")
    assert post(port, "/api/term/typing", {"ticket": TID, "page": page, "on": True})[0] == 200
    assert post(port, "/api/term/size", {"ticket": TID, "cols": 60, "rows": 8, "page": page}) == (200, b"{}")
    assert post(port, "/api/term/size", {"ticket": TID, "cols": 70, "rows": 9, "page": page}) == (200, b"{}")
    assert size_now() == "70x9"
    typing_on(tmp_path, False)  # the setting went off meanwhile: giving the typing back still works
    assert post(port, "/api/term/typing", {"ticket": TID, "page": page, "on": True})[0] == 403
    assert post(port, "/api/term/typing", {"ticket": TID, "page": page, "on": False}) == (200, b"{}")
    assert size_now() == "70x9"  # the page still watches: it keeps its size (ORCH-1758)
    typing_on(tmp_path)
    sizes = [json.loads(s.next("size")[1]) for _ in range(2)]  # every page hears each size
    assert sizes[-1] == {"cols": 70, "rows": 9}
    # typing again and leaving without turning it off: the size comes back too
    assert post(port, "/api/term/typing", {"ticket": TID, "page": page, "on": True})[0] == 200
    assert post(port, "/api/term/size", {"ticket": TID, "cols": 50, "rows": 6, "page": page})[0] == 200
    assert size_now() == "50x6"
    s.close()
    assert wait(lambda: size_now() == "80x24", timeout=8)


def test_the_plain_terminal_has_its_own_typing_switch(tmp_path, monkeypatch):
    """ORCH-261 (owner): the plain terminal is a shell on this computer; typing into it needs its own switch
    (focus.terminal_typing, off by default), the helper's switch alone is not enough."""
    SOCK[0] = "orch-" + secrets.token_hex(4)
    monkeypatch.setattr(termbridge, "LINGER", 0.3)
    sid = "t_plain0001"
    tm("new-session", "-d", "-x", "80", "-y", "24", "-s", sid, "--", "sh", "-c", "echo plain-shell; cat -v")
    sessions = {
        "sessions": [
            {"id": sid, "kind": "terminal", "open": True, "tmux": {"socket": SOCK[0], "session": sid}}
        ]
    }
    orch = fake_orch(tmp_path, {"running": False}, sessions)
    (tmp_path / ".orch" / "tickets").mkdir(parents=True)
    srv = make_server(tmp_path, 0, orch_bin=orch)
    srv.RequestHandlerClass = functools.partial(srv.RequestHandlerClass, session=Person())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        typing_on(tmp_path)  # the helper's switch on, the plain terminal's not
        s = Stream(port, tid=sid)
        assert json.loads(s.next("hello")[1])["typing_allowed"] is False
        s.next("screen")
        assert termbridge.watching(sid).plain is True
        code, body = post(port, "/api/term/input", {"ticket": sid, "data": "x"})
        assert code == 403 and b"Typing into the plain terminal is off" in body
        # resize and taking the typing are refused too, also with a page id
        assert post(port, "/api/term/size", {"ticket": sid, "cols": 60, "rows": 10})[0] == 403
        assert post(port, "/api/term/typing", {"ticket": sid, "page": "p" * 16, "on": True})[0] == 403
        assert post(port, "/api/term/typing", {"ticket": sid, "page": "p" * 16, "on": False})[0] == 200
        (tmp_path / ".orch" / "config.toml").write_text(
            "[focus]\nsession_typing = false\nterminal_typing = true\n"
        )
        assert post(port, "/api/term/input", {"ticket": sid, "data": "shell-typed\r"}) == (200, b"{}")
        assert s.until(b"shell-typed")
        s.close()
        s2 = Stream(port, tid=sid)  # a page that opens now hears that it may type
        assert json.loads(s2.next("hello")[1])["typing_allowed"] is True
        s2.close()
    finally:
        srv.shutdown()
        srv.server_close()
        for w in list(termbridge._WATCHES.values()):
            w.close()
        tm("kill-server")


def test_an_id_that_is_both_a_helper_and_the_plain_terminal_counts_as_the_shell(tmp_path):
    """ORCH-261: the stricter switch wins; a helper claim on the same id never makes the shell a helper."""
    SOCK[0] = "orch-" + secrets.token_hex(4)
    sid = "t_plain0001"
    tmux = {"socket": SOCK[0], "session": sid}
    try:
        tm("new-session", "-d", "-x", "80", "-y", "24", "-s", sid, "--", "sh", "-c", "cat")
        orch = fake_orch(
            tmp_path,
            {"running": True, "claim": {"tmux": tmux}},
            {"sessions": [{"id": sid, "kind": "terminal", "open": True, "tmux": tmux}]},
        )
        assert termsession.ref_kind(tmp_path, orch, sid, plain=True) == ((SOCK[0], sid), True)
        assert termsession.ref_kind(tmp_path, orch, sid) == ((SOCK[0], sid), False)  # helpers' own routes
        w = termbridge.Watch(SOCK[0], sid)
        w.plain = True
        termbridge._WATCHES[(SOCK[0], sid)] = w
        fake_orch(tmp_path, {"running": True, "claim": {"tmux": tmux}}, {"sessions": []})
        joined = termbridge.join(tmp_path, orch, sid, "pg")
        assert joined is w and w.plain is True  # a later helper look never turns the mark off
        termbridge.leave(w, "pg")
    finally:
        for x in list(termbridge._WATCHES.values()):
            x.close()
        termbridge._WATCHES.clear()
        tm("kill-server")
