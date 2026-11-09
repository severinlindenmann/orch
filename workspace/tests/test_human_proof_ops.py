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
        assert hp.request_handoff(ws, "update", f"orch{i}") is True
    assert hp.request_handoff(ws, "update", "orch9") is False  # dropped, nothing evicted
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
    assert argv[:3] == [pageproof.sys.executable, "-I", "-m"] and "planted" not in " ".join(argv)
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


def test_handoff_take_only_runs_the_allowed_command_words(ws):
    hp.request_handoff(ws, "ticket.answer", "t_a:q1", argv=["config", "set", "x", "y"])
    hid = hp.handoffs(ws)[0]["id"]
    assert hp.handoff_take(ws, hid) is None  # wrong words for this op
    hp.request_handoff(ws, "ticket.answer", "t_a:q1", argv=["answer", "t_a", "q1", "--", "x"])
    hid = [h for h in hp.handoffs(ws) if h["argv"][0] == "answer"][0]["id"]
    assert hp.handoff_take(ws, hid)["argv"][0] == "answer"
    assert hp.handoff_take(ws, hid) is None  # one click, one run


def test_handoff_click_delivers_the_answer_and_it_counts_as_a_person(ws, run, monkeypatch):
    """What the dashboard does on Continue: take the item, mint, run the stored command with the proof."""
    tid, q = _ask(ws, run)
    run("answer", tid, q, "Blue", "--by", "human:pat", "--json")
    item = hp.handoff_take(ws, hp.handoffs(ws)[0]["id"])
    proof = hp.mint(hp.human_key(ws), hp.new_payload(item["op"], item["target"], "human:pat"))
    code, out, err = _cli(run, monkeypatch, proof, *item["argv"])
    assert code == 0, out + err
    assert tickets.load(ws, tid)["questions"][0]["answer"] == "Blue"
