"""H1 on the first batch of ops (slice 1.0a-2): forged flags, missing / expired / wrong target / wrong op /
replayed proofs, the dev test human, the pending start flows, launch token, hand-off."""

import io
import json
import os
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
    assert hp.write_launch_token(ws, "mine") is None  # a local add-on never gets one


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
    assert card["value"] == "Blue -- really" and "Which one?" in card["label"] and "Q" in card["label"]
    assert not card["label"].startswith("t_") and tid not in card["label"]  # plain words, no raw id
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
    assert card["op"] == "relay.connect" and "r.example" in card["label"] and "ws_a" in card["label"]
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
