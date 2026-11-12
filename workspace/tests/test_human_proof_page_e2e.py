"""NOT mocked (1.0a-2): the real dashboard server -> run_with_proof -> a REAL `sys.executable -I -m orch`
child on a test workspace and test home. Per first-batch op: the op succeeds, `by` comes from the proof, and
the input counts as a person's (it is what starts a run). Runs in CI on POSIX."""

import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest
from conftest import _REAL_HOME_FN, stray_tmux

from orch import addons, pageproof, runs, tickets
from orch import humanproof as hp

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workspace-addons" / "dashboard" / "src"))
pytest.importorskip("orch_dashboard.server")
from orch_dashboard.server import make_server  # noqa: E402


@pytest.fixture
def live(monkeypatch):
    """A test workspace + test home under the REAL ~/.orch-test (a child process sees the real account home),
    never ~/.orch-tool. Removed by exact path."""
    base = _REAL_HOME_FN() / ".orch-test"
    base.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="pytest-page-", dir=base))
    home = Path(tempfile.mkdtemp(prefix="pytest-home-", dir=base))
    (root / ".orch").mkdir()
    monkeypatch.setattr(addons, "real_home", _REAL_HOME_FN)
    monkeypatch.setenv("ORCH_HOME", str(home))
    for k in list(os.environ):
        if k.startswith("CODEX_") or k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "ORCH_AGENT", "ORCH_BIN"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(root)
    # No agent tool and no tmux can be found by the child: an answer would otherwise START a real agent (a
    # live tmux session) via resume_after_answer. These tests check the op, not a real agent run.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    srv = make_server(root, 0, orch_bin=pageproof.SELF)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    yield root, port
    srv.shutdown()
    srv.server_close()
    leftovers = stray_tmux(str(root))
    for sock in leftovers:  # clean up first, then fail: a test must leave no tmux server behind
        subprocess.run(["/usr/bin/env", "tmux", "-L", sock, "kill-server"], check=False, capture_output=True)
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(home, ignore_errors=True)
    assert not leftovers, f"tmux servers left behind: {leftovers}"


SECRETS = {}  # cookie -> page secret of the sessions this module signed in


def http_post(port, path, body, cookie=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    h = {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
    }
    if cookie:
        h["Cookie"] = cookie
        if cookie in SECRETS:
            h["X-Orch-Page"] = SECRETS[cookie]
    c.request("POST", path, json.dumps(body), h)
    r = c.getresponse()
    return r.status, r.getheader("Set-Cookie"), r.read().decode()


def signed_in(root, port):
    st, ck, body = http_post(port, "/session", {"token": hp.write_launch_token(root, "dashboard")})
    assert st == 200
    cookie = ck.split(";")[0]
    SECRETS[cookie] = json.loads(body)["secret"]
    return cookie


def act(root, port, ck, op, args):
    return http_post(port, "/api/act", {"op": op, "args": args}, ck)


def new_ticket(run, title="T", review=False, root=None):
    code, out, _ = run("ticket", "new", title, "--json", "--by", "agent:x")
    tid = json.loads(out)["id"]
    if review:
        tickets.apply_op(root, tid, lambda t: t.update(status="review"), by=tickets.SYSTEM)
    return tid


def test_answer_click(live, run):
    root, port = live
    tid = new_ticket(run)
    code, out, _ = run("ask", tid, "Which?", "--json", "--by", "agent:x")
    q = json.loads(out)["id"]
    ck = signed_in(root, port)
    shown = next(x for x in tickets.load(root, tid)["questions"] if x["id"] == q)  # what the page showed
    st, _, body = act(
        root,
        port,
        ck,
        "answer",
        {"ticket": tid, "question": q, "digest": tickets.question_digest(shown), "answer": "Blue -- not red"},
    )
    assert st == 200, body
    t = tickets.load(root, tid)
    assert t["questions"][0]["answer"] == "Blue -- not red"  # text after `--` survived
    assert pageproof.actor() in [h["by"] for h in t["history"]]  # by comes from the proof


def test_send_back_click_starts_a_run(live, run):
    root, port = live
    tid = new_ticket(run, review=True, root=root)
    ck = signed_in(root, port)
    st, _, body = act(root, port, ck, "ticket.changes", {"ticket": tid, "text": "Please add tests"})
    assert st == 200, body
    assert tickets.load(root, tid)["status"] == "ready"
    assert [i["text"] for i in runs.human_waiting(root, tid)] == [
        "Please add tests"
    ]  # the host starts a run for it


def test_looks_good_click(live, run):
    root, port = live
    tid = new_ticket(run, review=True, root=root)
    ck = signed_in(root, port)
    rev = tickets.load(root, tid)["revision"]
    st, _, body = act(
        root, port, ck, "ticket.patch", {"ticket": tid, "data": {"status": "done"}, "if_revision": rev}
    )
    assert st == 200, body
    t = tickets.load(root, tid)
    assert t["status"] == "done" and t["history"][-1]["by"] == pageproof.actor()


def test_terminal_run_send_waits_for_one_click(live, run):
    root, port = live
    tid = new_ticket(run)
    code, out, err = run("run", "send", tid, "go on -- please", "--by", "human:pat", "--json")
    assert code == 2 and "Continue" in (out + err)
    assert runs.human_waiting(root, tid) == []  # nothing starts without the click
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request("GET", "/api/handoffs", headers={"Host": f"127.0.0.1:{port}"})
    items = json.loads(c.getresponse().read())
    assert len(items) == 1 and items[0]["op"] == "run.human_input"
    ck = signed_in(root, port)
    st, _, body = http_post(port, "/api/act", {"op": "handoff.confirm", "args": {"id": items[0]["id"]}}, ck)
    assert st == 200, body
    assert [i["text"] for i in runs.human_waiting(root, tid)] == ["go on -- please"]


def test_chat_click(live, run):
    root, port = live
    ck = signed_in(root, port)
    st, _, body = act(root, port, ck, "chat.say", {"text": "Hello -- there"})
    assert st == 200, body
    gid = (
        next(t["id"] for t in tickets.list_tickets(root) if t.get("general"))
        if hasattr(tickets, "list_tickets")
        else None
    )
    if gid:
        assert [i["text"] for i in runs.human_waiting(root, gid)] == ["Hello -- there"]


def test_proof_flag_goes_before_the_double_dash():
    seen = {}
    import subprocess

    real = subprocess.run
    subprocess.run = lambda argv, **k: (
        seen.update(argv=argv) or subprocess.CompletedProcess(argv, 0, "{}", "")
    )
    try:
        pageproof.run_with_proof(
            ["answer", "t_a", "q1", "--by", "human:x", "--json", "--", "text"],
            "hp1.x.y",
            orch_bin=pageproof.SELF,
            cwd=Path("/"),
            env={},
            timeout=5,
        )
    finally:
        subprocess.run = real
    a = seen["argv"]
    assert a.index("--proof-stdin") < a.index("--") and a[-1] == "text"


def test_relay_connect_via_hand_off_reaches_the_relay_with_a_proof(live, run):
    """The person's terminal `relay connect` waits for one click; Continue runs it with a proof and the token
    that was kept apart. The relay is not there (port 1): "can't reach" means the proof WAS accepted."""
    from conftest import turn_on

    root, port = live
    turn_on(root, "relay")
    code, out, err = run(
        "relay",
        "connect",
        "http://127.0.0.1:1",
        "--workspace",
        "ws_a",
        "--token",
        "orn_T0KEN",
        "--by",
        "human:pat",
        "--json",
    )
    assert code == 2 and "orn_T0KEN" not in out + err
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request("GET", "/api/handoffs", headers={"Host": f"127.0.0.1:{port}"})
    item = json.loads(c.getresponse().read())[0]
    assert item["op"] == "relay.connect" and "orn_T0KEN" not in json.dumps(item)
    ck = signed_in(root, port)
    st, _, body = http_post(port, "/api/act", {"op": "handoff.confirm", "args": {"id": item["id"]}}, ck)
    assert st == 422 and "reach" in body.lower() and "dashboard on this computer" not in body
