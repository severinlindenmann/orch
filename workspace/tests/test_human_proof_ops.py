"""H1 on the first batch of ops (slice 1.0a-2): forged flags, missing / expired / wrong target / wrong op /
replayed proofs, the dev test human, the pending start flows, launch token, hand-off."""

import io
import json
import os
import sys
import time

import pytest

from orch import humanproof as hp
from orch import pageproof, runs, tickets
from orch.errors import Refused


@pytest.fixture
def ws(proj, monkeypatch):
    """A TEST workspace under <fake home>/.orch-test with its test home (a source-tree test install never
    pairs a real workspace with the account home), with the same environment hygiene as `proj`."""
    from orch import addons

    acct = addons.real_home()
    base = acct / ".orch-test"
    root = base / "ws"
    (root / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.chdir(root)
    return root


def _proof(ws, op, target, by="human:pat", **kw):
    key = hp.human_key(ws)
    p = hp.new_payload(op, target, by, **kw)
    return hp.mint(key, p)


def _cli(run, monkeypatch, proof, *argv):
    monkeypatch.setattr("sys.stdin", io.StringIO((proof + "\n") if proof else ""))
    return run(*argv, "--proof-stdin")


def _review_ticket(ws, run):
    code, out, _ = run("ticket", "new", "T", "--json", "--by", "agent:x")
    tid = json.loads(out)["id"]
    tickets.apply_op(ws, tid, lambda t: t.update(status="review"))
    return tid


def _ask(ws, run):
    code, out, _ = run("ticket", "new", "Q", "--json", "--by", "agent:x")
    tid = json.loads(out)["id"]
    code, out, _ = run("ask", tid, "Which one?", "--json", "--by", "agent:x")
    assert code == 0, out
    return tid, json.loads(out)["id"]


# ------------------------------------------------------------------ answer (ticket.answer)


def test_answer_without_proof_is_refused_and_handed_off(ws, run):
    tid, q = _ask(ws, run)
    code, out, err = run("answer", tid, q, "A", "--by", "human:pat", "--json")
    assert code == 2 and "dashboard on this computer" in (out + err)
    assert tickets.load(ws, tid)["questions"][0].get("answer") is None
    assert any(h["op"] == "ticket.answer" and h["target"] == f"{tid}:{q}" for h in hp.handoffs(ws))


def test_answer_with_valid_proof_takes_by_from_proof(ws, run, monkeypatch):
    tid, q = _ask(ws, run)
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "ticket.answer", f"{tid}:{q}"), "answer", tid, q, "A", "--json"
    )
    assert code == 0, out + err
    assert tickets.load(ws, tid)["history"][-1]["by"] == "human:pat"


@pytest.mark.parametrize(
    "mk",
    [
        lambda ws, tid, q: _proof(ws, "ticket.answer", f"{tid}:{q}", now=int(time.time()) - 500),  # expired
        lambda ws, tid, q: _proof(ws, "ticket.answer", f"{tid}:q9"),  # wrong target
        lambda ws, tid, q: _proof(ws, "ticket.verdict", f"{tid}:{q}"),  # wrong op
        lambda ws, tid, q: "hp1.e30.AAAA",  # garbage
        lambda ws, tid, q: "",  # missing
    ],
)
def test_answer_bad_proofs_refused(ws, run, monkeypatch, mk):
    tid, q = _ask(ws, run)
    code, out, err = _cli(run, monkeypatch, mk(ws, tid, q), "answer", tid, q, "A", "--json")
    assert code == 2 and "dashboard on this computer" in (out + err)
    assert tickets.load(ws, tid)["questions"][0].get("answer") is None


def test_answer_forged_by_flag_with_valid_proof_is_refused(ws, run, monkeypatch):
    tid, q = _ask(ws, run)
    proof = _proof(ws, "ticket.answer", f"{tid}:{q}")
    code, out, err = _cli(
        run, monkeypatch, proof, "answer", tid, q, "A", "--by", "human:someone-else", "--json"
    )
    assert code == 2 and tickets.load(ws, tid)["questions"][0].get("answer") is None


def test_answer_replay_is_refused(ws, run, monkeypatch):
    tid, q = _ask(ws, run)
    proof = _proof(ws, "ticket.answer", f"{tid}:{q}")
    assert _cli(run, monkeypatch, proof, "answer", tid, q, "A", "--json")[0] == 0
    code, out, err = _cli(run, monkeypatch, proof, "answer", tid, q, "B", "--json")
    assert code == 2


def test_agent_in_the_environment_cannot_use_a_valid_proof(ws, run, monkeypatch):
    tid, q = _ask(ws, run)
    proof = _proof(ws, "ticket.answer", f"{tid}:{q}")
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, err = _cli(run, monkeypatch, proof, "answer", tid, q, "A", "--json")
    assert code == 2 and tickets.load(ws, tid)["questions"][0].get("answer") is None


# ------------------------------------------------------------------ verdict


def test_looks_good_needs_the_proof(ws, run, monkeypatch):
    tid = _review_ticket(ws, run)
    args = (
        "ticket",
        "patch",
        tid,
        '{"status": "done"}',
        "--if-revision",
        str(tickets.load(ws, tid)["revision"]),
    )
    code, out, err = run(*args, "--by", "human:pat", "--json")
    assert code == 2 and tickets.load(ws, tid)["status"] == "review"
    code, out, err = _cli(run, monkeypatch, _proof(ws, "ticket.verdict", tid), *args, "--json")
    assert code == 0, out + err
    assert tickets.load(ws, tid)["status"] == "done"


def test_send_back_forged_and_proven(ws, run, monkeypatch):
    tid = _review_ticket(ws, run)
    code, out, err = run("ticket", "changes", tid, "do more", "--by", "human:pat", "--json")
    assert code == 2 and tickets.load(ws, tid)["status"] == "review"
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "ticket.verdict", tid), "ticket", "changes", tid, "do more", "--json"
    )
    assert code == 0, out + err
    # the note is queued as the person's input: it carries the pending MAC and counts as a person's
    assert [i["text"] for i in runs.human_waiting(ws, tid)] == ["do more"]


# ------------------------------------------------------------------ update, relay connect


def test_update_and_relay_connect_refuse_without_proof(ws, run):
    from conftest import turn_on

    turn_on(ws, "relay")
    code, out, err = run("update", "--by", "human:pat", "--json")
    assert code == 2 and "dashboard on this computer" in (out + err)
    code, out, err = run(
        "relay",
        "connect",
        "https://r.example",
        "--workspace",
        "w",
        "--token",
        "orn_x",
        "--by",
        "human:pat",
        "--json",
    )
    assert code == 2 and "dashboard on this computer" in (out + err)
    assert not (ws / ".orch" / "secrets" / "relay.json").exists()


# ------------------------------------------------------------------ pending MAC: who may start a run


def test_forged_pending_line_does_not_start(ws, run):
    tid, _ = _ask(ws, run)
    runs.pending_add(ws, tid, "human:pat", "message", "hello", "dashboard")  # CLI-style: no MAC
    assert runs.human_waiting(ws, tid) == []
    path = runs._pending_path(ws, tid) if hasattr(runs, "_pending_path") else None
    if path:
        lines = [json.loads(x) for x in path.read_text().splitlines()]
        lines[0].update(human=True, mac="x")
        path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        assert runs.human_waiting(ws, tid) == []


def test_run_send_with_proof_counts_as_a_person(ws, run, monkeypatch):
    tid, _ = _ask(ws, run)
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "run.human_input", tid), "run", "send", tid, "go on", "--json"
    )
    assert code == 0, out + err
    assert [i["text"] for i in runs.human_waiting(ws, tid)] == ["go on"]


def test_run_send_without_proof_is_handed_off(ws, run):
    tid, _ = _ask(ws, run)
    code, out, err = run("run", "send", tid, "go on", "--by", "human:pat", "--json")
    assert code == 2 and runs.human_waiting(ws, tid) == []


# ------------------------------------------------------------------ dev test human


def test_dev_proof_never_works_on_a_real_workspace(ws, run, monkeypatch):
    tid, q = _ask(ws, run)
    key = os.urandom(32).hex()
    hp.human_key(ws)
    d = hp.key_dir(ws)
    (d / "dev-human.key").write_text(key + "\n")
    os.chmod(d / "dev-human.key", 0o600)
    p = hp.new_payload("ticket.answer", f"{tid}:{q}", "human:test-human")
    p["dev"] = True
    code, out, err = _cli(run, monkeypatch, hp.mint(bytes.fromhex(key), p), "answer", tid, q, "A", "--json")
    assert code == 2 and tickets.load(ws, tid)["questions"][0].get("answer") is None
    with pytest.raises(Refused):
        hp.mint_dev(ws, "ticket.answer", f"{tid}:{q}")
    with pytest.raises(Refused):
        hp.dev_mark(ws)  # a workspace that already has a human key cannot become dev


def test_dev_workspace_accepts_the_test_human(ws, run, monkeypatch):
    proj = ws
    # a fresh demo workspace: marked dev at creation (no human.key yet), then the test human acts
    monkeypatch.setattr(hp, "install_kind", lambda: "dev")
    hp.dev_mark(proj)
    assert hp.dev_workspace(proj)
    tid, q = _ask(proj, run)
    proof = hp.mint_dev(proj, "ticket.answer", f"{tid}:{q}")
    code, out, err = _cli(run, monkeypatch, proof, "answer", tid, q, "A", "--json")
    assert code == 0, out + err
    assert tickets.load(proj, tid)["history"][-1]["by"] == "human:test-human"
    # on a normal install the same record means nothing
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    assert not hp.dev_workspace(proj)


# ------------------------------------------------------------------ hand-off cap, launch token


def test_handoff_cap_drops_new_requests(ws):
    for i in range(3):
        assert hp.request_handoff(ws, "update", f"orch{i}", argv=["update", str(i)]) is True
    assert (
        hp.request_handoff(ws, "update", "orch9", argv=["update", "9"]) is False
    )  # dropped, nothing evicted
    assert [h["target"] for h in hp.handoffs(ws)] == ["orch0", "orch1", "orch2"]


def test_launch_token_is_single_use_and_expires(ws):
    t = hp.write_launch_token(ws, "dashboard")
    assert t and hp.consume_launch_token(ws, "dashboard", "x" * 24) is False  # wrong token also spends it
    assert hp.consume_launch_token(ws, "dashboard", t) is False
    t = hp.write_launch_token(ws, "focus")
    assert hp.consume_launch_token(ws, "focus", t) is True
    assert hp.consume_launch_token(ws, "focus", t) is False
    with pytest.raises(Refused):
        hp.write_launch_token(ws, "mine")  # a local add-on never gets one


def test_page_session_headers(ws):
    s = pageproof.PageSession(ws, "dashboard")
    assert s.key is not None
    ck = {"Host": "127.0.0.1:8420", "Cookie": f"{pageproof.COOKIE}={s.cookie}"}
    assert s.can_mint(ck, 8420)
    assert not s.can_mint({**ck, "Host": "evil.example:8420"}, 8420)
    assert not s.can_mint({**ck, "X-Forwarded-For": "1.2.3.4"}, 8420)
    assert not s.can_mint({**ck, "Forwarded": "for=1.2.3.4"}, 8420)
    assert not s.can_mint({"Host": "127.0.0.1:8420"}, 8420)  # no cookie
    assert not s.can_mint({**ck, "Cookie": f"{pageproof.COOKIE}=nope"}, 8420)


def test_page_session_is_watch_only_with_an_agent_in_the_environment(ws, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    assert pageproof.PageSession(ws, "focus").key is None


def test_argv0_never_uses_orch_bin(monkeypatch):
    monkeypatch.setenv("ORCH_BIN", "/tmp/planted")
    argv = pageproof.argv0(pageproof.SELF)
    assert argv[:4] == [pageproof.sys.executable, "-I", "-P", "-m"] and "planted" not in " ".join(argv)
    assert "ORCH_BIN" not in pageproof.child_env({"ORCH_BIN": "/tmp/planted"}, pageproof.SELF)


# ------------------------------------------------------------------ hand-off: terminal -> one click


def test_terminal_answer_queues_a_handoff_with_the_command_and_no_token(ws, run):
    tid, q = _ask(ws, run)
    code, out, err = run("answer", tid, q, "Blue", "--by", "human:pat", "--json")
    assert code == 2
    text = out + err
    assert "Continue" in text and "launch" not in text and "hp1." not in text
    item = hp.handoffs(ws)[0]
    assert item["argv"][:3] == ["answer", tid, q] and "--by" not in item["argv"]
    assert not list(
        hp.key_dir(ws).glob("launch-*.token")
    )  # a hand-off writes no token for the caller to read


def test_handoff_is_not_queued_for_words_the_page_cannot_run(ws):
    assert hp.request_handoff(ws, "ticket.answer", "t_a:q1", argv=["config", "set", "x", "y"]) is False
    assert hp.request_handoff(ws, "no.such.op", "t_a", argv=["answer"]) is False
    assert hp.handoffs(ws) == []
    assert hp.request_handoff(ws, "ticket.answer", "t_a:q1", argv=["answer", "t_a", "q1", "--", "x"]) is True
    hid = hp.handoffs(ws)[0]["id"]
    assert hp.handoff_take(ws, hid)["argv"][0] == "answer"
    assert hp.handoff_take(ws, hid) is None  # one click, one run


def test_handoff_card_shows_the_exact_text_and_the_stored_value_is_what_runs(ws, run):
    tid, q = _ask(ws, run)
    run("answer", tid, q, "Blue -- really", "--by", "human:pat", "--json")
    card = hp.handoffs(ws)[0]
    assert card["value"] == "Blue -- really"
    assert card["parts"] == {"title": "Q", "question": "Which one"}  # structured fields, no sentence
    assert "{value}" not in json.dumps(card) and tid not in json.dumps(card["parts"])  # no id, no template
    # a stored value that is not in the stored command is never run
    d = hp.key_dir(ws)
    items = json.loads((d / "handoffs.json").read_text())
    items[0]["argv"] = [w.replace("Blue -- really", "Something else") for w in items[0]["argv"]]
    hp._write_private(d / "handoffs.json", json.dumps(items))
    assert hp.handoff_take(ws, card["id"]) is None


def test_handoff_values_over_the_limit_are_not_queued(ws, run):
    tid, _ = _ask(ws, run)
    code, out, err = run("run", "send", tid, "x" * (hp.VALUE_MAX + 1), "--by", "human:pat", "--json")
    assert code == 2 and hp.handoffs(ws) == []


def test_run_send_file_is_refused_without_a_proof(ws, run):
    tid, _ = _ask(ws, run)
    f = ws / "msg.txt"
    f.write_text("secret plan")
    code, out, err = run("run", "send", tid, "--file", str(f), "--by", "human:pat", "--json")
    assert code == 2 and hp.handoffs(ws) == []


def test_every_caller_shows_its_text_on_the_card(ws, run):
    tid = _review_ticket(ws, run)
    run("ticket", "changes", tid, "Please fix the tests", "--by", "human:pat", "--json")
    run("chat", "say", "Hello team", "--by", "human:pat", "--json")
    run("run", "send", tid, "go on", "--by", "human:pat", "--json")
    vals = sorted(h["value"] for h in hp.handoffs(ws))
    assert vals == ["Hello team", "Please fix the tests", "go on"]


def test_handoff_click_delivers_the_answer_and_it_counts_as_a_person(ws, run, monkeypatch):
    """What the dashboard does on Continue: take the item, mint, run the stored command with the proof."""
    tid, q = _ask(ws, run)
    run("answer", tid, q, "Blue", "--by", "human:pat", "--json")
    item = hp.handoff_take(ws, hp.handoffs(ws)[0]["id"])
    proof = hp.mint(hp.human_key(ws), hp.new_payload(item["op"], item["target"], "human:pat"))
    code, out, err = _cli(run, monkeypatch, proof, *item["argv"])
    assert code == 0, out + err
    assert tickets.load(ws, tid)["questions"][0]["answer"] == "Blue"


# ------------------------------------------------------------------ the browser opener gets no caller env


def test_opener_env_is_built_from_scratch(monkeypatch):
    for k, v in {
        "BROWSER": "/tmp/steal",
        "PATH": "/tmp/evil",
        "LD_PRELOAD": "/tmp/x.so",
        "GIO_EXTRA_MODULES": "/t",
        "XDG_CONFIG_HOME": "/t",
        "PYTHONPATH": "/t",
        "DISPLAY": ":0",
    }.items():
        monkeypatch.setenv(k, v)
    env = hp.opener_env()
    assert env["PATH"] == "/usr/bin:/bin"
    assert not {
        k for k in env if "BROWSER" in k or k.startswith(("LD_", "GIO_", "XDG_CONFIG", "PYTHON", "DYLD_"))
    }
    assert set(env) <= {
        "PATH",
        "HOME",
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
    }


def test_open_browser_passes_exactly_that_env_and_cwd(monkeypatch):
    import subprocess

    seen = {}
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: seen.update(cmd=cmd, **kw))
    monkeypatch.setenv("BROWSER", "/tmp/steal")
    monkeypatch.setattr(hp.sys, "platform", "darwin")
    assert hp.open_browser("http://127.0.0.1:1/#launch=abc") is True
    assert seen["cmd"][0] == "/usr/bin/open" and seen["cwd"] == "/" and seen["env"] == hp.opener_env()
    assert "BROWSER" not in seen["env"]


def test_proof_child_env_drops_code_loading_variables():
    env = pageproof.child_env(
        {"LD_PRELOAD": "x", "DYLD_INSERT_LIBRARIES": "x", "PYTHONPATH": "x", "HOME": "/h"}, pageproof.SELF
    )
    assert env == {"HOME": "/h"}


# ------------------------------------------------------------------ launch token: expiry, second use revokes


def test_launch_token_lives_30_seconds_and_an_expired_one_is_refused(ws, monkeypatch):
    assert hp.LAUNCH_LIFE <= 30
    s = pageproof.PageSession(ws, "focus")
    tok = hp.write_launch_token(ws, "focus")
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 31)
    assert s.launch(tok) is None
    assert not s.revoked  # an expired token is just refused


def test_second_use_of_a_spent_token_revokes_the_session(ws, capsys):
    s = pageproof.PageSession(ws, "dashboard")
    tok = hp.write_launch_token(ws, "dashboard")
    cookie = s.launch(tok)
    hdr = {"Host": "127.0.0.1:1", "Cookie": f"{pageproof.COOKIE}={cookie}"}
    assert s.can_mint(hdr, 1)
    assert s.launch(tok) is None  # the same link used again
    assert s.revoked and not s.can_mint(hdr, 1)  # the session minted from it is dead
    assert "Someone else tried to use this sign-in link" in pageproof.REVOKED_MSG
    err = capsys.readouterr().err
    assert "used twice" in err and tok not in err and cookie not in err  # the log line holds no secret
    # one more click on the dashboard from orch gives a new token and a working session
    cookie2 = s.launch(hp.write_launch_token(ws, "dashboard"))
    assert cookie2 and cookie2 != cookie and s.can_mint({**hdr, "Cookie": f"{pageproof.COOKIE}={cookie2}"}, 1)


def test_two_threads_with_the_same_token_exactly_one_session_then_revoked(ws, capsys):
    import threading

    s = pageproof.PageSession(ws, "dashboard")
    tok = hp.write_launch_token(ws, "dashboard")
    barrier, got = threading.Barrier(2), []

    def hit():
        barrier.wait()
        got.append(s.launch(tok))

    ts = [threading.Thread(target=hit) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(g is not None for g in got) == [False, True]  # exactly one request got a session
    assert s.revoked  # the other one revoked it
    first = next(g for g in got if g)
    assert not s.can_mint({"Host": "127.0.0.1:1", "Cookie": f"{pageproof.COOKIE}={first}"}, 1)
    err = capsys.readouterr().err
    assert "used twice" in err and tok not in err and first not in err


def test_looks_good_cannot_be_bypassed_in_two_steps(ws, run):
    tid = _review_ticket(ws, run)
    rev = lambda: str(tickets.load(ws, tid)["revision"])  # noqa: E731
    # step 1: away from Review as a person, no proof
    code, *_ = run(
        "ticket", "patch", tid, '{"status": "active"}', "--if-revision", rev(), "--by", "human:x", "--json"
    )
    assert code == 2 and tickets.load(ws, tid)["status"] == "review"
    tickets.apply_op(ws, tid, lambda t: t.update(status="active"))  # an agent's own move
    # step 2: to done as a person, no proof
    code, *_ = run(
        "ticket", "patch", tid, '{"status": "done"}', "--if-revision", rev(), "--by", "human:x", "--json"
    )
    assert code == 2 and tickets.load(ws, tid)["status"] == "active"
    # non-status edits stay free
    code, *_ = run(
        "ticket", "patch", tid, '{"note": "n"}', "--if-revision", rev(), "--by", "human:x", "--json"
    )
    assert code == 0


def test_relay_connect_handoff_keeps_the_token_out_of_handoffs_json(ws, run, monkeypatch):
    from conftest import turn_on

    turn_on(ws, "relay")
    code, out, err = run(
        "relay",
        "connect",
        "https://r.example",
        "--workspace",
        "ws_a",
        "--token",
        "orn_SECRETTOKEN",
        "--by",
        "human:pat",
        "--json",
    )
    assert code == 2 and "orn_SECRETTOKEN" not in out + err
    card = hp.handoffs(ws)[0]
    assert (
        card["op"] == "relay.connect"
        and card["parts"] == {"host": "r.example", "scheme": "https"}
        and "ws_a" not in json.dumps(card["parts"])
    )
    assert "orn_SECRETTOKEN" not in json.dumps(hp.handoffs(ws))
    assert "orn_SECRETTOKEN" not in (hp.key_dir(ws) / "handoffs.json").read_text()
    item = hp.handoff_take(ws, card["id"])  # what the page runs after the click
    assert "orn_SECRETTOKEN" in item["argv"] and item["argv"][:2] == ["relay", "connect"]
    assert not list(hp.key_dir(ws).glob("handoff-*.secret"))  # the secret is spent with the click
    assert hp.handoff_take(ws, card["id"]) is None


def test_dismiss_removes_the_secret_too(ws, run):
    from conftest import turn_on

    turn_on(ws, "relay")
    run(
        "relay",
        "connect",
        "https://r.example",
        "--workspace",
        "w",
        "--token",
        "orn_X1",
        "--by",
        "human:pat",
        "--json",
    )
    assert list(hp.key_dir(ws).glob("handoff-*.secret"))
    hp.handoff_drop(ws, hp.handoffs(ws)[0]["id"])
    assert not list(hp.key_dir(ws).glob("handoff-*.secret"))


def test_browser_opens_only_for_a_newly_queued_item_and_at_most_every_30_s(ws, run, monkeypatch):
    opened = []
    monkeypatch.setattr(hp, "open_browser", lambda url: opened.append(url) or True)
    monkeypatch.setattr(hp.term, "is_terminal", lambda f: True)
    monkeypatch.setattr(
        "orch.services.workspace_rows", lambda root: [{"addon": "dashboard", "url": "http://127.0.0.1:9"}]
    )
    tid, q = _ask(ws, run)
    run("answer", tid, q, "A", "--by", "human:pat", "--json")  # new: opens
    run("answer", tid, q, "A", "--by", "human:pat", "--json")  # same request again: no new browser
    tid2, q2 = _ask(ws, run)
    run("answer", tid2, q2, "B", "--by", "human:pat", "--json")  # new, but within 30 s: no browser
    assert len(opened) == 1 and "#launch=" in opened[0]


def test_relay_allow_works_via_the_hand_off_and_the_title_is_in_the_label(ws, run, monkeypatch):
    from conftest import turn_on

    from orch import relay

    turn_on(ws, "relay")
    monkeypatch.setattr(
        relay,
        "load_message",
        lambda root, mid: {"from": "ws_peer", "type": "delegate", "body": {"title": "Fix it"}},
    )
    given = []
    monkeypatch.setattr(
        relay,
        "give_allow",
        lambda root, mid, mode: given.append((mid, mode)) or {"body": {"mode": mode}, "to": "ws_peer"},
    )
    monkeypatch.setattr(relay, "name_of", lambda root, w: "Peer")
    code, out, err = run("relay", "allow", "m_deleg00000000010", "--once", "--by", "human:pat", "--json")
    assert code == 2 and given == []
    card = hp.handoffs(ws)[0]  # it IS queued now
    assert card["op"] == "relay.allow" and card["parts"] == {"peer": "Peer", "task": "Fix it", "mode": "once"}
    assert "ws_peer" not in json.dumps(card["parts"])
    item = hp.handoff_take(ws, card["id"])
    assert item["argv"][:2] == ["relay", "allow"]
    proof = hp.mint(hp.human_key(ws), hp.new_payload(item["op"], item["target"], "human:pat"))
    monkeypatch.setattr("sys.stdin", io.StringIO(proof + "\n"))
    code, out, err = run(*item["argv"], "--proof-stdin")
    assert code == 0, out + err
    assert given == [("m_deleg00000000010", "once")]


def test_an_abbreviated_token_option_does_not_slip_past_the_split(ws, run):
    from conftest import turn_on

    turn_on(ws, "relay")
    with pytest.raises(SystemExit):  # `--tok` is not an option any more: usage error, nothing is queued
        run(
            "relay",
            "connect",
            "https://r.example",
            "--workspace",
            "w",
            "--tok",
            "orn_ABBREV",
            "--by",
            "human:pat",
        )
    assert hp.handoffs(ws) == []
    f = hp.key_dir(ws) / "handoffs.json"
    assert not f.exists() or "orn_ABBREV" not in f.read_text()


def test_a_second_identical_connect_keeps_the_first_token_and_drops_the_new_one(ws, run):
    from conftest import turn_on

    turn_on(ws, "relay")
    base = ("relay", "connect", "https://r.example", "--workspace", "w", "--by", "human:pat", "--json")
    run(*base, "--token", "orn_FIRST")
    run(*base, "--token", "orn_SECOND")
    items = hp.handoffs(ws)
    assert len(items) == 1
    assert "orn_FIRST" in hp.handoff_take(ws, items[0]["id"])["argv"]


def test_expired_secret_files_are_removed_on_read(ws, run):
    from conftest import turn_on

    turn_on(ws, "relay")
    run(
        "relay",
        "connect",
        "https://r.example",
        "--workspace",
        "w",
        "--token",
        "orn_OLD",
        "--by",
        "human:pat",
        "--json",
    )
    d = hp.key_dir(ws)
    items = json.loads((d / "handoffs.json").read_text())
    items[0]["exp"] = 1  # long expired
    hp._write_private(d / "handoffs.json", json.dumps(items))
    assert hp.handoffs(ws) == []
    assert not list(d.glob("handoff-*.secret"))


def test_an_unusable_key_folder_refuses_visibly_and_saves_nothing(ws, run, monkeypatch):
    tid, q = _ask(ws, run)
    proof = _proof(ws, "ticket.answer", f"{tid}:{q}")
    monkeypatch.setattr(runs, "_pending_proof", lambda root, tid: None)  # key folder unusable at write time
    code, out, err = _cli(run, monkeypatch, proof, "answer", tid, q, "A", "--json")
    assert (
        code == 2
        and "Not saved" in out + err
        and "start it again" in out + err
        and "orch doctor" not in out + err
    )
    assert tickets.load(ws, tid)["questions"][0].get("answer") is None  # not half done
    # Send back: the note is not queued without a MAC either, and the ticket stays in Review
    rid = _review_ticket(ws, run)
    proof = _proof(ws, "ticket.verdict", rid)
    code, out, err = _cli(run, monkeypatch, proof, "ticket", "changes", rid, "more", "--json")
    assert code == 2 and "Not saved" in out + err and tickets.load(ws, rid)["status"] == "review"
    assert runs.undelivered(ws, rid) == []


def _demo(ws):
    """A dev demo workspace under the test prefix, marked at creation (the dev installer's step)."""
    fresh = ws.parent / "demo"
    (fresh / ".orch").mkdir(parents=True)
    hp.dev_mark(fresh)
    return fresh


def test_dev_proof_command_works_only_in_a_dev_workspace(ws, run, monkeypatch):
    code, out, err = run("dev-proof", "update", "orch")  # a test workspace without a dev record
    assert code == 2 and "hp1." not in out
    fresh = _demo(ws)
    monkeypatch.chdir(fresh)
    code, out, err = run("dev-proof", "ticket.answer", "t_a:q1")
    assert code == 0 and out.strip().startswith("hp1.")
    assert hp.verify_and_consume(fresh, out.strip(), "ticket.answer", "t_a:q1") == "human:test-human"


def test_dev_proof_refuses_a_dev_install_a_normal_install_and_a_real_workspace(ws, run, monkeypatch):
    fresh = _demo(ws)
    monkeypatch.chdir(fresh)
    for kind in ("dev", "normal"):
        monkeypatch.setattr(hp, "install_kind", lambda k=kind: k)
        code, out, err = run("dev-proof", "update", "orch")
        assert code == 2 and "hp1." not in out  # only a TEST install, even with the dev record
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    outside = ws.parent.parent / "real-ws"  # not under .orch-test
    (outside / ".orch").mkdir(parents=True)
    monkeypatch.chdir(outside)
    code, out, err = run("dev-proof", "update", "orch")
    assert code == 2 and "hp1." not in out


def test_dev_proof_refuses_an_orch_started_agent_context(ws, run, monkeypatch):
    fresh = _demo(ws)
    monkeypatch.chdir(fresh)
    for k in ("ORCH_RUN", "ORCH_TICKET", "ORCH_VIA", "CLAUDECODE"):
        monkeypatch.setenv(k, "x")
        code, out, err = run("dev-proof", "update", "orch")
        assert code == 2 and "hp1." not in out, k
        monkeypatch.delenv(k)
    code, out, err = run("dev-proof", "update", "orch", "--by", "agent:helper")
    assert code == 2 and "hp1." not in out
    assert run("dev-proof", "update", "orch")[0] == 0  # the clean harness context works


def test_dev_proof_allowlist_and_a_log_without_secrets(ws, run, monkeypatch):
    fresh = _demo(ws)
    monkeypatch.chdir(fresh)
    code, out, err = run("dev-proof", "config.share", "on")  # a real op, but not one the e2e scripts need
    assert code == 2 and "hp1." not in out
    code, proof, err = run("dev-proof", "update", "orch")
    assert code == 0
    log = (hp.key_dir(fresh) / "dev-proof.log").read_text()
    assert "dev:test-human minted op=update" in log and proof.strip() not in log and "hp1" not in log


# ------------------------------------------------------------------ chat: make-ticket, DM ops


def _proposal(ws):
    from orch import chat

    chat.record(ws, "person", "you", "dashboard", "Fish", convo_start=True)
    chat.record(
        ws,
        "m_proposal0000001",
        "ws_helper01",
        "helper",
        "Ready?",
        refs=[{"kind": "proposal", "title": "Fish"}],
    )
    return "m_proposal0000001"


def test_make_ticket_needs_the_proof_in_the_cli_and_hands_off(ws, run, monkeypatch):
    mid = _proposal(ws)
    code, out, err = run("chat", "make-ticket", mid, "--by", "human:pat", "--json")
    assert code == 2 and "Continue" in out + err
    assert (
        not [t for t in tickets.list_all(ws) if t.get("title") == "Fish"]
        if hasattr(tickets, "list_all")
        else True
    )
    card = hp.handoffs(ws)[0]
    assert card["op"] == "chat.make_ticket" and card["target"] == mid
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "chat.make_ticket", mid), "chat", "make-ticket", mid, "--json"
    )
    assert code == 0, out + err
    assert json.loads(out)["key"]


def test_make_ticket_forged_by_with_a_proof_for_another_message_is_refused(ws, run, monkeypatch):
    mid = _proposal(ws)
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "chat.make_ticket", "m_other"), "chat", "make-ticket", mid, "--json"
    )
    assert code == 2 and "dashboard on this computer" in out + err


def test_the_phone_path_makes_the_ticket_in_process_from_the_relay_sender_only(ws):
    """relay._apply_proposal_answer calls chat.make_ticket(root, mid, None, by) with the relay-authenticated
    `human:<phone>`: no proof is read there. An agent in the environment, or a by that is not human:, is
    refused inside chat itself, so the in-process call is not an unproven way for an agent."""
    from orch import chat

    mid = _proposal(ws)
    with pytest.raises(Refused):
        chat.make_ticket(ws, mid, None, "agent:x")
    made = chat.make_ticket(ws, mid, None, "human:ph_abcdef")
    assert made["key"]


def test_dm_reads_and_sync_need_no_proof_and_confer_no_person_input(ws, run):
    """contacts / thread / sync are read-only for orch's authority: no proof, no hand-off per poll, and they
    never write a person-class pending line (the pending MAC is only written for proven input)."""
    for argv in (("chat", "contacts"), ("chat", "sync")):
        code, out, err = run(*argv, "--by", "human:pat", "--json")
        assert "dashboard on this computer" not in out + err and "Continue" not in out + err
    assert hp.handoffs(ws) == []


# ------------------------------------------------------------------ update/ORCH_REF and folder add-ons


def test_update_source_is_resolved_first_shown_and_part_of_the_proof(ws, run, monkeypatch):
    """Normal install: ORCH_REPO / ORCH_REF set by an agent are ignored; the card shows the official source
    and the proof target is that source, so a proof for another source does not verify."""
    from orch import addons

    monkeypatch.setattr(addons, "_env_source_ok", lambda: False)  # a normal install (no env override)
    monkeypatch.setattr(addons, "_install_origin", lambda: {})
    monkeypatch.setenv("ORCH_REPO", "https://github.com/evil/fork")
    monkeypatch.setenv("ORCH_REF", "evil")
    seen = {}
    monkeypatch.setattr(
        addons, "update", lambda *a, **k: seen.update(repo=addons.repo(), ref=addons.ref()) or []
    )
    code, out, err = run("update", "--by", "human:pat", "--json")
    assert code == 2
    card = hp.handoffs(ws)[0]
    assert card["parts"] == {"source": f"{addons.DEFAULT_REPO}@main"} and "evil" not in json.dumps(
        card["parts"]
    )
    assert card["target"] == hp.update_target(addons.DEFAULT_REPO, "main")
    # a proof for the fork's source does not verify for this update
    bad = _proof(ws, "update", hp.update_target("https://github.com/evil/fork", "evil"))
    code, out, err = _cli(run, monkeypatch, bad, "update", "--json")
    assert code == 2 and "repo" not in seen
    # the proof for the shown source runs, and installs from exactly that source (the env is still ignored)
    good = _proof(ws, "update", card["target"])
    code, out, err = _cli(run, monkeypatch, good, "update", "--json")
    assert code == 0, out + err
    assert seen == {"repo": addons.DEFAULT_REPO, "ref": "main"}


def test_dev_and_test_installs_keep_the_env_override_for_e2e(ws, run, monkeypatch):
    from orch import addons

    monkeypatch.setenv("ORCH_REPO", "https://github.com/lane-c/test")
    monkeypatch.setenv("ORCH_REF", "e2e")
    run("update", "--by", "human:pat", "--json")  # test install: the override counts
    assert hp.handoffs(ws)[0]["parts"] == {"source": "https://github.com/lane-c/test@e2e"}
    assert addons.repo() == "https://github.com/lane-c/test"


def test_a_folder_addon_needs_a_click_and_installs_from_the_snapshot(ws, run, monkeypatch):
    from orch import addons

    folder = ws.parent / "my-addon"
    (folder / "src").mkdir(parents=True)
    (folder / "pyproject.toml").write_text("[project]\nname='x'\n")
    (folder / "src" / "a.py").write_text("one\n")
    monkeypatch.setattr(addons, "_local_add_ok", lambda: bool(addons._LOCAL_ADD_PROVEN))  # a normal install
    seen = {}
    monkeypatch.setattr(addons, "add", lambda *a, **k: seen.update(args=a, proven=addons._LOCAL_ADD_PROVEN))
    code, out, err = run("addon", "add", str(folder), "--yes", "--by", "human:pat", "--json")
    assert code == 2 and "args" not in seen  # refused: nothing installed
    card = hp.handoffs(ws)[0]
    info = addons.prepare_local_add(ws, folder)
    assert card["op"] == "addon.add_local" and card["target"] == info["hash"] and len(info["hash"]) == 64
    assert card["exact"] == str(folder.resolve()) and card["parts"]["short"] == info["short"]
    assert str(folder.resolve()).endswith(card["parts"]["path"].lstrip("\u2026"))
    item = hp.handoff_take(ws, card["id"])  # one click: the page takes the item and runs it with a proof
    proof = _proof(ws, item["op"], item["target"])
    code, out, err = _cli(run, monkeypatch, proof, *item["argv"])
    assert code == 0, out + err
    assert seen["proven"] == info["hash"]  # installed inside trusted_local_add(<that content hash>)
    # an agent's own add is refused outright, no hand-off by an agent
    monkeypatch.setenv("CLAUDECODE", "1")
    seen.clear()
    code, out, err = run("addon", "add", str(folder), "--yes", "--json")
    assert code == 2 and "args" not in seen


def test_a_content_swap_before_the_click_is_refused(ws, run, monkeypatch):
    from orch import addons

    folder = ws.parent / "swap-addon"
    (folder / "src").mkdir(parents=True)
    (folder / "pyproject.toml").write_text("[project]\nname='x'\n")
    (folder / "src" / "a.py").write_text("good\n")
    monkeypatch.setattr(addons, "_local_add_ok", lambda: bool(addons._LOCAL_ADD_PROVEN))
    seen = {}
    monkeypatch.setattr(addons, "add", lambda *a, **k: seen.update(args=a))
    run("addon", "add", str(folder), "--yes", "--by", "human:pat", "--json")
    card = hp.handoffs(ws)[0]
    item = hp.handoff_take(ws, card["id"])
    (folder / "src" / "a.py").write_text("EVIL\n")  # swapped after the request, before the click
    proof = _proof(ws, item["op"], item["target"])
    code, out, err = _cli(run, monkeypatch, proof, *item["argv"])
    assert code == 2 and "args" not in seen  # the proof was for the other content


# ------------------------------------------------------------------ unusable key folder: nothing looks saved


def test_chat_say_with_an_unusable_key_folder_writes_nothing(ws, run, monkeypatch):
    from orch import chat

    monkeypatch.setattr(runs, "_pending_proof", lambda root, tid: None)
    proof = _proof(ws, "chat.send", "general")
    code, out, err = _cli(run, monkeypatch, proof, "chat", "say", "Hello team", "--json")
    assert code == 2 and "Not saved" in out + err
    day = chat.read_day(ws, chat.day_key(ws))
    assert day["messages"] == []  # no chat line that looks saved while the error says it is not
    assert (
        not [t for t in tickets.list_tickets(ws) if t.get("general")]
        if hasattr(tickets, "list_tickets")
        else True
    )


def test_a_phone_text_with_an_unusable_key_folder_retries_then_tells_the_phone(ws, monkeypatch):
    from orch import chat, relay

    monkeypatch.setattr(runs, "_pending_proof", lambda root, tid: None)
    sent = []
    monkeypatch.setattr(relay, "send_text", lambda root, to, text, **k: sent.append((to, text, k)) or {})
    msg = {
        "id": "m_phonetext00000001",
        "from": "ph_abcdefghij",
        "type": "text",
        "body": {"text": "hi", "general": True},
    }
    with pytest.raises(relay.Transient):  # tried again on the next pulls, not marked seen
        relay._phone_text(ws, msg, final=False)
    assert sent == []
    note, tid = relay._phone_text(ws, msg, final=True)  # the last try: a plain reply, nothing written
    assert "not saved" in note and len(sent) == 1
    to, text, kw = sent[0]
    assert to == "ph_abcdefghij" and "Not saved on the computer" in text and "Try again shortly" in text
    assert kw["reply_to"] == msg["id"]
    assert chat.read_day(ws, chat.day_key(ws))["messages"] == []


def test_the_queued_add_command_carries_the_absolute_path_the_card_shows(ws, run, monkeypatch):
    from orch import addons

    folder = ws.parent / "rel-addon"
    (folder / "src").mkdir(parents=True)
    (folder / "pyproject.toml").write_text("[project]\nname='x'\n")
    (folder / "src" / "a.py").write_text("x\n")
    sub = ws / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)  # the requester's cwd is a subfolder; the page runs the command from the root
    monkeypatch.setattr(addons, "_local_add_ok", lambda: bool(addons._LOCAL_ADD_PROVEN))
    monkeypatch.setattr(hp, "CURRENT_ARGV", ["addon", "add", "../../rel-addon", "--yes"])
    code, out, err = run("addon", "add", "../../rel-addon", "--yes", "--by", "human:pat", "--json")
    assert code == 2
    card = hp.handoffs(ws)[0]
    item = hp.handoff_take(ws, card["id"])
    assert card["exact"] == str(folder.resolve()) and str(folder.resolve()) in item["argv"]
    assert "../../rel-addon" not in item["argv"]


# ------------------------------------------------------------------ the detached update: log and result


def _run_runner(ws, monkeypatch, code_text):
    monkeypatch.chdir(ws)
    monkeypatch.setattr("sys.stdin", io.StringIO("hp1.proof\n"))
    return pageproof._runner([sys.executable, "-c", code_text])


def test_runner_records_a_finished_update(ws, monkeypatch):
    assert _run_runner(ws, monkeypatch, "import sys; sys.stdin.read(); print('ok')") == 0
    assert hp.take_update_status(ws) == {"state": "finished", "reason": ""}
    assert hp.take_update_status(ws) is None  # read once
    assert (hp.key_dir(ws) / "update.log").read_text().strip() == "ok"  # the log, in the guarded folder


def test_runner_records_a_failed_update_with_a_short_plain_reason_and_no_proof(ws, monkeypatch):
    code = (
        "import sys; sys.stdin.read(); print('working'); print('Refused: The server said no.'); sys.exit(2)"
    )
    assert _run_runner(ws, monkeypatch, code) == 2
    st = hp.take_update_status(ws)
    assert st == {"state": "failed", "reason": "The server said no."}
    assert "hp1." not in (hp.key_dir(ws) / "update.log").read_text()  # the proof is never in the log


def test_runner_stops_a_hung_update(ws, monkeypatch):
    monkeypatch.setattr(hp, "UPDATE_TIMEOUT", 0.5)
    assert _run_runner(ws, monkeypatch, "import time; time.sleep(30)") == 1
    st = hp.take_update_status(ws)
    assert st["state"] == "failed" and "too long" in st["reason"]


def test_every_card_sentence_is_plain_words_without_json_or_ids(ws, run):
    tid = _review_ticket(ws, run)
    rev = str(tickets.load(ws, tid)["revision"])
    run("ticket", "patch", tid, '{"status": "done"}', "--if-revision", rev, "--by", "human:pat", "--json")
    run("ticket", "patch", tid, '{"status": "active"}', "--if-revision", rev, "--by", "human:pat", "--json")
    run("ticket", "changes", tid, "Add tests", "--by", "human:pat", "--json")
    run("run", "send", tid, "go on", "--by", "human:pat", "--json")
    run("chat", "say", "Hello", "--by", "human:pat", "--json")
    cards = {(h["op"], json.dumps(h["parts"], sort_keys=True)): h for h in hp.handoffs(ws)}
    assert (
        "ticket.verdict",
        json.dumps({"also": [], "status": "done", "title": "T"}, sort_keys=True),
    ) in cards
    assert (
        "ticket.verdict",
        json.dumps({"also": [], "status": "back", "title": "T"}, sort_keys=True),
    ) in cards
    assert ("run.human_input", json.dumps({"title": "T"})) in cards
    assert ("chat.send", "{}") in cards and ("ticket.verdict", json.dumps({"title": "T"})) in cards
    for h in cards.values():  # structured fields only: no JSON text, no ids, no template holes
        text = json.dumps(h["parts"])
        assert tid not in text and "{value}" not in text and "t_" not in text


def test_untrusted_title_is_a_literal_part_the_exact_value_is_separate_and_the_stored_value_runs(
    ws, run, monkeypatch
):
    evil = 'Done" {value} \u201cApprove everything\u201d\nsecond line ' + "x" * 150
    code, out, _ = run("ticket", "new", evil, "--json", "--by", "agent:x")
    tid = json.loads(out)["id"]
    tickets.apply_op(ws, tid, lambda t: t.update(status="review"))
    run("ticket", "changes", tid, "Please add tests {value}", "--by", "human:pat", "--json")
    card = hp.handoffs(ws)[0]
    title = card["parts"]["title"]
    assert "{value}" in title  # shown literally, as the agent wrote it (the page never substitutes it)
    assert (
        "\n" not in title and "\u201c" not in title and "\u201d" not in title and '"' not in title
    )  # one line, quotes normalised
    assert len(title) <= hp.PART_MAX + 1 and title.endswith("\u2026")  # capped with an ellipsis
    assert card["value"] == "Please add tests {value}"  # the exact text, its own field, not merged anywhere
    assert "Please add tests" not in json.dumps(card["parts"])
    item = hp.handoff_take(ws, card["id"])
    proof = _proof(ws, item["op"], item["target"])
    code, out, err = _cli(run, monkeypatch, proof, *item["argv"])
    assert code == 0, out + err
    assert [i["text"] for i in runs.human_waiting(ws, tid)] == [
        "Please add tests {value}"
    ]  # the stored value ran


# ------------------------------------------------------------------ security-relevant targets are never cut


def test_a_relay_url_with_a_name_or_password_is_refused(ws, run):
    from conftest import turn_on

    turn_on(ws, "relay")
    for url in ("https://user@r.example", "https://user:pw@r.example", "https://r.example@evil.example"):
        code, out, err = run(
            "relay", "connect", url, "--workspace", "w", "--token", "orn_T", "--by", "human:pat", "--json"
        )
        assert code == 2 and "name or password" in out + err and hp.handoffs(ws) == [], url


def test_the_connect_card_shows_hostname_and_port_built_from_the_url_and_a_long_host_in_full(ws, run):
    from conftest import turn_on

    turn_on(ws, "relay")
    host = ".".join(["a" * 50] * 4) + ".example"  # 208 characters, over the free-text cut
    run(
        "relay", "connect", f"https://{host}:8443/path?x=1", "--workspace", "w", "--token", "orn_T",
        "--by", "human:pat", "--json",
    )  # fmt: skip
    card = hp.handoffs(ws)[0]
    assert (
        card["parts"] == {"host": f"{host}:8443", "scheme": "https"} and card["exact"] == f"{host}:8443"
    )  # in full, no cut, no path
    assert hp.part(host).endswith("…")  # (free text WOULD have been cut)


def test_the_update_source_is_shown_in_full(ws, run, monkeypatch):
    from orch import addons

    long_repo = "https://example.org/" + "r" * 200
    monkeypatch.setenv("ORCH_REPO", long_repo)  # a test install honours the override
    monkeypatch.setenv("ORCH_REF", "main")
    run("update", "--by", "human:pat", "--json")
    card = hp.handoffs(ws)[0]
    assert card["parts"]["source"] == card["exact"] == f"{addons.repo()}@{addons.ref()}"
    assert len(card["exact"]) > hp.PART_MAX


def test_a_long_addon_path_shows_its_end_in_the_sentence_and_the_full_path_in_the_exact_block(
    ws, run, monkeypatch
):
    from orch import addons

    deep = ws.parent
    for i in range(6):
        deep = deep / (f"long-folder-name-{i}-" + "x" * 20)
    folder = deep / "real-folder"
    (folder / "src").mkdir(parents=True)
    (folder / "pyproject.toml").write_text("[project]\nname='x'\n")
    (folder / "src" / "a.py").write_text("x\n")
    monkeypatch.setattr(addons, "_local_add_ok", lambda: bool(addons._LOCAL_ADD_PROVEN))
    run("addon", "add", str(folder), "--yes", "--by", "human:pat", "--json")
    card = hp.handoffs(ws)[0]
    assert card["exact"] == str(folder.resolve()) and len(card["exact"]) > 100
    assert card["parts"]["path"].startswith("…") and card["parts"]["path"].endswith("/real-folder")  # the END
    assert hp.handoff_take(ws, card["id"]) is not None
    # a card whose full target is not what the command carries is never run
    run("addon", "add", str(folder), "--yes", "--by", "human:pat", "--json")
    d = hp.key_dir(ws)
    items = json.loads((d / "handoffs.json").read_text())
    items[0]["exact"] = "/somewhere/else"
    hp._write_private(d / "handoffs.json", json.dumps(items))
    assert hp.handoff_take(ws, items[0]["id"]) is None


def test_free_text_is_cut_in_the_sentence_but_the_exact_block_keeps_it_whole(ws, run):
    tid, q = _ask(ws, run)
    long_answer = "word " * 100
    run("answer", tid, q, long_answer, "--by", "human:pat", "--json")
    card = hp.handoffs(ws)[0]
    assert card["value"] == long_answer  # whole
    assert len(card["parts"]["question"]) <= hp.PART_MAX + 1


# ------------------------------------------------------------------ #386 Won't do: needs the proof


def _ticket_with_step(ws, run):
    code, out, _ = run("ticket", "new", "Plan", "--json", "--by", "agent:x")
    tid = json.loads(out)["id"]
    code, out, _ = run("check", "add", tid, "Write the file", "--json", "--by", "agent:x")
    return tid, json.loads(out)["id"]


def test_wont_do_needs_the_proof_and_hands_off_with_plain_parts(ws, run, monkeypatch):
    tid, cid = _ticket_with_step(ws, run)
    code, out, err = run(
        "check", "wont-do", tid, cid, "--reason", "not needed", "--by", "human:pat", "--json"
    )
    assert code == 2 and "Continue" in out + err
    assert not tickets.load(ws, tid)["checklist"][0].get("wont_do")
    card = hp.handoffs(ws)[0]
    assert (
        card["op"] == "check.wont_do" and card["target"] == f"{tid}:{cid}" and card["value"] == "not needed"
    )
    assert card["parts"] == {"title": "Plan", "step": "Write the file", "n": 1}
    item = hp.handoff_take(ws, card["id"])
    code, out, err = _cli(run, monkeypatch, _proof(ws, item["op"], item["target"]), *item["argv"])
    assert code == 0, out + err
    step = tickets.load(ws, tid)["checklist"][0]
    assert step["wont_do"] is True and step["by"] == "human:pat"  # by from the proof


def test_wont_do_forged_flag_and_agent_are_refused(ws, run, monkeypatch):
    tid, cid = _ticket_with_step(ws, run)
    wrong = _proof(ws, "check.wont_do", f"{tid}:c9")
    code, *_ = _cli(run, monkeypatch, wrong, "check", "wont-do", tid, cid, "--json")
    assert code == 2 and not tickets.load(ws, tid)["checklist"][0].get("wont_do")
    code, *_ = run("check", "wont-do", tid, cid, "--by", "agent:x", "--json")
    assert code == 2 and not tickets.load(ws, tid)["checklist"][0].get("wont_do")


def test_undoing_a_wont_do_needs_a_proof_but_reopening_a_done_step_stays_free(ws, run, monkeypatch):
    tid, cid = _ticket_with_step(ws, run)
    _cli(
        run, monkeypatch, _proof(ws, "check.wont_do", f"{tid}:{cid}"), "check", "wont-do", tid, cid, "--json"
    )
    code, out, err = run("check", "reopen", tid, cid, "--by", "human:pat", "--json")
    assert code == 2 and tickets.load(ws, tid)["checklist"][0].get("wont_do") is True  # still won't do
    card = [h for h in hp.handoffs(ws) if h["op"] == "check.wont_do_undo"][0]
    assert card["parts"] == {"title": "Plan", "step": "Write the file", "n": 1, "action": "reopen"}
    code, *_ = _cli(
        run,
        monkeypatch,
        _proof(ws, "check.wont_do_undo", f"{tid}:{cid}"),
        "check",
        "reopen",
        tid,
        cid,
        "--json",
    )
    assert code == 0 and not tickets.load(ws, tid)["checklist"][0].get("wont_do")
    # an ordinary done step reopens as before: no proof, no hand-off
    code, out, _ = run("check", "add", tid, "Second", "--json", "--by", "agent:x")
    c2 = json.loads(out)["id"]
    run("check", "done", tid, c2, "--note", "x", "--json", "--by", "agent:x")
    code, *_ = run("check", "reopen", tid, c2, "--by", "human:pat", "--json")
    assert code == 0


def test_undo_is_decided_under_the_lock_a_load_error_requires_the_proof_and_a_swap_is_refused(
    ws, run, monkeypatch
):
    tid, cid = _ticket_with_step(ws, run)
    # a done step: free to reopen, no proof, no hand-off
    code, out, _ = run("check", "add", tid, "Plain", "--json", "--by", "agent:x")
    plain = json.loads(out)["id"]
    run("check", "done", tid, plain, "--note", "x", "--json", "--by", "agent:x")
    assert run("check", "reopen", tid, plain, "--by", "human:pat", "--json")[0] == 0
    # the step becomes wont_do BETWEEN anything a caller could have checked and the locked reopen: the locked
    # operation itself refuses (nothing is decided before the lock)
    orig = tickets.apply_op

    def become_wont_do_first(root, t, op):
        if t == tid:
            tickets.apply_op = orig  # one swap only
            orig(root, tid, lambda x: x["checklist"][0].update(wont_do=True))
        return orig(root, t, op)

    monkeypatch.setattr(tickets, "apply_op", become_wont_do_first)
    code, out, err = run("check", "reopen", tid, cid, "--by", "human:pat", "--json")
    monkeypatch.setattr(tickets, "apply_op", orig)
    assert code == 2 and tickets.load(ws, tid)["checklist"][0].get("wont_do") is True
    assert [h for h in hp.handoffs(ws) if h["op"] == "check.wont_do_undo"]  # asked for the click instead
    # the library call itself needs the explicit proven flag
    with pytest.raises(tickets.NeedsProof):
        tickets.check_reopen(ws, tid, cid, "human:pat")
    assert tickets.check_reopen(ws, tid, cid, "human:pat", proven=True)[1]["id"] == cid


def test_a_ticket_that_cannot_be_read_fails_closed_for_the_undo(ws, run, monkeypatch):
    tid, cid = _ticket_with_step(ws, run)
    (ws / ".orch" / "tickets" / f"{tid}.json").write_text("{not json")
    code, out, err = run("check", "reopen", tid, cid, "--by", "human:pat", "--json")
    assert code == 2 and "proven" not in out  # refused: nothing was reopened without a proof


# ---------------------------------------------------------- rename / remove of a Won't do need the proof too


def _wont_do_step(ws, run, monkeypatch):
    tid, cid = _ticket_with_step(ws, run)
    _cli(
        run, monkeypatch, _proof(ws, "check.wont_do", f"{tid}:{cid}"), "check", "wont-do", tid, cid, "--json"
    )
    assert tickets.load(ws, tid)["checklist"][0]["wont_do"] is True
    return tid, cid


def test_remove_and_rename_of_a_wont_do_need_the_proof_and_hand_off(ws, run, monkeypatch):
    tid, cid = _wont_do_step(ws, run, monkeypatch)
    for argv in (("check", "remove", tid, cid), ("check", "edit", tid, cid, "Renamed")):
        code, out, err = run(*argv, "--by", "human:pat", "--json")
        assert code == 2 and "Continue" in out + err, argv
    step = tickets.load(ws, tid)["checklist"][0]
    assert step["wont_do"] is True and step["text"] == "Write the file"  # nothing changed
    cards = {h["parts"]["action"]: h for h in hp.handoffs(ws) if h["op"] == "check.wont_do_undo"}
    assert set(cards) == {"remove", "edit"} and cards["edit"]["value"] == "Renamed"
    assert cards["remove"]["parts"] == {"title": "Plan", "step": "Write the file", "n": 1, "action": "remove"}
    # with the proof: it works, and by comes from the proof
    target = f"{tid}:{cid}"
    code, *_ = _cli(
        run,
        monkeypatch,
        _proof(ws, "check.wont_do_undo", target),
        "check",
        "edit",
        tid,
        cid,
        "Renamed",
        "--json",
    )
    assert code == 0 and tickets.load(ws, tid)["checklist"][0]["text"] == "Renamed"
    code, *_ = _cli(
        run, monkeypatch, _proof(ws, "check.wont_do_undo", target), "check", "remove", tid, cid, "--json"
    )
    assert code == 0 and tickets.load(ws, tid)["checklist"] == []


def test_an_agent_cannot_remove_or_rename_a_wont_do_even_with_a_forged_flag(ws, run, monkeypatch):
    tid, cid = _wont_do_step(ws, run, monkeypatch)
    for argv in (("check", "remove", tid, cid), ("check", "edit", tid, cid, "X")):
        assert run(*argv, "--by", "agent:x", "--json")[0] == 2
    wrong = _proof(ws, "check.wont_do_undo", f"{tid}:c9")
    assert _cli(run, monkeypatch, wrong, "check", "remove", tid, cid, "--json")[0] == 2
    assert tickets.load(ws, tid)["checklist"][0]["wont_do"] is True


def test_editing_and_removing_an_ordinary_step_stay_free(ws, run):
    tid, cid = _ticket_with_step(ws, run)
    assert run("check", "edit", tid, cid, "New text", "--by", "human:pat", "--json")[0] == 0
    assert run("check", "remove", tid, cid, "--by", "human:pat", "--json")[0] == 0
    assert hp.handoffs(ws) == []


def test_the_library_edit_and_remove_decide_under_the_lock(ws, run, monkeypatch):
    tid, cid = _wont_do_step(ws, run, monkeypatch)
    with pytest.raises(tickets.NeedsProof):
        tickets.check_edit(ws, tid, cid, "x", "human:pat")
    with pytest.raises(tickets.NeedsProof):
        tickets.check_remove(ws, tid, cid, "human:pat")
    # a step that BECOMES wont_do between a caller's look and the locked operation is refused too
    t2, c2 = _ticket_with_step(ws, run)
    orig = tickets.apply_op

    def swap(root, t, op):
        if t == t2:
            tickets.apply_op = orig
            orig(root, t2, lambda x: x["checklist"][0].update(wont_do=True))
        return orig(root, t, op)

    monkeypatch.setattr(tickets, "apply_op", swap)
    with pytest.raises(tickets.NeedsProof):
        tickets.check_remove(ws, t2, c2, "human:pat")
    monkeypatch.setattr(tickets, "apply_op", orig)
    assert tickets.load(ws, t2)["checklist"][0]["wont_do"] is True


def test_wont_do_cards_show_the_step_number_and_the_connect_card_the_scheme(ws, run):
    from conftest import turn_on

    tid, cid = _ticket_with_step(ws, run)
    run("check", "wont-do", tid, cid, "--by", "human:pat", "--json")
    assert hp.handoffs(ws)[0]["parts"]["n"] == 1
    turn_on(ws, "relay")
    run(
        "relay",
        "connect",
        "http://r.example:8080",
        "--workspace",
        "w",
        "--token",
        "orn_T",
        "--by",
        "human:pat",
        "--json",
    )
    card = [h for h in hp.handoffs(ws) if h["op"] == "relay.connect"][0]
    assert card["parts"] == {"host": "r.example:8080", "scheme": "http"}


# ------------------------------------------------------------ notices: reading never clears, only "Got it"


def _queue_notice(ws):
    d = hp.key_dir(ws)
    at = "2026-11-10T00:00:00Z"
    nid = hp._notice_id("protection_reset", at, hp.RESET_NOTICE)
    note = {"id": nid, "kind": "protection_reset", "at": at, "text": hp.RESET_NOTICE}
    hp._write_private(d / "notices.json", json.dumps([note]))
    return note["id"]


def test_reading_a_notice_never_clears_it_only_the_ack_does(ws):
    nid = _queue_notice(ws)
    first, second = hp.read_notices(ws), hp.read_notices(ws)
    assert (
        first == second and first[0]["id"] == nid and first[0]["text"] == hp.RESET_NOTICE
    )  # read twice: there
    assert hp.ack_notice(ws, "nope") is False and hp.read_notices(ws)
    assert hp.ack_notice(ws, nid) is True
    assert hp.read_notices(ws) == []  # acknowledged: gone
    assert hp.ack_notice(ws, nid) is False


def test_the_cli_says_the_notice_once_and_the_page_still_has_it(ws, run, capsys):
    _queue_notice(ws)
    code, out, err = run("ticket", "list", "--json")
    assert code == 0 and hp.RESET_NOTICE in err  # said once, in words, on stderr (stdout stays JSON)
    json.loads(out)
    code, out, err = run("ticket", "list", "--json")
    assert hp.RESET_NOTICE not in err  # not twice
    assert [n["text"] for n in hp.read_notices(ws)] == [hp.RESET_NOTICE]  # the page still shows it
