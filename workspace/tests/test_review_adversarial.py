"""Adversarial tests for the Review stack (security review of feature/review-stack, 15 Nov 2026).

Each test pins a finding that is fixed (the attack is refused).
"""

import hashlib
import io
import json
import sys

import pytest
from test_review_server import _reviewed, req, sign_in, srv, ws  # noqa: F401 - shared helpers  # noqa: F401 - fixtures

from orch import humanproof as hp
from orch import review, review_server, tickets
from orch.errors import Refused

PNG = b"\x89PNG\r\n\x1a\nXX"
# conftest._legacy_trust trusts `--by human:` for every module not named in REAL_PROOF_MODULES (not this one,
# and neither is test_review_server). Keep the REAL proof gate here: take the originals at import time (before
# any fixture patches them) and put them back after the conftest fixture ran.
_REAL = {
    (hp, "person_by"): hp.person_by,
    (hp, "ENFORCE_PENDING_MAC"): hp.ENFORCE_PENDING_MAC,
    (tickets, "set_status"): tickets.set_status,
    (tickets, "patch"): tickets.patch,
    (tickets, "accept_review"): tickets.accept_review,
}


@pytest.fixture(autouse=True)
def _real_proof(_legacy_trust, monkeypatch):
    for (mod, name), fn in _REAL.items():
        monkeypatch.setattr(mod, name, fn)


def _card(root, run, *extra):
    code, out, _ = run("ticket", "new", "Q", "--json", "--by", "agent:x")
    tid = json.loads(out)["id"]
    args = extra or ("--draft", "Block", "--then", "I build it.")
    code, out, err = run("review", "add", tid, *args, "--json", "--by", "agent:x")
    assert code == 0, out + err
    q = json.loads(out)
    return tid, q["id"], tickets.question_digest(q)


def _proof(root, op, target, by="human:pat"):
    return hp.mint(hp.human_key(root), hp.new_payload(op, target, by))


def _go(run, monkeypatch, proof, *argv):
    monkeypatch.setattr("sys.stdin", io.StringIO((proof + "\n") if proof else ""))
    return run("review", "answer", *argv, "--proof-stdin", "--json")


# ------------------------------------------------------------------ Q1: answers as the person


def test_a_proof_is_spent_once(ws, run, monkeypatch):  # noqa: F811
    """Replay of a captured page proof: the nonce is spent by the first answer."""
    tid, qid, d = _card(ws, run, "--choose", "Pick", "--then", "x", "--option", "A=One", "--option", "B=Two")
    proof = _proof(ws, "ticket.answer", f"{tid}:{qid}:{d}")
    code, out, err = _go(run, monkeypatch, proof, tid, qid, "--verdict", "ok", "--picked", "A", "--digest", d)
    assert code == 0, out + err
    # the same proof again (would be a change: "Use B") is refused
    code, out, _ = _go(run, monkeypatch, proof, tid, qid, "--verdict", "ok", "--picked", "B", "--digest", d)
    assert code == 2
    qs = tickets.load(ws, tid)["questions"]
    assert len(qs) == 1 and qs[0]["decision"]["picked"] == "A"


def test_check_verdict_proof_does_not_open_a_card_question(ws, run, monkeypatch):  # noqa: F811
    """A ticket.verdict proof (target = tid only) must not answer a card question on that ticket."""
    tid, qid, d = _card(ws, run)
    code, _, _ = _go(
        run, monkeypatch, _proof(ws, "ticket.verdict", tid), tid, qid, "--verdict", "ok", "--digest", d
    )
    assert code == 2 and tickets.load(ws, tid)["questions"][0]["answer"] is None


def test_terminal_review_answer_queues_no_blind_handoff(ws, run, monkeypatch):  # noqa: F811
    """A command that is not an agent tool (an agent that dropped CLAUDECODE) asks for 'Don't do';
    the person would approve a hand-off card that does not say what it does."""
    tid, qid, d = _card(ws, run)
    monkeypatch.setattr(hp, "CURRENT_ARGV", ["review", "answer", tid, qid, "--verdict", "no", "--digest", d])
    run("review", "answer", tid, qid, "--verdict", "no", "--digest", d, "--json")
    items = [i for i in hp.handoffs(ws) if i.get("op") in ("ticket.answer", "ticket.verdict")]
    shown = [json.dumps({k: i.get(k) for k in ("label", "value", "exact", "parts")}) for i in items]
    assert all('"no"' in s or "Don't do" in s for s in shown), shown


def test_agent_cannot_answer_a_review_card_with_plain_answer(ws, run):  # noqa: F811
    tid, qid, _ = _card(ws, run)
    code, out, err = run("answer", tid, qid, "Approve", "--by", "agent:other", "--json")
    assert code != 0 and tickets.load(ws, tid)["questions"][0]["answer"] is None, out + err


# ------------------------------------------------------------------ Q2: page session and fence


def test_answer_from_another_loopback_port_is_refused(srv, ws, run):  # noqa: F811
    """A page on another localhost port (an agent's dev server) the person has open: the browser sends the
    cookie, Origin is that port, Sec-Fetch-Site same-site. Without the secret, and even with it, refused."""
    port = srv.server_address[1]
    ck = sign_in(ws, port)
    tid, qid, d = _card(ws, run)
    body = {"id": f"core:q:{tid}:{qid}", "digest": d, "verdict": "ok", "picked": None, "note": None}
    for h in (
        {"Cookie": ck, "Origin": "http://127.0.0.1:9", "X-Orch-Page": None},
        {"Cookie": ck, "Origin": "http://127.0.0.1:9"},
        {"Cookie": ck, "Origin": f"http://127.0.0.1:{port}", "Sec-Fetch-Site": "same-site"},
        {"Cookie": ck, "Origin": "null"},
    ):
        assert req(port, "POST", "/api/answer", body, headers=h)[0] == 403, h
    # a simple-request CSRF (text/plain, no preflight) never reads as JSON
    st, _, _ = req(
        port, "POST", "/api/answer", json.dumps(body), headers={"Cookie": ck, "Content-Type": "text/plain"}
    )
    assert st in (400, 403)
    assert tickets.load(ws, tid)["questions"][0]["answer"] is None


def test_session_post_cross_site_and_dns_rebinding(srv, ws):  # noqa: F811
    port = srv.server_address[1]
    tok = hp.write_launch_token(ws, "review")
    for h, host in (
        ({"Origin": "http://evil.example"}, None),
        ({"Origin": f"http://attacker.test:{port}"}, f"attacker.test:{port}"),  # rebinding: foreign Host
        ({"Sec-Fetch-Site": "cross-site"}, None),
        ({"X-Forwarded-For": "1.2.3.4"}, None),
    ):
        assert req(port, "POST", "/session", {"token": tok}, headers=h, host=host)[0] == 403, h
    # a failed attempt must not have spent a good token for the person... nor handed a cookie out
    st, hd, _ = req(port, "POST", "/session", {"token": tok})
    assert "Set-Cookie" not in hd or st == 200


def test_page_and_files_cannot_be_framed_or_run_script(srv, ws, run):  # noqa: F811
    port = srv.server_address[1]
    ck = sign_in(ws, port)
    tid, _, _ = _card(ws, run)
    sha = "e" * 12
    _reviewed(
        ws, tid, sha, "x.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    )
    st, hd, _ = req(port, "GET", "/")
    csp = hd.get("Content-Security-Policy", "")
    assert (
        "frame-ancestors 'none'" in csp
        and "script-src" not in csp
        and "'unsafe-inline'" not in csp.split("style-src")[0]
    )
    st, hd, _ = req(
        port, "GET", f"/api/file?t={tid}&c={sha}&n=x.svg", headers={"Cookie": ck, "X-Orch-Page": None}
    )
    assert st == 200 and hd["X-Content-Type-Options"] == "nosniff"
    fcsp = [p.strip() for p in hd["Content-Security-Policy"].split(";")]
    assert "sandbox" in fcsp and "default-src 'none'" in fcsp  # bare sandbox: no allow-scripts
    assert "Access-Control-Allow-Origin" not in hd


# ------------------------------------------------------------------ Q3: reviewed copies


def test_reviewed_folder_links_are_refused(srv, ws, run, tmp_path):  # noqa: F811
    """An agent replaces reviewed/<sha12> (or reviewed/ itself) with a link to another folder."""
    port = srv.server_address[1]
    ck = sign_in(ws, port)
    tid, _, _ = _card(ws, run)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.png").write_bytes(PNG)
    rv = ws / ".orch" / "tickets" / tid / "reviewed"
    rv.mkdir(parents=True, exist_ok=True)
    (rv / ("d" * 12)).symlink_to(outside, target_is_directory=True)
    h = {"Cookie": ck}
    assert req(port, "GET", f"/api/file?t={tid}&c={'d' * 12}&n=leak.png", headers=h)[0] == 404
    # a sub folder link inside a real copy
    real = rv / ("f" * 12)
    real.mkdir()
    (real / "sub").symlink_to(outside, target_is_directory=True)
    assert req(port, "GET", f"/api/file?t={tid}&c={'f' * 12}&n=sub/leak.png", headers=h)[0] == 404
    # the ticket folder of another ticket through the t= value: refused by the id pattern
    assert req(port, "GET", f"/api/file?t={tid}/..&c={'f' * 12}&n=leak.png", headers=h)[0] == 404


# ------------------------------------------------------------------ Q4: digests (RULE A)


def test_rule_a_old_formula_still_matches(proj):
    """question_digest of a card-less question equals develop's formula (computed here independently)."""
    q = {"id": "q1", "text": "Go?", "options": ["Yes", "No"], "recommended": None, "kind": "plain",
         "action": None, "answer": None, "answered_by": None, "via": None}  # fmt: skip
    old = {k: q.get(k) for k in ("id", "text", "options", "kind", "action", "recommended")}
    canon = json.dumps(old, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    assert tickets.question_digest(q) == hashlib.sha256(canon.encode()).hexdigest()
    # explicit None values of the new keys do not change it either
    assert tickets.question_digest({**q, "card": None, "shown": None}) == tickets.question_digest(q)


def test_answer_mark_binds_the_decision(proj):
    from orch import history

    a = {"id": "q2", "text": "Ok?", "options": [], "recommended": None, "answer": "Don't do",
         "answered_by": "human:me", "via": "page", "decision": {"action": "dont", "summary": "Don't do",
         "replaced_by": None}}  # fmt: skip
    forged = {**a, "decision": {**a["decision"], "action": "approve"}}
    assert history._digest("answers", a) != history._digest("answers", forged)
    assert history._digest("answers", a) != history._digest("answers", {**a, "card": {"kind": "draft"}})


# ------------------------------------------------------------------ Q5: the kit is found by path


def test_a_planted_orch_ui_on_sys_path_is_not_used(tmp_path, monkeypatch):
    import orch

    plant = tmp_path / "plant" / "orch_ui"
    (plant / "static").mkdir(parents=True)
    (plant / "__init__.py").write_text("")
    (plant / "static" / "review.html").write_text("<p>fake</p>")
    marker = tmp_path / "ran"
    (plant / "origin.py").write_text(
        f"open({str(marker)!r}, 'w').close()\ndef check_request(*a, **k):\n    return None\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path / "plant"))
    for m in [m for m in sys.modules if m == "orch_ui" or m.startswith("orch_ui.")]:
        monkeypatch.delitem(sys.modules, m)
    monkeypatch.setattr(review_server, "_ORIGIN", [])
    review_server._origin_check()
    assert not marker.exists()
    d = review_server.kit_dir()
    assert (
        d is None
        or d.resolve().parent.parent == __import__("pathlib").Path(orch.__file__).resolve().parent.parent
    )


def test_review_server_mints_only_answer_ops(ws):  # noqa: F811
    from orch import pageproof

    s = pageproof.PageSession(ws, "review")
    assert s.key is not None
    for op in ("ticket.patch", "update", "relay.allow", "secret.set", "config.agent_add"):
        with pytest.raises(Refused):
            s.mint(op, "x")
    assert s.mint("ticket.answer", "t_abcdef12:q1:" + "0" * 64)


# ------------------------------------------------------------------ end to end with the REAL proof gate


def test_page_answer_end_to_end_with_the_real_proof(srv, ws, run):  # noqa: F811
    """test_review_server runs under conftest's legacy trust (--by human: is believed), so the server's minted
    op/target were never checked by the real gate there. Here they are: a card answer and a Check verdict."""
    from orch import pageproof

    port = srv.server_address[1]
    ck = sign_in(ws, port)
    tid, qid, d = _card(ws, run)
    body = {"id": f"core:q:{tid}:{qid}", "digest": d, "verdict": "ok", "picked": None, "note": None}
    st, _, out = req(port, "POST", "/api/answer", body, headers={"Cookie": ck})
    assert st == 200, out
    q = tickets.load(ws, tid)["questions"][0]
    assert q["answered_by"] == pageproof.actor() and q["via"] == "page"
    # a Check card (ticket in Review): ticket.verdict proof, Done is signed
    code, out, _ = run("ticket", "new", "R", "--json", "--by", "agent:x")
    rid = json.loads(out)["id"]
    tickets.apply_op(ws, rid, lambda t: t.update(status="review"), by=tickets.SYSTEM)
    cd = review.check_digest(tickets.load(ws, rid))
    body = {"id": f"core:review:{rid}", "digest": cd, "verdict": "ok", "picked": None, "note": None}
    st, _, out = req(port, "POST", "/api/answer", body, headers={"Cookie": ck})
    assert st == 200, out
    assert tickets.load(ws, rid)["status"] == "done"
    # replaying the same request is a NEW proof minted by the page (person's session), not a replay; a
    # stale digest is refused as changed
    st, _, out = req(port, "POST", "/api/answer", {**body, "digest": "0" * 64}, headers={"Cookie": ck})
    assert st in (409, 422), out


def test_boot_adds_the_page_secret_only_to_same_origin_paths():
    from pathlib import Path

    js = (Path(review_server.__file__).resolve().parent.parent / "orch_ui/static/review-boot.js").read_text()
    assert "startsWith('/')&&!u.startsWith('//')" in js
    assert "if(s&&same(u))" in js and "String(u).startsWith('/')" not in js


def test_record_answered_refuses_an_agent_entry_with_a_card(tmp_path):
    """Delta review L2: record_answered checks the person itself (not only its callers)."""
    import pytest

    from orch import tickets

    with pytest.raises(tickets.Refused):
        tickets.record_answered(
            tmp_path, "t_x", {"answer": "Use C", "card": {"kind": "choice"}}, "agent:x", "cli"
        )
